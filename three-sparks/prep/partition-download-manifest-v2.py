#!/usr/bin/env python3
"""Partition the pinned acquisition manifest without changing its file metadata.

Local files only. No model data, credentials, network, SSH, or running process changes.
The head retains numbered target shards 1..12, all metadata, draft, and template.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re

PINNED_FULL_MANIFEST_SHA256 = "9d86dd90d73ebf4f5817a6e65afe7ead5dd01f0e93aa584016cd4ec35c60d330"
SHARD = re.compile(r"model-(\d{5})-of-00019\.safetensors\Z")
WORKER1_SHARDS = {13, 18, 19}
WORKER2_SHARDS = {14, 15, 16, 17}
ROLES = ("head", "worker1", "worker2")


def dump(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("download-manifest.json"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("download-partitions-v2"))
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    if source_hash != PINNED_FULL_MANIFEST_SHA256:
        raise SystemExit("Full manifest differs from the reviewed pin; repartition only after review.")
    source = json.loads(raw)
    groups = {role: [] for role in ROLES}
    original_items = {}
    numbered = set()
    for artifact in source["artifacts"]:
        assigned = {role: [] for role in ROLES}
        for item in artifact["files"]:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe source filename")
            key = (artifact["name"], item["path"])
            if key in original_items:
                raise ValueError("Duplicate source file")
            if not (item.get("sha256") or item.get("git_blob_sha1")):
                raise ValueError("Source file lacks verification metadata")
            original_items[key] = (artifact, item)
            role = "head"
            match = SHARD.fullmatch(item["path"]) if artifact["name"] == "target" else None
            if match:
                number = int(match[1])
                numbered.add(number)
                if number in WORKER1_SHARDS:
                    role = "worker1"
                elif number in WORKER2_SHARDS:
                    role = "worker2"
                elif number not in range(1, 13):
                    raise ValueError("Unexpected numbered shard")
            elif artifact["name"] == "target" and item["path"] == "mtp.safetensors":
                role = "worker1"
            elif item["path"].endswith(".safetensors") and artifact["name"] == "target":
                raise ValueError("Unreviewed target tensor file")
            assigned[role].append(copy.deepcopy(item))
        for role in ROLES:
            if assigned[role]:
                part = copy.deepcopy(artifact)
                part["files"] = assigned[role]
                part["bytes"] = sum(item["bytes"] for item in assigned[role])
                groups[role].append(part)
    if numbered != set(range(1, 20)):
        raise ValueError("Expected exactly numbered target shards 1..19")

    seen = set()
    proof = {"source_manifest_sha256": source_hash, "source_total_files": len(original_items),
             "source_total_bytes": source["total_bytes"], "partitions": {}}
    prepared = {}
    for role in ROLES:
        artifacts = groups[role]
        files = []
        for artifact in artifacts:
            for item in artifact["files"]:
                key = (artifact["name"], item["path"])
                original_artifact, original_item = original_items[key]
                assert key not in seen, "Overlapping partitions"
                assert item == original_item, "Per-file metadata changed"
                assert {k: v for k, v in artifact.items() if k not in ("bytes", "files")} == {
                    k: v for k, v in original_artifact.items() if k not in ("bytes", "files")}
                seen.add(key)
                files.append({"path": "models/" + artifact["name"] + "/" + item["path"], "bytes": item["bytes"]})
        total = sum(item["bytes"] for item in files)
        partition = copy.deepcopy(source)
        partition.update(artifacts=artifacts, total_bytes=total)
        partition["partition"] = {"role": role, "source_manifest_sha256": source_hash}
        prepared[role] = (partition, files)
        proof["partitions"][role] = {"files": len(files), "bytes": total,
            "target_numbered_shards": [f["path"].split("/")[-1] for f in files if SHARD.fullmatch(f["path"].split("/")[-1])],
            "target_other_tensor_files": [f["path"].split("/")[-1] for f in files if f["path"].startswith("models/target/") and f["path"].endswith(".safetensors") and not SHARD.fullmatch(f["path"].split("/")[-1])]}
    assert seen == set(original_items), "Incomplete coverage"
    assert sum(p["bytes"] for p in proof["partitions"].values()) == source["total_bytes"], "Byte totals changed"
    proof.update(disjoint=True, complete=True, original_file_metadata_preserved=True,
                 original_artifact_repo_revision_preserved=True, original_full_manifest_unchanged=True)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for role, (partition, files) in prepared.items():
        destination = args.output_dir / (role + ".json")
        dump(destination, partition)
        proof["partitions"][role]["manifest_sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
        # Paths relative to --root, suitable for rsync --files-from without HF caches.
        (args.output_dir / (role + ".files-from")).write_text("".join(item["path"] + "\n" for item in files))
    dump(args.output_dir / "partition-proof.json", proof)
    assert args.manifest.read_bytes() == raw
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
