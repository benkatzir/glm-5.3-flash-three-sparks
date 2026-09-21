#!/usr/bin/env python3
"""Resumable pinned HF acquisition; SHA-256 every file, LFS SHA or Git blob check.

No root access, HF token argument, deletion, or model execution. Requires the
existing huggingface_hub installation only when actually downloading.
"""
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time


def atomic_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    os.replace(tmp, path)


def verify(path, item):
    size = path.stat().st_size
    if size != item["bytes"]:
        raise ValueError(f"Size mismatch: {path.name}: {size} != {item['bytes']}")
    sha = hashlib.sha256()
    git = hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            sha.update(chunk)
            git.update(chunk)
    digest = sha.hexdigest()
    if item.get("sha256"):
        if digest != item["sha256"]:
            raise ValueError(f"SHA256 mismatch: {path.name}")
    elif git.hexdigest() != item["git_blob_sha1"]:
        raise ValueError(f"Git blob mismatch: {path.name}")
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("download-manifest.json"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--reserve-gib", type=int, default=40)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 8 or args.reserve_gib < 0:
        parser.error("workers must be 1..8 and reserve-gib nonnegative")
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    rows = []
    for artifact in manifest["artifacts"]:
        for item in artifact["files"]:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe manifest filename")
            rows.append((artifact, item, args.root / "models" / artifact["name"] / relative))
    plan = {"root": str(args.root), "files": len(rows), "total_bytes": sum(x[1]["bytes"] for x in rows), "artifacts": [{"name": a["name"], "repo": a["repo"], "revision": a["revision"], "bytes": a["bytes"]} for a in manifest["artifacts"]]}
    if args.plan:
        print(json.dumps(plan, indent=2))
        return
    args.root.mkdir(parents=True, exist_ok=True)
    lock_handle = (args.root / "download.lock").open("a")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    remaining = sum(max(0, item["bytes"] - (path.stat().st_size if path.exists() else 0)) for _, item, path in rows)
    free = shutil.disk_usage(args.root).free
    if free < remaining + args.reserve_gib * 2**30:
        raise RuntimeError(f"Insufficient free storage: {free} bytes; need {remaining} plus {args.reserve_gib} GiB reserve")
    os.environ.setdefault("HF_HUB_CACHE", str(args.root / "cache" / "hub"))
    os.environ.setdefault("HF_XET_CACHE", str(args.root / "cache" / "xet"))
    os.environ.setdefault("HF_XET_CHUNK_CACHE_SIZE_BYTES", "0")
    from huggingface_hub import hf_hub_download

    state = {**plan, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "state": "running", "started_at": time.time(), "verified_bytes": 0, "verified_files": 0, "entries": {}}
    guard = threading.Lock()
    status = args.root / "download-status.json"

    def persist():
        with guard:
            state["updated_at"] = time.time()
            atomic_json(status, state)

    def acquire(artifact, item, path):
        key = artifact["name"] + "/" + item["path"]
        with guard:
            state["entries"][key] = {"state": "downloading", "bytes": item["bytes"]}
        # hf_hub_download keeps .incomplete files and safely resumes on restart.
        local = Path(hf_hub_download(repo_id=artifact["repo"], revision=artifact["revision"], filename=item["path"], local_dir=args.root / "models" / artifact["name"]))
        if local.resolve() != path.resolve():
            raise RuntimeError("Unexpected HF download destination")
        with guard:
            state["entries"][key]["state"] = "verifying"
        digest = verify(local, item)
        with guard:
            state["entries"][key].update(state="verified", sha256=digest, verified_at=time.time())
            state["verified_files"] += 1
            state["verified_bytes"] += item["bytes"]
        persist()

    persist()
    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(acquire, *row): row for row in rows}
        pending = set(futures)
        while pending:
            done, pending = concurrent.futures.wait(pending, timeout=5, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                try:
                    future.result()
                except Exception as exc:
                    artifact, item, _ = futures[future]
                    key = artifact["name"] + "/" + item["path"]
                    # Avoid printing HTTP exceptions which can contain signed URLs.
                    failed.append(key)
                    with guard:
                        state["entries"][key] = {"state": "failed", "error_type": type(exc).__name__}
            persist()
    state["state"] = "failed" if failed else "verified"
    state["finished_at"] = time.time()
    persist()
    print(json.dumps({"state": state["state"], "verified_files": state["verified_files"], "verified_bytes": state["verified_bytes"], "status_file": str(status), "failed_files": failed}))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
