#!/usr/bin/env python3
"""Verify every file under three-sparks/ against source-lock.json. No network, no Torch."""
import hashlib, json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
lock = json.loads((root / "source-lock.json").read_text())["files"]
for rel, expected in lock.items():
    p = (root / rel).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise SystemExit("Missing or escaping file: " + rel)
    if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
        raise SystemExit("Checksum mismatch: " + rel)
print(f"PASS: {len(lock)} files match source-lock.json; this does not validate a rebuilt image or model quality.")
