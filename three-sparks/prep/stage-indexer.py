#!/usr/bin/env python3
"""CPU-only staging in an ephemeral image; no GPU, model, or network needed.

On the Spark: python3 stage-indexer.py --image IMAGE --root /home/ben/glm53-lab
Expects this prep directory and runtime tree already copied there. Refuses an
existing overlay instead of replacing any working deployment artifact.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess


def apply_diff(path, diff):
    text = path.read_text()
    lines = diff.read_text().splitlines(keepends=True)
    chunks = []
    active = None
    for line in lines:
        if line.startswith("@@"):
            active = [[], []]
            chunks.append(active)
        elif active is not None:
            if line.startswith(" "):
                active[0].append(line[1:]); active[1].append(line[1:])
            elif line.startswith("-"):
                active[0].append(line[1:])
            elif line.startswith("+"):
                active[1].append(line[1:])
            elif line.startswith("\\"):
                raise ValueError("Unexpected no-newline diff")
    if not chunks:
        raise ValueError("No hunks in diff")
    for old, new in chunks:
        old, new = "".join(old), "".join(new)
        if text.count(old) != 1:
            raise ValueError(f"Non-unique patch anchor in {path.name}")
        text = text.replace(old, new, 1)
    ast.parse(text)
    path.write_text(text)


def inside():
    vllm = Path(importlib.util.find_spec("vllm").origin).parent
    layer = vllm / "model_executor/layers"
    names = ["sparse_attn_indexer.py", "sparse_attn_indexer_kpool.py"]
    original = {name: hashlib.sha256((layer / name).read_bytes()).hexdigest() for name in names}
    patches = Path("/prep/upstream/patches/indexer-overlay")
    for diff in sorted(patches.glob("*.diff")):
        match = re.search(r"^\+\+\+ ([^\t ]+)", diff.read_text(), re.M)
        if not match or match[1] not in names:
            raise RuntimeError("Unexpected overlay filename")
        apply_diff(layer / match[1], diff)
    for script in ["patch-kpool-init.py", "patch-indexer-workspace-tp3.py"]:
        subprocess.run(["python3", "/runtime/" + script, "--root", str(vllm)], check=True)
    manifest = {"vllm_root": str(vllm), "files": {}}
    for name in names:
        content = (layer / name).read_bytes()
        ast.parse(content)
        shutil.copyfile(layer / name, Path("/out") / name)
        manifest["files"][name] = {"original_sha256": original[name], "patched_sha256": hashlib.sha256(content).hexdigest()}
    (Path("/out") / "overlay-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--inside", action="store_true")
    args = parser.parse_args()
    if args.inside:
        inside(); return
    if not args.image or not args.root:
        parser.error("--image and --root required")
    prep = Path(__file__).resolve().parent
    out = args.root / "overlay-v1"
    out.mkdir(parents=True, exist_ok=False)
    image_id = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", args.image], text=True).strip()
    subprocess.run(["docker", "run", "--rm", "--network", "none", "--memory", "2g", "--entrypoint", "python3", "-v", f"{prep}:/prep:ro", "-v", f"{args.root}/runtime:/runtime:ro", "-v", f"{out}:/out", image_id, "/prep/stage-indexer.py", "--inside"], check=True)
    manifest_path = out / "overlay-manifest.json"
    data = json.loads(manifest_path.read_text())
    data["image_id"] = image_id
    manifest_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Staged overlay: {out}")


if __name__ == "__main__":
    main()
