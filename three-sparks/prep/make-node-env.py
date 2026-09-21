#!/usr/bin/env python3
"""Produce one private per-node environment, no SSH/Docker or secret creation.

Example: python3 make-node-env.py --root /home/ben/glm53-lab --rank 0
 --host-ip HEAD_MGMT_IP --head-ip HEAD_MGMT_IP --iface ACTUAL --image IMAGE_ID
The key file is private/api-key; provision it separately without logging it.
Default API bind is loopback. Use --api-bind 0.0.0.0 after auth gates pass.
"""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import shlex
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--rank", type=int, choices=range(3), required=True)
    p.add_argument("--host-ip", required=True)
    p.add_argument("--head-ip", required=True)
    p.add_argument("--iface", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--api-bind", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8888)
    a = p.parse_args()
    for v in (a.host_ip, a.head_ip, a.api_bind):
        ipaddress.IPv4Address(v)
    if not a.root.is_absolute() or re.search(r"[\s:$]", str(a.root)):
        p.error("Root must be an absolute path without whitespace, colon or dollar")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", a.iface) or not 1024 <= a.port <= 65535:
        p.error("Invalid interface or API port")
    text = (Path(__file__).parent / "upstream/tracks/tp3/env.tp3-full.example").read_text()
    for key, value in {"@NODE_RANK@": str(a.rank), "@HOST_IP@": a.host_ip, "@HEAD_IP@": a.head_ip, "@IFACE@": a.iface, "@HOME@": str(a.root.parent)}.items():
        text = text.replace(key, value)
    root = str(a.root)
    fields = {
        "NAME": f"glm53-v1-r{a.rank}", "IMAGE": a.image,
        "MODEL_HOST_PATH": root + "/models/target-tp3", "MODEL_LINK_TARGET": root + "/models/target",
        "DRAFT_HOST_PATH": root + "/models/draft-tp3", "DRAFT_LINK_TARGET": root + "/models/draft",
        "CACHE_HOST_PATH": root + "/runtime-cache", "TP3_DIR": root + "/runtime",
        "NCCL_MESH_PLUGIN_DIR": root + "/nccl-mesh", "OVERLAY_DIR": root + "/overlay-v1",
        "CHAT_TEMPLATE_HOST": root + "/models/template/chat_template.jinja",
        "AUTH_DIR": root + "/prep", "API_KEY_FILE": root + "/private/api-key",
        "API_BIND": a.api_bind, "PORT": str(a.port), "ENFORCE_EAGER": "1",
        "FASTLOAD_DIR": root + "/fastload/fullscope-image-index8192-v1", "FASTLOAD_MODE": "",
    }
    for key, value in fields.items():
        pattern = rf"^{key}=.*$"
        line = key + "=" + shlex.quote(value)
        if re.search(pattern, text, re.M):
            text, count = re.subn(pattern, lambda _: line, text, flags=re.M)
            assert count == 1
        else:
            text += "\n" + line + "\n"
    text = text.replace('HAREM_GLM47_FAILCLOSED=1 HAREM_KDA_FLASHKDA', 'HAREM_XGRAMMAR_BACKPORT=1 HAREM_GLM47_FAILCLOSED=1 HAREM_KDA_FLASHKDA')
    # Initial acceptance is still-image vision only; avoid advertising untested video.
    text = text.replace('{"image":4,"video":2}', '{"image":4,"video":0}')
    old = '/var/tmp/glm-5.3-flash-turboderp-4.05bpw-tp3/quantization_config.json'
    if old not in text:
        raise RuntimeError("hf-overrides quantization path anchor missing")
    text = text.replace(old, root + '/models/target-tp3/quantization_config.json')
    text = '# PRIVATE LOCAL ADAPTATION: eager; first cold load; authenticated image-only API.\n' + text
    private = a.root / "private"
    private.mkdir(parents=True, exist_ok=True)
    private.chmod(0o700)
    out = private / f"rank{a.rank}.env"
    with open(out, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as f:
        f.write(text)
    subprocess.run(["bash", "-n", str(out)], check=True)
    print(out)


if __name__ == "__main__":
    main()
