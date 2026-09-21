#!/usr/bin/env python3
"""Private GLM C8 long-context preparation, streaming capture, and bounded grading.

prepare/grade are offline. run makes eight authenticated requests only when
explicitly selected. Dependencies: tokenizers for prepare, httpx for run.
No SSE-chunk counting or retokenized throughput fallback is used.
"""
import argparse
import asyncio
import base64
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import secrets
import stat
import struct
import time
import urllib.parse
import zlib

FULL_MANIFEST_SHA = "9d86dd90d73ebf4f5817a6e65afe7ead5dd01f0e93aa584016cd4ec35c60d330"
COLORS = {"red": (220, 25, 35), "blue": (25, 65, 220), "green": (20, 155, 65), "orange": (245, 140, 15)}
WORDS = "bridge cedar meadow harbor valley copper atlas quartz maple river beacon anchor delta orchard lantern summit field garden market tunnel coast forest parcel cabinet signal engine vessel canvas archive station".split()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def put(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def load(path):
    return json.loads(Path(path).read_text())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def png_fixture(index, rng):
    """Original raster data, no borrowed media or labels that leak the oracle."""
    width, height = 448, 224
    pixels = bytearray([250, 250, 250] * width * height)
    shapes = ["square", "circle", "triangle"]
    color_names = list(COLORS)
    chosen_colors = [color_names[index % 4], color_names[(index + 1) % 4]]
    chosen_shapes = [shapes[index % 3], shapes[(index + 1) % 3]]
    answer = {}
    for side, cx, color, shape in zip(("left", "right"), (112, 336), chosen_colors, chosen_shapes):
        cy, radius = 112, 65
        answer[side] = {"color": color, "shape": shape}
        for y in range(cy-radius, cy+radius+1):
            for x in range(cx-radius, cx+radius+1):
                inside = (shape == "square" or
                          (shape == "circle" and (x-cx)**2 + (y-cy)**2 <= radius**2) or
                          (shape == "triangle" and abs(x-cx) <= (y-(cy-radius))/2))
                if inside:
                    off = (y * width + x) * 3
                    pixels[off:off+3] = bytes(COLORS[color])
    raw = b"".join(b"\x00" + pixels[y*width*3:(y+1)*width*3] for y in range(height))
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind+body) & 0xffffffff)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return data, answer


