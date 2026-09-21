#!/usr/bin/env python3
"""Derive rankN-fair-v4.env from rankN-fair-v3.env (video limit 0 -> 2, NAME v4) and dry-run the launcher."""
import re, sys, subprocess, pathlib
rank = int(sys.argv[1]); L = pathlib.Path("/home/ben/glm53-lab")
src = L / f"private/rank{rank}-fair-v3.env"; dst = L / f"private/rank{rank}-fair-v4.env"
if not dst.exists():
    t = src.read_text()
    m = re.search(r"^EXTRA_ARGS='(.*)'$", t, re.M); assert m, "no EXTRA_ARGS line"
    base = m.group(1); assert '{"image":4,"video":0}' in base and "long-prefill" not in base
    new = base.replace('{"image":4,"video":0}', '{"image":4,"video":2}') + " --long-prefill-token-threshold 256"
    assert f"NAME=glm53-v3-r{rank}" in t and "GPU_MEMORY_UTILIZATION=0.80" in t and "MAX_NUM_BATCHED_TOKENS=2304" in t
    block = ("\n# Video enabled v4 (2026-09-21, Claude Code): same model/precision/scheduling/memory as v3;\n"
             "# only NAME and the per-prompt video limit change (0 -> 2). EXTRA_ARGS restated in full so\n"
             "# the long-prefill threshold from v2 is kept. Fixtures under $TP3_DIR/fixtures arm the video geometry gate.\n"
             f"NAME=glm53-v4-r{rank}\n"
             f"EXTRA_ARGS='{new}'\n")
    dst.write_text(t + block); dst.chmod(0o600)
    print("wrote", dst)
else:
    print("exists", dst)
out = L / f"private/launch-dry-run-fair-v4-r{rank}.txt"
p = subprocess.run(["env", "DRY_RUN=1", "ENV_FILE=" + str(dst), "bash", str(L / "prep/start-private-tp3.sh"), str(rank)], capture_output=True, text=True)
out.write_text(p.stdout + p.stderr); assert p.returncode == 0, p.stderr
s = p.stdout
lim = re.findall(r'limit-mm-per-prompt (\S+)', s)
checks = {"name": f"--name glm53-v4-r{rank}" in s, "mem080": "--gpu-memory-utilization 0.80" in s,
          "batch2304": "--max-num-batched-tokens 2304" in s, "threshold256": "--long-prefill-token-threshold 256" in s,
          "two_limits_last_video2": len(lim) == 2 and lim[-1].replace("\\", "") == '{"image":4,"video":2}',
          "eager": "--enforce-eager" in s, "fixtures_in_tp3dir": "/home/ben/glm53-lab/runtime:/opt/harem-tp3:ro" in s,
          "auth": "glm_private_auth.BearerMiddleware" in s, "cdi": "nvidia.com/gpu=all" in s, "rank": f"--node-rank {rank}" in s}
print("DRYRUN", rank, checks); assert all(checks.values()), checks
print("v4dryrunPASS rank", rank)
