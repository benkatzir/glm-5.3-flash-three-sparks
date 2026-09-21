#!/usr/bin/env python3
"""Derive rankN-ctrl.env from rankN-fair-v4.env: the SCHEDULER CONTROL for the 500k A/B.
Identical to v4 (video 2, mem 0.80, eager, same image/weights/patches) except the two
scheduler settings go back to upstream's: --max-num-batched-tokens 2048 and NO
--long-prefill-token-threshold. Then dry-run the launcher and assert every setting."""
import re, sys, subprocess, pathlib
rank = int(sys.argv[1]); L = pathlib.Path("/home/ben/glm53-lab")
src = L / f"private/rank{rank}-fair-v4.env"; dst = L / f"private/rank{rank}-ctrl.env"
if not dst.exists():
    t = src.read_text()
    lines = re.findall(r"^EXTRA_ARGS='(.*)'$", t, re.M); assert lines, "no EXTRA_ARGS"
    v4 = lines[-1]; assert '{"image":4,"video":2}' in v4 and "--long-prefill-token-threshold 256" in v4
    ctrl = v4.replace(" --long-prefill-token-threshold 256", "")
    assert "long-prefill" not in ctrl
    block = ("\n# SCHEDULER CONTROL for the 500k A/B (2026-09-21, Claude Code): identical to fair-v4 except\n"
             "# upstream's scheduler settings -- batch 2048 and no long-prefill threshold. Not a serving profile.\n"
             f"NAME=glm53-ctrl-r{rank}\nMAX_NUM_BATCHED_TOKENS=2048\nEXTRA_ARGS='{ctrl}'\n")
    dst.write_text(t + block); dst.chmod(0o600); print("wrote", dst)
else:
    print("exists", dst)
out = L / f"private/launch-dry-run-ctrl-r{rank}.txt"
p = subprocess.run(["env", "DRY_RUN=1", "ENV_FILE=" + str(dst), "bash", str(L / "prep/start-private-tp3.sh"), str(rank)], capture_output=True, text=True)
out.write_text(p.stdout + p.stderr); assert p.returncode == 0, p.stderr
s = p.stdout; lim = re.findall(r'limit-mm-per-prompt (\S+)', s)
checks = {"name": f"--name glm53-ctrl-r{rank}" in s, "mem080": "--gpu-memory-utilization 0.80" in s,
          "batch2048": "--max-num-batched-tokens 2048" in s, "no_threshold": "long-prefill-token-threshold" not in s,
          "video2_last": len(lim) == 2 and lim[-1].replace("\\", "") == '{"image":4,"video":2}', "eager": "--enforce-eager" in s,
          "auth": "glm_private_auth.BearerMiddleware" in s, "cdi": "nvidia.com/gpu=all" in s, "rank": f"--node-rank {rank}" in s,
          "same_image": "sha256:af1cd7490e0bd7f47c3ede8752e87625f3e080a4f5224d9191ca455aa56cdfbb" in s}
print("DRYRUN", rank, checks); assert all(checks.values()), checks
print("ctrldryrunPASS rank", rank)