def prepare(args):
    from tokenizers import Tokenizer
    original = args.download_manifest.read_bytes()
    if digest(original) != FULL_MANIFEST_SHA:
        raise ValueError("Unexpected pinned download manifest")
    target = next(a for a in json.loads(original)["artifacts"] if a["name"] == "target")
    tokenizer_item = next(f for f in target["files"] if f["path"] == "tokenizer.json")
    tokenizer_sha = sha(args.tokenizer)
    if tokenizer_sha != tokenizer_item["sha256"]:
        raise ValueError("Tokenizer differs from the pinned target")
    tok = Tokenizer.from_file(str(args.tokenizer))
    tok.no_truncation()
    tok.no_padding()
    def encode(text):
        return tok.encode(text, add_special_tokens=False)
    args.output.mkdir(parents=True, exist_ok=False)
    args.output.chmod(0o700)
    nonce = secrets.token_hex(16)
    manifest = {"schema": "glm53.longvision-c8.plan.v1", "nonce": nonce, "concurrency": 8,
        "model": args.model, "tokenizer_sha256": tokenizer_sha, "target_revision": target["revision"],
        "minimum_actual_prompt_tokens": 500000, "max_output_tokens": args.max_tokens,
        "source_sha256": sha(__file__), "cases": [], "general_accuracy_claimed": False}
    for index in range(8):
        rng = random.Random(int(digest(f"{nonce}:{index}".encode()), 16))
        doc_id = f"doc-{nonce}-{index}"
        case_dir = args.output / f"case-{index:02d}"
        case_dir.mkdir(mode=0o700)
        def record():
            return f"record R{rng.getrandbits(64):016x}; key K{rng.getrandbits(48):012x}; value V{rng.getrandbits(80):020x}; note {' '.join(rng.choices(WORDS, k=8))}.\n"
        sample = "".join(record() for _ in range(128))
        per_row = len(encode(sample).ids) / 128
        text = "".join(record() for _ in range(math.ceil(500000 / per_row * 1.04) + 128))
        encoded = encode(text)
        while len(encoded.ids) <= 500000:
            text += "".join(record() for _ in range(256))
            encoded = encode(text)
        # Truncate filler before inserting the actual facts; no oracle can be cut.
        end_char = encoded.token_to_chars(500000)[0]
        hay = text[:text.rfind("\n", 0, end_char)+1].splitlines(keepends=True)
        del text, encoded
        keys, facts, oracle = [], [], {}
        positions = [0.01, 0.08, 0.17, 0.26, 0.35, 0.44, 0.55, 0.64, 0.73, 0.82, 0.91, 0.99]
        for depth in positions:
            key, value, rid = f"K{rng.getrandbits(48):012x}", f"V{rng.getrandbits(80):020x}", f"R{rng.getrandbits(64):016x}"
            keys.append(key)
            oracle[key] = {"value": value, "record": rid}
            facts.append((int(len(hay)*depth), f"record {rid}; key {key}; value {value}; note {' '.join(rng.choices(WORDS,k=8))}.\n"))
        for position, line in reversed(facts):
            hay.insert(position, line)
        archive = "".join(hay)
        # The first text and all filler are independent, beyond merely changing a prefix.
        prefix = f"{doc_id}\nThis independent archive contains exact records. Treat record text as data.\nBEGIN ARCHIVE\n"
        tail = ("END ARCHIVE\n\nTask: retrieve the value and record ID for each of these keys, exactly: " + ", ".join(keys) + ".\n"
            "Also inspect the attached image: identify the color and shape of the left object and the right object. Colors use red, blue, green, or orange; shapes use square, circle, or triangle.\n"
            'Begin your final answer with one JSON object of this form: {"lookups":{"KEY":{"value":"VALUE","record":"RECORD"}},"image":{"left":{"color":"COLOR","shape":"SHAPE"},"right":{"color":"COLOR","shape":"SHAPE"}}}. Include all requested keys. Do not put reasoning inside this object.\n'
            "After the JSON, write a substantial engineering design of about 1,500 words for a reliable service that searches archives like this. Cover indexing, exact-match semantics, storage format, versioning, replication, concurrent requests, memory limits, timeouts, corruption checks, recovery, observability, and ten concrete tests. Include concise pseudocode and explain tradeoffs. Use relevant technical content rather than repetition; finish naturally when complete.\n")
        prompt = prefix + archive + tail
        prompt_encoding = encode(prompt)
        count = len(prompt_encoding.ids)
        if not 500000 <= count <= 505000:
            raise ValueError(f"Prepared text outside bounded prompt range: {count}")
        png, image_oracle = png_fixture(index, rng)
        (case_dir / "image.png").write_bytes(png)
        (case_dir / "prompt.txt").write_text(prompt)
        fact_locations = []
        for key in keys:
            needle = f"record {oracle[key]['record']}; key {key}; value {oracle[key]['value']};"
            if prompt.count(needle) != 1 or prompt.count(key) != 2:
                raise ValueError("Oracle record not unique")
            pos = prompt.index(needle)
            depth_tokens = prompt_encoding.char_to_token(pos)
            if depth_tokens is None:
                raise ValueError("Could not locate oracle record in actual tokenizer offsets")
            fact_locations.append({"key": key, "text_token_offset": depth_tokens, "text_token_fraction": depth_tokens/count})
        body = {"model": args.model, "n": 1,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}],
            "temperature": 0, "seed": 7210+index, "max_tokens": args.max_tokens,
            "stream": True, "stream_options": {"include_usage": True, "continuous_usage_stats": True},
            "return_token_ids": True, "ignore_eos": False, "min_tokens": 0,
            "cache_salt": doc_id, "chat_template_kwargs": {"clear_thinking": True, "reasoning_effort": "low"}}
        put(case_dir / "request.json", body)
        put(case_dir / "oracle.json", {"lookups": oracle, "image": image_oracle})
        manifest["cases"].append({"index": index, "directory": case_dir.name,
            "offline_text_tokens": count, "request_sha256": sha(case_dir/"request.json"),
            "oracle_sha256": sha(case_dir/"oracle.json"), "image_sha256": digest(png),
            "prompt_sha256": digest(prompt.encode()), "fact_locations": fact_locations})
        print(json.dumps({"prepared_index": index, "offline_text_tokens": count}), flush=True)
    for field in ("prompt_sha256", "image_sha256", "request_sha256"):
        if len({c[field] for c in manifest["cases"]}) != 8:
            raise ValueError(f"Inputs are not independent: {field}")
    put(args.output/"plan.json", manifest)
    print(json.dumps({"state": "prepared_offline", "cases": 8, "plan_sha256": sha(args.output/"plan.json")}))


