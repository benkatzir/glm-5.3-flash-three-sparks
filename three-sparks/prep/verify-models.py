#!/usr/bin/env python3
"""Verify all files against an acquisition manifest without downloading anything.

Uses download-models.py's exact size, SHA-256, and Git-blob verification routine.
Takes the same exclusive download lock: run only after download or replication finishes.
No cache or credential writes. Optional report uses a new output filename only.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import time

PINNED_FULL_MANIFEST_SHA256 = "9d86dd90d73ebf4f5817a6e65afe7ead5dd01f0e93aa584016cd4ec35c60d330"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("download-manifest.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-manifest-sha256", default=PINNED_FULL_MANIFEST_SHA256,
                        help="Defaults to the reviewed complete manifest; override only for an explicitly reviewed alternative.")
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error("Model root is missing")
    if args.output and args.output.exists():
        parser.error("Refusing to overwrite verification report")
    raw = args.manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.expected_manifest_sha256:
        raise SystemExit("Manifest differs from expected complete-file identity; refusing verification.")
    manifest = json.loads(raw)
    helper = Path(__file__).with_name("download-models.py")
    spec = importlib.util.spec_from_file_location("glm_pinned_download_verifier", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Use the downloader's existing lock file when possible; this never changes weights.
    with (args.root / "download.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Download/verification lock is held; wait for that operation to finish.")
        started = time.time()
        results = []
        seen = set()
        for artifact in manifest["artifacts"]:
            for item in artifact["files"]:
                relative = Path(item["path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe manifest filename")
                key = artifact["name"] + "/" + item["path"]
                if key in seen:
                    raise ValueError("Duplicate manifest file")
                seen.add(key)
                path = args.root / "models" / artifact["name"] / relative
                row = {"file": key, "bytes": item["bytes"]}
                try:
                    row.update(state="verified", sha256=module.verify(path, item))
                except Exception as exc:
                    # Avoid disclosing operational paths or exception payloads.
                    row.update(state="failed", error_type=type(exc).__name__)
                results.append(row)
        good = [row for row in results if row["state"] == "verified"]
        report = {"state": "verified" if len(good) == len(results) else "failed",
                  "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                  "verification_helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
                  "files": len(results), "verified_files": len(good),
                  "expected_bytes": sum(row["bytes"] for row in results),
                  "verified_bytes": sum(row["bytes"] for row in good),
                  "started_at": started, "finished_at": time.time(), "entries": results}
        if args.output:
            with args.output.open("x") as stream:
                json.dump(report, stream, indent=2)
                stream.write("\n")
        print(json.dumps({k: v for k, v in report.items() if k != "entries"}, indent=2))
        if report["state"] != "verified":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
