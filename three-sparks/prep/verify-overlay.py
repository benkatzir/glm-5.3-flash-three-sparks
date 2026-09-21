#!/usr/bin/env python3
"""Fail before launch if the image or a staged read-only overlay has changed."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--image", required=True)
p.add_argument("--overlay", required=True, type=Path)
a = p.parse_args()
m = json.loads((a.overlay / "overlay-manifest.json").read_text())
image_id = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", a.image], text=True).strip()
if image_id != m["image_id"]:
    raise SystemExit("Image differs from staged overlay image")
for name in ("sparse_attn_indexer.py", "sparse_attn_indexer_kpool.py"):
    if hashlib.sha256((a.overlay / name).read_bytes()).hexdigest() != m["files"][name]["patched_sha256"]:
        raise SystemExit("Overlay SHA256 mismatch: " + name)
print("Image and both read-only indexer overlay hashes verified")