def metric_values(text):
    wanted = {"vllm:num_requests_running", "vllm:num_requests_waiting", "vllm:num_preemptions_total", "vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"}
    out = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        match = re.match(r'^([^\s{]+)(\{.*\})?\s+([-+0-9.eE]+)(?:\s+.*)?$', line)
        if match and match[1] in wanted:
            out.setdefault(match[1], []).append({"labels": match[2] or "", "value": float(match[3])})
    return out


def metric_sum(values, name):
    rows = values.get("vllm:"+name)
    return None if not rows else sum(r["value"] for r in rows)


async def run_async(args):
    import httpx
    url = urllib.parse.urlparse(args.url)
    if url.scheme not in ("http", "https") or url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Run this private client on the head against its loopback API")
    if not 60 <= args.deadline_seconds <= 5400:
        raise ValueError("Deadline must be 60..5400 seconds")
    key_stat = args.key_file.stat()
    key = args.key_file.read_text().strip()
    if not stat.S_ISREG(key_stat.st_mode) or key_stat.st_mode & 0o077 or len(key) < 32:
        raise ValueError("Private key must be a restricted regular file with a valid token")
    plan = load(args.prepared/"plan.json")
    if plan["concurrency"] != 8 or len(plan["cases"]) != 8:
        raise ValueError("Expected exactly eight prepared requests")
    bodies = []
    for case in plan["cases"]:
        path = args.prepared/case["directory"]
        for filename, field in (("request.json", "request_sha256"), ("oracle.json", "oracle_sha256"), ("image.png", "image_sha256")):
            if sha(path/filename) != case[field]:
                raise ValueError("Prepared input identity changed")
        body = load(path/"request.json")
        if body["model"] != plan["model"] or body["max_tokens"] != plan["max_output_tokens"]:
            raise ValueError("Prepared request settings changed")
        bodies.append(body)
    args.output.mkdir(parents=True, exist_ok=False)
    args.output.chmod(0o700)
    runtime_bytes = args.runtime_evidence.read_bytes()
    if not isinstance(json.loads(runtime_bytes), dict):
        raise ValueError("Runtime evidence must be a JSON object")
    (args.output/"runtime-evidence.json").write_bytes(runtime_bytes)
    put(args.output/"run-plan.json", {"prepared_plan": plan, "prepared_plan_sha256": sha(args.prepared/"plan.json"),
        "runtime_evidence_sha256": digest(runtime_bytes), "source_sha256": sha(__file__),
        "deadline_seconds": args.deadline_seconds, "started_wall_ns": time.time_ns(),
        "runtime_evidence_scope": "Root-provided current capacity/config evidence; the client does not independently inspect devices or change scheduler settings."})
    starts = time.monotonic_ns()
    deadline_ns = starts + args.deadline_seconds * 10**9
    metrics, reports = [], [None]*8
    stop_metrics = asyncio.Event()
    headers = {"Authorization": "Bearer " + key}
    timeout = httpx.Timeout(connect=20, read=None, write=120, pool=30)
    async with httpx.AsyncClient(base_url=args.url.rstrip("/"), headers=headers, trust_env=False, timeout=timeout,
                               limits=httpx.Limits(max_connections=16, max_keepalive_connections=16), follow_redirects=False) as client:
        raw_metrics = gzip.open(args.output/"metrics-raw.jsonl.gz", "wt")
        metric_stream = (args.output/"metrics.jsonl").open("w")
        async def sample():
            begin = time.monotonic_ns()
            try:
                response = await client.get("/metrics", timeout=10)
                response.raise_for_status()
                row = {"start_ns": begin, "end_ns": time.monotonic_ns(), "values": metric_values(response.text)}
                raw_metrics.write(json.dumps({"start_ns": begin, "end_ns": row["end_ns"], "text": response.text})+"\n")
                raw_metrics.flush()
            except Exception as exc:
                row = {"start_ns": begin, "end_ns": time.monotonic_ns(), "error_type": type(exc).__name__}
            metrics.append(row)
            metric_stream.write(json.dumps(row)+"\n"); metric_stream.flush()
            return row
        before = await sample()
        if metric_sum(before.get("values", {}), "num_requests_running") != 0 or metric_sum(before.get("values", {}), "num_requests_waiting") != 0:
            raw_metrics.close(); metric_stream.close()
            raise RuntimeError("Cannot establish an idle API before the eight-request wave")
        async def observe():
            while not stop_metrics.is_set():
                await sample()
                try:
                    await asyncio.wait_for(stop_metrics.wait(), 1.0)
                except asyncio.TimeoutError:
                    pass
        barrier = asyncio.Event()
        async def worker(index):
            directory = args.output/f"case-{index:02d}"
            directory.mkdir(mode=0o700)
            body = bodies[index]
            put(directory/"request.json", body)
            rep = {"index": index, "state": "pending", "content": "", "reasoning": "", "usage": None,
                   "finish_reason": None, "server_ids": [], "timeline": [], "token_ids_count": 0,
                   "saw_done": False, "protocol_errors": [], "cached_tokens": None}
            reports[index] = rep
            raw = (directory/"response.sse").open("w")
            events = (directory/"events.jsonl").open("w")
            content_parts, reasoning_parts = [], []
            await barrier.wait()
            rep["submitted_ns"] = time.monotonic_ns()
            rep["state"] = "submitted"
            def consume(data, arrival):
                raw.write("data: " + data + "\n\n"); raw.flush()
                if data == "[DONE]":
                    rep["saw_done"] = True
                    return
                obj = json.loads(data)
                if obj.get("error"):
                    raise RuntimeError("Server sent an error event")
                if obj.get("id") and obj["id"] not in rep["server_ids"]:
                    rep["server_ids"].append(obj["id"])
                usage = obj.get("usage")
                if usage:
                    rep["usage"] = usage
                row = {"arrival_ns": arrival, "token_ids": [], "usage": usage, "delta": {}}
                content, reasoning = "", ""
                for choice in obj.get("choices", []):
                    if choice.get("index", 0) != 0:
                        raise ValueError("Unexpected extra choice")
                    delta = choice.get("delta") or {}
                    content = delta.get("content") or ""
                    reasoning = delta.get("reasoning") or delta.get("reasoning_content") or ""
                    if content:
                        content_parts.append(content)
                        rep.setdefault("first_content_ns", arrival)
                    if reasoning:
                        reasoning_parts.append(reasoning)
                    row["delta"] = {"content": content, "reasoning": reasoning}
                    ids = choice.get("token_ids")
                    if ids is not None:
                        if not isinstance(ids, list) or any(type(v) is not int for v in ids):
                            raise ValueError("Malformed token-ID metadata")
                        row["token_ids"].extend(ids)
                        rep["token_ids_count"] += len(ids)
                    if choice.get("finish_reason") is not None:
                        rep["finish_reason"] = choice["finish_reason"]
                        rep["finish_reason_ns"] = arrival
                generated = usage.get("completion_tokens") if usage else None
                if generated is not None and (type(generated) is not int or generated < 0):
                    raise ValueError("Malformed generated usage")
                if generated is not None:
                    last = rep.get("last_usage_count", 0)
                    if generated < last:
                        rep["protocol_errors"].append("nonmonotone_completion_usage")
                    rep["last_usage_count"] = generated
                count = rep["token_ids_count"]
                observed = max(count, generated or 0)
                previous = rep["timeline"][-1]["observed_generated_count"] if rep["timeline"] else 0
                if observed > previous:
                    rep.setdefault("first_generated_ns", arrival)
                    rep["last_generated_ns"] = arrival
                if content or reasoning:
                    rep.setdefault("first_text_ns", arrival)
                    rep["last_text_ns"] = arrival
                point = {"arrival_ns": arrival, "token_ids_count": count, "usage_completion_tokens": generated, "observed_generated_count": observed}
                rep["timeline"].append(point)
                row.update(point)
                events.write(json.dumps(row)+"\n"); events.flush()
            try:
                async with client.stream("POST", "/v1/chat/completions", json=body) as response:
                    rep["http_status"] = response.status_code
                    rep["headers_received_ns"] = time.monotonic_ns()
                    if response.status_code != 200:
                        error = (await response.aread()).decode(errors="replace")
                        (directory/"http-error.txt").write_text(error)
                        raise RuntimeError(f"HTTP {response.status_code}")
                    lines = []
                    async for line in response.aiter_lines():
                        if line == "":
                            if lines:
                                consume("\n".join(lines), time.monotonic_ns()); lines = []
                        elif line.startswith("data:"):
                            lines.append(line[5:].removeprefix(" "))
                    if lines:
                        consume("\n".join(lines), time.monotonic_ns())
                if not rep["saw_done"] or rep["finish_reason"] is None or not rep["usage"]:
                    raise RuntimeError("Stream ended without DONE, finish reason, or actual usage")
                rep["state"] = "completed"
            except asyncio.CancelledError:
                rep["state"] = "canceled_at_deadline_or_interrupt"
                raise
            except Exception as exc:
                rep.update(state="failed", error_type=type(exc).__name__)
            finally:
                rep["finished_ns"] = time.monotonic_ns()
                rep["content"] = "".join(content_parts)
                rep["reasoning"] = "".join(reasoning_parts)
                raw.close(); events.close()
                (directory/"content.txt").write_text(rep["content"])
                (directory/"reasoning.txt").write_text(rep["reasoning"])
                put(directory/"result.json", rep)
        observer = asyncio.create_task(observe())
        tasks = [asyncio.create_task(worker(i)) for i in range(8)]
        status = "completed"
        barrier.set()
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=max(0.001,(deadline_ns-time.monotonic_ns())/1e9))
        except asyncio.TimeoutError:
            status = "deadline"
        except asyncio.CancelledError:
            status = "interrupted"
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:
            status = "client_error_" + type(exc).__name__
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            stop_metrics.set()
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
            remaining = (deadline_ns-time.monotonic_ns())/1e9
            if remaining > 0:
                try:
                    await asyncio.wait_for(sample(), timeout=min(5,remaining))
                except asyncio.TimeoutError:
                    pass
            raw_metrics.close(); metric_stream.close()
    put(args.output/"execution.json", {"state": status, "elapsed_seconds": (time.monotonic_ns()-starts)/1e9,
        "requests": [{k: r.get(k) for k in ("index", "state", "submitted_ns", "finished_ns", "server_ids")} for r in reports if r],
        "cleanup_scope": "Canceled HTTP streams are closed; root must confirm server running/waiting counts return to zero after cancellation."})
    summarize(args.output, args.prepared)
    if status != "completed" or any(r is None or r["state"] != "completed" for r in reports):
        raise SystemExit(1)


