#!/usr/bin/env python3
"""Local copy of upstream sweep: file-key auth and actual usage tokens required."""
from pathlib import Path
import ast
import shutil

root = Path(__file__).parent
source = root / "upstream/scripts/bench-sweep.py"
text = source.read_text()
edits = [
    ('BASE = os.environ.get("API", "http://192.0.2.10:8001")', '''BASE = os.environ.get("API", "http://127.0.0.1:8888")
API_KEY = None
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def private_urlopen(req, timeout):
    if isinstance(req, str):
        req = urllib.request.Request(req)
    req.add_header("Authorization", "Bearer " + API_KEY)
    return OPENER.open(req, timeout=timeout)'''),
    ('urllib.request.urlopen(BASE + "/metrics", timeout=10)', 'private_urlopen(BASE + "/metrics", timeout=10)'),
    ('urllib.request.urlopen(req, timeout=900)', 'private_urlopen(req, timeout=1800)'),
    ('    n = usage["completion_tokens"] if usage else toks', '''    if not usage or not isinstance(usage.get("completion_tokens"), int):
        raise RuntimeError("Missing actual completion-token usage; SSE chunks cannot be counted as tokens")
    n = usage["completion_tokens"]'''),
    ('    ap.add_argument("--out", required=True)', '''    ap.add_argument("--out", required=True)
    ap.add_argument("--api-key-file", required=True, help="Private key file; key is never a command argument")'''),
    ('    BASE = a.base', '''    BASE = a.base
    with open(a.api_key_file) as key_handle:
        API_KEY = key_handle.read().strip()
    if not API_KEY:
        raise SystemExit("Empty API key file")'''),
    ('return {"conc": conc, "requests": len(ok),', 'return {"conc": conc, "requests": len(ok), "attempted_requests": nreq, "failed_requests": len(res)-len(ok), "request_results": res, "all_requests_passed": len(ok)==nreq,'),
]
for old, new in edits:
    if text.count(old) != 1:
        raise SystemExit("Benchmark anchor mismatch: " + old[:60])
    text = text.replace(old, new, 1)
ast.parse(text)
(root / "bench-private.py").write_text(text)
shutil.copyfile(root / "upstream/scripts/hizset-v2.jsonl", root / "hizset-v2.jsonl")
print(root / "bench-private.py")

# The ten-question gate evaluates strings only and never executes model output.
text = (root / "upstream/scripts/correctness-probe.py").read_text()
old = 'BASE=sys.argv[1] if len(sys.argv)>1 else os.environ.get("API","http://192.0.2.10:8001")'
new = '''import argparse
_ap = argparse.ArgumentParser()
_ap.add_argument("--base", default="http://127.0.0.1:8888")
_ap.add_argument("--api-key-file", required=True)
_a = _ap.parse_args()
BASE = _a.base
with open(_a.api_key_file) as _key_handle:
    API_KEY = _key_handle.read().strip()
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def private_urlopen(req, timeout):
    req.add_header("Authorization", "Bearer " + API_KEY)
    return OPENER.open(req, timeout=timeout)'''
if text.count(old) != 1 or text.count('urllib.request.urlopen(r,timeout=300)') != 1:
    raise SystemExit("Correctness client anchor mismatch")
text = text.replace(old, new, 1).replace('urllib.request.urlopen(r,timeout=300)', 'private_urlopen(r,timeout=300)', 1)
ast.parse(text)
(root / "correctness-private.py").write_text(text)
