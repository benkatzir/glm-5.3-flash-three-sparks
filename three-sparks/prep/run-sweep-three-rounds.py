#!/usr/bin/env python3
"""Three sequential short-prompt sweeps (C1, C2, C4, C6, C8) with bench-private.py.
Each round must pass every request before the next starts. Run on the head.

  python3 run-sweep-three-rounds.py --root /path/to/glm53-lab --label glm53-v1
"""
import argparse, json, pathlib, subprocess

ap = argparse.ArgumentParser()
ap.add_argument("--root", type=pathlib.Path, required=True, help="lab root holding prep/ and private/api-key")
ap.add_argument("--label", required=True, help="result prefix, e.g. glm53-v1")
ap.add_argument("--rounds", type=int, default=3)
ap.add_argument("--base", default="http://127.0.0.1:8888")
a = ap.parse_args()
r = a.root
for i in range(1, a.rounds + 1):
    out = r / f"sweep-{a.label}-round{i}.json"
    assert not out.exists(), out
    cmd = ["python3", "-u", str(r / "prep/bench-private.py"), "--base", a.base, "--api-key-file", str(r / "private/api-key"),
           "--out", str(out), "--label", f"{a.label}-round{i}", "--think", "low"]
    with (r / f"sweep-{a.label}-round{i}.log").open("x") as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    rows = json.loads(out.read_text())
    assert len(rows) == 5 and all(x.get("all_requests_passed") for x in rows), rows
    print("ROUND_PASSED", i, flush=True)