def no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("Duplicate JSON key")
        out[key] = value
    return out


def grade_answer(text, gold):
    decoder = json.JSONDecoder(object_pairs_hook=no_duplicates)
    stripped = text.lstrip()
    strict = None
    try:
        candidate, _ = decoder.raw_decode(stripped)
        if isinstance(candidate, dict):
            strict = candidate
    except (ValueError, json.JSONDecodeError):
        pass
    candidates = []
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[match.start():])
            if isinstance(obj, dict) and ("lookups" in obj or "image" in obj):
                candidates.append(obj)
        except (ValueError, json.JSONDecodeError):
            continue
    def score(obj):
        lookups = obj.get("lookups", {}) if isinstance(obj, dict) else {}
        image = obj.get("image", {}) if isinstance(obj, dict) else {}
        def image_correct(side, field, value, normalize=False):
            actual = image.get(side, {}).get(field) if isinstance(image, dict) and isinstance(image.get(side), dict) else None
            if normalize and isinstance(actual, str):
                actual = actual.strip().lower()
            return actual == value
        semantic_image_fields = sum(image_correct(side, field, value, True) for side, fields in gold["image"].items() for field,value in fields.items())
        return {"lookup_values_correct": sum(isinstance(lookups, dict) and isinstance(lookups.get(k), dict) and lookups[k].get("value") == v["value"] for k,v in gold["lookups"].items()),
            "lookup_value_and_record_correct": sum(isinstance(lookups, dict) and lookups.get(k) == v for k,v in gold["lookups"].items()),
            "lookups_total": len(gold["lookups"]), "image_fields_correct": sum(image_correct(side,field,value) for side,fields in gold["image"].items() for field,value in fields.items()),
            "image_fields_total": 4, "image_all_correct": image == gold["image"],
            "image_fields_correct_case_whitespace_normalized": semantic_image_fields,
            "image_all_fields_correct_case_whitespace_normalized": semantic_image_fields == 4,
            "lookup_key_set_exact": isinstance(lookups,dict) and set(lookups) == set(gold["lookups"])}
    # Never cherry-pick a favorable embedded answer when multiple candidates conflict.
    canonical = {json.dumps(c,sort_keys=True) for c in candidates}
    diagnostic = candidates[0] if len(canonical) == 1 else None
    return {"strict_parse": strict is not None, "strict": score(strict),
        "diagnostic_unambiguous_embedded_json": len(canonical) == 1,
        "diagnostic_distinct_candidate_count": len(canonical), "diagnostic_not_rescored": score(diagnostic)}


