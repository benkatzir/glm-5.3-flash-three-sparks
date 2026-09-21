#!/usr/bin/env python3
"""Assemble only local upstream runtime files; no Docker, network or remote actions."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "upstream"
PIN = "7f1bd29cf473548212b8b731c52dcf2c7aa5a033"
DST = ROOT / "prepared-runtime-7f1bd29"

def main():
    actual = subprocess.check_output(["git", "-C", str(SRC), "rev-parse", "HEAD"], text=True).strip()
    if actual != PIN:
        raise SystemExit(f"Wrong upstream commit: {actual}")
    if DST.exists():
        raise SystemExit(f"Refusing to overwrite {DST}")
    patch_source = SRC / "tracks/tp3/patches"
    shutil.copytree(patch_source, DST)
    # The upstream prelude and sidecar hashing require these scripts at tree root.
    for relative in (
        "indexer-workspace/patch-indexer-workspace-tp3.py",
        "prefix-hit-and-kpool-tail/patch-prefixhit-tp3.py",
        "prefix-hit-and-kpool-tail/patch-kpooltail-tp3.py",
        "flashkda/patch-flashkda-tp3.py",
        "glm47-failclosed/patch-glm47-failclosed-tp3.py",
        "xgrammar-backports/patch-xgrammar-backports-tp3.py",
    ):
        source = patch_source / relative
        shutil.copy2(source, DST / source.name)
    for source in (patch_source / "vision").iterdir():
        if source.is_file() and source.suffix in (".py", ".sh"):
            shutil.copy2(source, DST / source.name)
    prelude = DST / "tp3full-prelude.sh"
    text = prelude.read_text()
    marker = "# --- Vision tower -------------------------------------------------------------"
    if text.count(marker) != 1:
        raise SystemExit("Vision insertion anchor mismatch")
    grammar = ('run python3 "$TP3_DIR/patch-xgrammar-backports-tp3.py" '
               '--root "$(dirname "$VLLM_PY")" --in-place\n\n')
    hook = (patch_source / "vision/prelude-vision-hook.sh").read_text()
    text = text.replace(marker, grammar + hook + "\n" + marker, 1)
    prelude.write_text(text)
    os.link(prelude, DST / "tp3-prelude.sh")
    for script in set(re.findall(r'\$TP3_DIR/([A-Za-z0-9_/-]+\.py)', text)):
        if not (DST / script).is_file():
            raise SystemExit(f"Prelude dependency missing: {script}")
    subprocess.run(["bash", "-n", str(prelude)], check=True)
    manifest = {
        "upstream_commit": PIN,
        "status": "local files assembled; no image, weights, fixtures, overlay extraction or runtime validation",
        "files": {str(p.relative_to(DST)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(DST.rglob("*")) if p.is_file()},
    }
    (ROOT / "prepared-runtime-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Prepared {DST}; shell syntax and named prelude dependencies verified")

if __name__ == "__main__":
    main()
