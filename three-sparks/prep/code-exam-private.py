#!/usr/bin/env python3
"""Private GLM coding exam; generated code runs only in an ephemeral CPU container.

Preserves all twelve prompts/assertion suites and model settings from upstream
scripts/code-exam.py (Apache-2.0). Container restrictions do not turn this small
functional gate into a general benchmark or prove model-level accuracy.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_IMAGE = "vllm/vllm-openai@sha256:905c02933be6021301db2dc284e24e3727467aa3a0f63b41d609885778a07bce"
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]
DOCKER_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
              "HOME": "/nonexistent", "DOCKER_CONFIG": "/nonexistent", "LANG": "C.UTF-8"}
TIMEOUT_SECONDS = 25
OUTPUT_LIMIT = 256 * 1024
SCRIPT_LIMIT = 64 * 1024

P=[
 ("binary_search","Write a Python function `bsearch(a, x)` that returns the index of x in the sorted list a, or -1 if absent. Use binary search. Output only the function code.",
  "assert bsearch([1,3,5,7,9],7)==3; assert bsearch([1,3,5,7,9],4)==-1; assert bsearch([],1)==-1; assert bsearch([2],2)==0"),
 ("roman","Write a Python function `to_roman(n)` converting an integer 1..3999 to a Roman numeral string. Output only the function code.",
  "assert to_roman(1)=='I'; assert to_roman(4)=='IV'; assert to_roman(1994)=='MCMXCIV'; assert to_roman(3999)=='MMMCMXCIX'"),
 ("parens","Write a Python function `balanced(s)` returning True if the brackets in s (round, square, curly) are correctly balanced and nested. Output only the function code.",
  "assert balanced('([]{})'); assert not balanced('([)]'); assert balanced(''); assert not balanced('(')"),
 ("anagram","Write a Python function `group_anagrams(words)` returning a list of lists grouping anagrams together. Output only the function code.",
  "r=group_anagrams(['eat','tea','tan','ate','nat','bat']); s=sorted(sorted(g) for g in r); assert s==[['ate','eat','tea'],['bat'],['nat','tan']], s"),
 ("lru","Write a Python function `first_unique(s)` returning the first non-repeating character of string s, or None. Output only the function code.",
  "assert first_unique('swiss')=='w'; assert first_unique('aabb') is None; assert first_unique('x')=='x'"),
 ("matrix","Write a Python function `spiral(m)` returning the elements of a 2-D list m in clockwise spiral order as a flat list. Output only the function code.",
  "assert spiral([[1,2,3],[4,5,6],[7,8,9]])==[1,2,3,6,9,8,7,4,5]; assert spiral([[1]])==[1]; assert spiral([])==[]"),
 ("intervals","Write a Python function `merge_intervals(iv)` merging overlapping intervals in a list of [start,end] pairs, returning them sorted. Output only the function code.",
  "assert merge_intervals([[1,3],[2,6],[8,10],[15,18]])==[[1,6],[8,10],[15,18]]; assert merge_intervals([])==[]"),
 ("dp","Write a Python function `lis(a)` returning the length of the longest strictly increasing subsequence of list a. Output only the function code.",
  "assert lis([10,9,2,5,3,7,101,18])==4; assert lis([])==0; assert lis([7,7,7])==1"),
 ("graph","Write a Python function `has_cycle(n, edges)` returning True if the undirected graph with n nodes (0..n-1) and the given edge list contains a cycle. Output only the function code.",
  "assert has_cycle(3,[[0,1],[1,2],[2,0]]); assert not has_cycle(3,[[0,1],[1,2]]); assert not has_cycle(1,[])"),
 ("text","Write a Python function `word_freq(text)` returning a dict of lowercase word -> count, where words are maximal runs of letters. Output only the function code.",
  "assert word_freq('The cat, the CAT!')=={'the':2,'cat':2}; assert word_freq('')=={}"),
 ("number","Write a Python function `is_palindrome_num(n)` returning True if the integer n reads the same forwards and backwards. Negative numbers are never palindromes. Output only the function code.",
  "assert is_palindrome_num(121); assert not is_palindrome_num(-121); assert is_palindrome_num(0); assert not is_palindrome_num(10)"),
 ("date","Write a Python function `days_between(a, b)` taking two 'YYYY-MM-DD' strings and returning the absolute number of days between them. Output only the function code.",
  "assert days_between('2020-01-01','2020-12-31')==365; assert days_between('2021-03-01','2021-03-01')==0; assert days_between('2020-03-01','2020-02-28')==2"),
]


def checked_image(image):
    if not re.fullmatch(r"(?:[A-Za-z0-9._:/-]+@)?sha256:[0-9a-f]{64}", image):
        raise ValueError("Sandbox image must be an immutable local digest or image ID")
    r = subprocess.run(DOCKER + ["image", "inspect", image],
                       env=DOCKER_ENV, capture_output=True, text=True, timeout=10)
    if r.returncode:
        raise RuntimeError("Pinned sandbox image is not available locally; no pull attempted")
    images = json.loads(r.stdout)
    if len(images) != 1 or images[0].get("Os") != "linux":
        raise RuntimeError("Expected exactly one local Linux image")
    if images[0].get("Config", {}).get("Volumes"):
        raise RuntimeError("Image declares automatic volumes; no volumes allowed for this exam")
    image_id = images[0]["Id"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise RuntimeError("Image inspection returned an invalid immutable image ID")
    return image_id


def container_command(image, name):
    return DOCKER + [
        "run", "--rm", "--pull=never", "--name", name, "--runtime=runc",
        "--network=none", "--read-only", "--user=65534:65534", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--memory=256m", "--memory-swap=256m",
        "--cpus=1", "--pids-limit=32", "--ulimit=cpu=20:20",
        "--ulimit=nofile=64:64", "--ulimit=core=0", "--shm-size=16m",
        "--ipc=none", "--cgroupns=private", "--no-healthcheck", "--init",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m", "--workdir=/tmp",
        "--env=NVIDIA_VISIBLE_DEVICES=void", "--log-driver=none",
        "--entrypoint=/usr/bin/env", "-i", image,
        "-i", "PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/tmp", "TMPDIR=/tmp",
        "PYTHONDONTWRITEBYTECODE=1", "python3", "-I", "-S", "-B", "-u", "-",
    ]


def execute_candidate(code, test, image):
    marker = "EXAM_DONE_" + uuid.uuid4().hex
    script = (code + "\n\n" + test + "\nprint(" + repr(marker) + ")\n").encode()
    if len(script) > SCRIPT_LIMIT:
        return False, "candidate script exceeds64KiB", {}
    name = "glm-code-exam-" + uuid.uuid4().hex
    proc = None
    started = time.monotonic()
    error = None
    metadata = {"container_name": name, "sandbox_image_id": image}
    # These anonymous host temporary files are never mounted in the container.
    # Docker forwards script bytes through stdin; generated code cannot see the
    # host script/key/result paths. File-backed output avoids unbounded RAM use.
    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        source.write(script); source.seek(0)
        try:
            proc = subprocess.Popen(container_command(image, name), stdin=source,
                                    stdout=stdout, stderr=stderr, env=DOCKER_ENV)
            deadline = started + TIMEOUT_SECONDS
            while proc.poll() is None:
                if time.monotonic() >= deadline:
                    error = "timeout25s"
                    break
                if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > OUTPUT_LIMIT:
                    error = "candidate output limit exceeded"
                    break
                time.sleep(0.05)
            if error:
                proc.kill()
            proc.wait(timeout=3)
            metadata["returncode"] = proc.returncode
            stdout.seek(0); stderr.seek(0)
            out = stdout.read(OUTPUT_LIMIT + 1)
            err = stderr.read(OUTPUT_LIMIT + 1)
            if len(out) + len(err) > OUTPUT_LIMIT:
                error = error or "candidate output limit exceeded"
            if not error and proc.returncode != 0:
                error = "candidate/container exited" + str(proc.returncode)
                # Do not print model-controlled stderr in the host terminal.
                metadata["stderr_tail"] = err[-2048:].decode(errors="replace")
            if not error and marker.encode() not in out.splitlines():
                error = "assertion completion marker missing"
        except (OSError, subprocess.SubprocessError) as exc:
            error = "container execution error: " + type(exc).__name__
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    error = "Docker client did not terminate"
            # Killing the CLI alone may leave a container running. Always force
            # cleanup by its unpredictable owned name, including timeout/error.
            try:
                cleanup = subprocess.run(DOCKER + ["rm", "-f", name],
                                         env=DOCKER_ENV, capture_output=True, timeout=5)
                if cleanup.returncode and b"No such container" not in cleanup.stderr:
                    error = "container cleanup failed; inspect owned container " + name
            except (OSError, subprocess.SubprocessError):
                error = "container cleanup unavailable; inspect owned container " + name
    metadata["wall_seconds"] = round(time.monotonic() - started, 4)
    metadata["source_sha256"] = hashlib.sha256(script).hexdigest()
    return error is None, error or "", metadata


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect refused", headers, fp)


class ModelClient:
    def __init__(self, base, api_key_file):
        url = urllib.parse.urlsplit(base)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("--base must be an HTTP(S) API origin/base path without credentials or query")
        self.base = base.rstrip("/")
        self.key = Path(api_key_file).read_text().strip()
        if not self.key or not self.key.isascii() or any(c.isspace() for c in self.key):
            raise ValueError("API key file must contain one nonempty ASCII token")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def ask(self, prompt):
        body = json.dumps({"model": "glm-5.3-flash", "messages": [{"role": "user", "content": prompt}],
                           "max_tokens": 1600, "temperature": 0.0,
                           "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "low"}}).encode()
        request = urllib.request.Request(self.base + "/v1/chat/completions", body,
                                         {"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        started = time.monotonic()
        with self.opener.open(request, timeout=600) as response:
            payload = json.load(response)
        choice = payload["choices"][0]
        message = choice["message"]
        content = (message.get("content") or "").strip()
        text = content or message.get("reasoning_content") or message.get("reasoning") or ""
        return text, {"usage": payload.get("usage"), "finish_reason": choice.get("finish_reason"),
                      "answer_field": "content" if content else "reasoning",
                      "request_seconds": round(time.monotonic() - started, 4)}


def extract_code(text):
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return blocks[0] if blocks else text


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="http://127.0.0.1:8888")
    p.add_argument("--api-key-file", required=True)
    p.add_argument("--out", type=Path)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--sandbox-image", default=DEFAULT_IMAGE)
    args = p.parse_args(argv)
    if not 1 <= args.repeats <= 100:
        p.error("--repeats must be1..100")
    return args


def run_exam(client, image, repeats):
    detail = {}; attempts = []; passed = 0
    for name, prompt, test in P:
        wins = 0; last_error = ""
        for repeat in range(repeats):
            record = {"task": name, "repeat": repeat + 1, "usage": None}
            try:
                content, response = client.ask(prompt)
                record.update(response)
                ok, error, execution = execute_candidate(extract_code(content), test, image)
                record["execution"] = execution
            except Exception as exc:
                ok = False
                error = "request error: " + type(exc).__name__
                if isinstance(exc, urllib.error.HTTPError):
                    error += " HTTP" + str(exc.code)
            record.update(passed=ok, error=error)
            attempts.append(record)
            if ok:
                wins += 1
            else:
                last_error = error
        passed += wins; detail[name] = wins
        verdict = "PASS" if wins == repeats else ("PARTIAL" if wins else "FAIL")
        suffix = "" if wins == repeats else " (" + last_error + ")"
        print(f"  {verdict:5s} {name:14s} {wins}/{repeats}{suffix}", flush=True)
    total = len(P) * repeats
    # Preserve server-reported usage per attempt, including nested detail. Only
    # sum present numeric counters; missing usage is never imputed as zero.
    usage_totals = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        values = [a["usage"].get(key) for a in attempts if isinstance(a["usage"], dict)]
        numeric = [v for v in values if isinstance(v, int) and not isinstance(v, bool)]
        usage_totals[key] = {"sum_reported": sum(numeric) if numeric else None,
                             "attempts_reporting": len(numeric)}
    return {"schema": "glm.private-code-exam.v1", "passed": passed, "total": total,
            "detail": detail, "attempts": attempts, "usage_totals": usage_totals,
            "sandbox_image_id": image, "sandbox_timeout_seconds": TIMEOUT_SECONDS,
            "qualification": "12-task functional gate; not a model-level accuracy estimate"}


def main(argv=None):
    args = parse_args(argv)
    if args.out and args.out.exists():
        raise ValueError("Refusing to replace an existing result file")
    image = checked_image(args.sandbox_image)
    client = ModelClient(args.base, args.api_key_file)
    result = run_exam(client, image, args.repeats)
    print(f"\n  CODE EXAM: {result['passed']}/{result['total']} ({100 * result['passed'] / result['total']:.1f}%)")
    print("  USAGE (server reported): " + json.dumps(result["usage_totals"]))
    if args.out:
        with args.out.open("x") as output:
            os.chmod(args.out, 0o600)
            json.dump(result, output, indent=2); output.write("\n")
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        # No exception payloads or request headers: key contents stay private.
        print("CODE EXAM setup failed: " + type(exc).__name__, flush=True)
        raise SystemExit(2)