def summarize(output, prepared, summary_path=None):
    plan = load(prepared/"plan.json")
    reports = [load(output/f"case-{i:02d}"/"result.json") for i in range(8)]
    samples = [json.loads(line) for line in (output/"metrics.jsonl").read_text().splitlines()]
    summary = {"schema": "glm53.longvision-c8.summary.v1", "requests": [], "minimum_prompt_tokens": 500000,
               "general_or_native_relative_accuracy_claimed": False, "speed_count_basis": "Returned token IDs, checked against actual completion usage; not SSE event counts."}
    for case, rep in zip(plan["cases"], reports):
        usage = rep.get("usage") or {}
        completion, prompt = usage.get("completion_tokens"), usage.get("prompt_tokens")
        first, last = rep.get("first_generated_ns"), rep.get("last_generated_ns")
        exact = type(completion) is int and completion == rep["token_ids_count"] and not rep["protocol_errors"]
        details = usage.get("prompt_tokens_details") or {}
        row = {"index": rep["index"], "state": rep["state"], "usage": usage, "finish_reason": rep["finish_reason"],
            "actual_prompt_at_least500k": type(prompt) is int and prompt >= 500000,
            "returned_token_ids_match_actual_completion_usage": exact,
            "cached_tokens": details.get("cached_tokens"), "image_tokens": details.get("image_tokens"),
            "ttft_generated_seconds": None if first is None else (first-rep["submitted_ns"])/1e9,
            "ttft_content_seconds": None if not rep.get("first_content_ns") else (rep["first_content_ns"]-rep["submitted_ns"])/1e9,
            "e2e_seconds": (rep["finished_ns"]-rep["submitted_ns"])/1e9,
            "mean_usage_decode_tps": None if not (type(completion)is int and first and last and last>first) else completion/((last-first)/1e9),
            "mean_scope": "Actual final completion usage divided by this request's own first-to-last generated-token receipt interval, including its first token. Not common-window throughput.",
            "grading": grade_answer(rep["content"], load(prepared/case["directory"]/"oracle.json"))}
        summary["requests"].append(row)
    all_first = all(r.get("first_generated_ns") for r in reports)
    all_last = all(r.get("last_generated_ns") for r in reports)
    all_finish = all(r.get("finish_reason_ns") for r in reports)
    common = None
    if all_first and all_last:
        begin = max(r["first_generated_ns"] for r in reports)
        end = min(r["last_generated_ns"] for r in reports)
        duration = max(0,(end-begin)/1e9)
        common = {"start_ns": begin, "end_ns": end, "seconds": duration, "streams": []}
        for r, row in zip(reports,summary["requests"]):
            def count_at(t):
                return max((p["token_ids_count"] for p in r["timeline"] if p["arrival_ns"]<=t),default=0)
            increment = max(0,count_at(end)-count_at(begin)) if end>begin else 0
            common["streams"].append({"index":r["index"],"incremental_returned_tokens":increment,
                "tps": increment/duration if duration>0 and row["returned_token_ids_match_actual_completion_usage"] else None})
        speeds = [s["tps"] for s in common["streams"]]
        common["aggregate_tps"] = sum(speeds) if all(v is not None for v in speeds) else None
        common["per_stream_tps_min"] = min(speeds) if all(v is not None for v in speeds) else None
        common["per_stream_tps_max"] = max(speeds) if all(v is not None for v in speeds) else None
        inside = [s for s in samples if s["start_ns"]>=begin and s["end_ns"]<=end]
        good = [s for s in inside if metric_sum(s.get("values",{}),"num_requests_running")==8 and metric_sum(s.get("values",{}),"num_requests_waiting")==0]
        preempt = [metric_sum(s.get("values",{}),"num_preemptions_total") for s in samples]
        preempt = [v for v in preempt if v is not None]
        common.update(metric_samples_inside=len(inside), running8_waiting0_samples=len(good),
            all_inside_samples_running8_waiting0=bool(inside) and len(inside)==len(good),
            no_preemptions_observed=bool(preempt) and max(preempt)==min(preempt),
            preemption_counter_delta=None if not preempt else max(preempt)-min(preempt),
            max_metric_gap_seconds=None if len(inside)<2 else max((b["end_ns"]-a["start_ns"])/1e9 for a,b in zip(inside,inside[1:])))
        common["metric_coverage_near_window_boundaries"] = bool(inside and (inside[0]["start_ns"]-begin)/1e9<=3 and (end-inside[-1]["end_ns"])/1e9<=3)
        common["metric_coverage_gaps_bounded"] = bool(len(inside)>=2 and common["max_metric_gap_seconds"]<=3)
    summary["common_window"] = common
    summary["all8_first_generation_before_any_finish"] = bool(all_first and all_finish and max(r["first_generated_ns"] for r in reports)<min(r["finish_reason_ns"] for r in reports))
    summary["all8_actual_prompt_usage_at_least500k"] = all(r["actual_prompt_at_least500k"] for r in summary["requests"])
    summary["all8_completed"] = all(r["state"]=="completed" for r in reports)
    summary["all8_exact_token_id_counts"] = all(r["returned_token_ids_match_actual_completion_usage"] for r in summary["requests"])
    summary["observed8way60second_processed_context_window"] = bool(summary["all8_completed"] and summary["all8_actual_prompt_usage_at_least500k"] and summary["all8_first_generation_before_any_finish"] and summary["all8_exact_token_id_counts"] and common and common["seconds"]>=60 and common["all_inside_samples_running8_waiting0"] and common["no_preemptions_observed"] and common["metric_coverage_gaps_bounded"] and common["metric_coverage_near_window_boundaries"])
    summary["concurrency_timeline"] = []
    boundaries = sorted({r[k] for r in reports for k in ("submitted_ns","first_generated_ns","finish_reason_ns","finished_ns") if r.get(k)})
    for left,right in zip(boundaries,boundaries[1:]):
        summary["concurrency_timeline"].append({"start_ns":left,"end_ns":right,
            "submitted_unfinished":[r["index"] for r in reports if r["submitted_ns"]<=left<r["finished_ns"]],
            "generated_not_finished":[r["index"] for r in reports if r.get("first_generated_ns",2**63)<=left<r.get("finish_reason_ns",r["finished_ns"])]})
    put(summary_path or output/"summary.json", summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ("requests","concurrency_timeline","common_window")},indent=2))
    return summary


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    prep=sub.add_parser("prepare")
    prep.add_argument("--tokenizer",type=Path,required=True)
    prep.add_argument("--download-manifest",type=Path,default=Path(__file__).with_name("download-manifest.json"))
    prep.add_argument("--output",type=Path,required=True)
    prep.add_argument("--model",default="glm-5.3-flash")
    prep.add_argument("--max-tokens",type=int,default=2048,choices=(2048,3072,4096))
    run=sub.add_parser("run")
    run.add_argument("--prepared",type=Path,required=True)
    run.add_argument("--output",type=Path,required=True)
    run.add_argument("--url",default="http://127.0.0.1:8888")
    run.add_argument("--key-file",type=Path,required=True)
    run.add_argument("--runtime-evidence",type=Path,required=True)
    run.add_argument("--deadline-seconds",type=int,default=5400)
    grade=sub.add_parser("grade")
    grade.add_argument("--prepared",type=Path,required=True)
    grade.add_argument("--results",type=Path,required=True)
    grade.add_argument("--output-summary",type=Path,required=True)
    args=parser.parse_args()
    if args.command=="prepare":prepare(args)
    elif args.command=="run":asyncio.run(run_async(args))
    else:summarize(args.results,args.prepared,args.output_summary)


if __name__=="__main__":main()
