#!/usr/bin/env python3
"""Bounded offline checks. Fake HTTP is in-process; no socket/API/GPU calls."""
import argparse
import asyncio
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import random
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock
import zlib

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("longvision_c8", HERE / "longvision-c8.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
GOLD = {"lookups": {"Kone": {"value": "V123", "record": "R321"}},
        "image": {"left": {"color": "red", "shape": "square"}, "right": {"color": "blue", "shape": "circle"}}}


class QualificationTests(unittest.TestCase):
    def test_original_pngs(self):
        hashes = set()
        for index in range(8):
            png, oracle = client.png_fixture(index, random.Random(index))
            hashes.add(client.digest(png))
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            offset, compressed = 8, b""
            while offset < len(png):
                size = struct.unpack(">I", png[offset:offset+4])[0]
                kind, data = png[offset+4:offset+8], png[offset+8:offset+8+size]
                self.assertEqual(struct.unpack(">I", png[offset+8+size:offset+12+size])[0], zlib.crc32(kind+data) & 0xffffffff)
                if kind == b"IHDR":
                    self.assertEqual(struct.unpack(">II", data[:8]), (448, 224))
                if kind == b"IDAT":
                    compressed += data
                offset += 12+size
            self.assertEqual(len(zlib.decompress(compressed)), 224*(1+448*3))
            self.assertNotEqual(oracle["left"], oracle["right"])
        self.assertEqual(len(hashes), 8)

    def test_grading_separates_format_and_content(self):
        exact = client.grade_answer(json.dumps(GOLD)+"\nEngineering design follows.", GOLD)
        self.assertTrue(exact["strict_parse"])
        self.assertEqual(exact["strict"]["lookup_value_and_record_correct"], 1)
        self.assertTrue(exact["strict"]["image_all_correct"])
        wrapped = client.grade_answer("Here is the answer:\n```json\n"+json.dumps(GOLD)+"\n```", GOLD)
        self.assertFalse(wrapped["strict_parse"])
        self.assertTrue(wrapped["diagnostic_unambiguous_embedded_json"])
        self.assertEqual(wrapped["diagnostic_not_rescored"]["lookup_values_correct"], 1)
        changed = copy.deepcopy(GOLD)
        changed["lookups"]["Kone"]["value"] = "wrong"
        conflict = client.grade_answer("Answers: "+json.dumps(GOLD)+json.dumps(changed), GOLD)
        self.assertEqual(conflict["diagnostic_distinct_candidate_count"], 2)
        self.assertEqual(conflict["diagnostic_not_rescored"]["lookup_values_correct"], 0)
        duplicate = client.grade_answer('{"lookups":{},"lookups":'+json.dumps(GOLD["lookups"])+',"image":{}}', GOLD)
        self.assertFalse(duplicate["strict_parse"])
        capital = copy.deepcopy(GOLD)
        capital["image"]["left"]["color"] = " RED "
        scored = client.grade_answer(json.dumps(capital), GOLD)["strict"]
        self.assertFalse(scored["image_all_correct"])
        self.assertTrue(scored["image_all_fields_correct_case_whitespace_normalized"])

    def fixture(self, root):
        prepared, results = root/"prepared", root/"results"
        prepared.mkdir(); results.mkdir()
        plan = {"cases": []}
        reports = []
        for i in range(8):
            directory = f"case-{i:02d}"
            (prepared/directory).mkdir(); (results/directory).mkdir()
            client.put(prepared/directory/"oracle.json", GOLD)
            plan["cases"].append({"directory": directory})
            timeline = [{"arrival_ns": (100+i+j)*10**9, "token_ids_count": (j+1)*20} for j in range(101)]
            report = {"index": i, "state": "completed", "usage": {"prompt_tokens": 500123, "completion_tokens": 2020},
                "token_ids_count": 2020, "protocol_errors": [], "finish_reason": "length", "content": json.dumps(GOLD),
                "submitted_ns": 10**9, "first_generated_ns": (100+i)*10**9,
                "last_generated_ns": (200+i)*10**9, "finish_reason_ns": (201+i)*10**9,
                "finished_ns": (202+i)*10**9, "timeline": timeline}
            client.put(results/directory/"result.json", report)
            reports.append(report)
        client.put(prepared/"plan.json", plan)
        metrics = [{"start_ns": second*10**9, "end_ns": second*10**9+10**8,
            "values": client.metric_values('vllm:num_requests_running{model_name="test"} 8\nvllm:num_requests_waiting 0\nvllm:num_preemptions_total 0')} for second in range(98,211)]
        self.write_metrics(results, metrics)
        return prepared, results, reports, metrics

    @staticmethod
    def write_metrics(results, metrics):
        (results/"metrics.jsonl").write_text("".join(json.dumps(m)+"\n" for m in metrics))

    def test_accounting_and_false_pass_guards(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            prepared, results, reports, metrics = self.fixture(Path(tmp))
            def summarize(name):
                return client.summarize(results, prepared, results/name)
            good = summarize("good.json")
            self.assertTrue(good["observed8way60second_processed_context_window"])
            self.assertEqual(good["common_window"]["seconds"], 93)
            self.assertEqual(good["common_window"]["aggregate_tps"], 160)
            self.assertEqual(good["common_window"]["per_stream_tps_min"], 20)
            self.assertEqual(good["requests"][0]["mean_usage_decode_tps"], 20.2)
            self.assertTrue(any(len(row["generated_not_finished"]) == 8 for row in good["concurrency_timeline"]))
            for field, value, name in [("usage", {"prompt_tokens": 499999, "completion_tokens": 2020}, "shortprompt"),
                                       ("token_ids_count", 2019, "id_mismatch"),
                                       ("finish_reason_ns", 106*10**9, "early_finish"),
                                       ("last_generated_ns", 150*10**9, "short_overlap"),
                                       ("state", "failed", "failed"),
                                       ("usage", {}, "missing_usage")]:
                changed = copy.deepcopy(reports[0]); changed[field] = value
                path = results/"case-00/result.json"
                path.write_text(json.dumps(changed))
                self.assertFalse(summarize(name+".json")["observed8way60second_processed_context_window"])
                path.write_text(json.dumps(reports[0]))
            preempted = copy.deepcopy(metrics)
            preempted[-1]["values"]["vllm:num_preemptions_total"][0]["value"] = 1
            self.write_metrics(results, preempted)
            self.assertFalse(summarize("preempted.json")["observed8way60second_processed_context_window"])
            self.write_metrics(results, [m for m in metrics if not 150 <= m["start_ns"]/1e9 <= 156])
            self.assertFalse(summarize("metricgap.json")["observed8way60second_processed_context_window"])

    def test_fake_sse_final_usage_and_token_ids(self):
        class Response:
            status_code = 200
            text = "vllm:num_requests_running 0\nvllm:num_requests_waiting 0\nvllm:num_preemptions_total 0\n"
            def raise_for_status(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def aiter_lines(self):
                events = [
                    {"id": "fake", "prompt_token_ids": [7]*20, "choices": [{"index": 0, "delta": {"role": "assistant"}, "token_ids": []}], "usage": {"prompt_tokens": 500123,"completion_tokens": 0}},
                    {"id": "fake", "choices": [{"index": 0, "delta": {"reasoning": "A brief check."}, "token_ids": [42]}], "usage": {"prompt_tokens": 500123,"completion_tokens": 1}},
                    {"id": "fake", "choices": [{"index": 0, "delta": {"content": json.dumps(GOLD)}, "token_ids": [43], "finish_reason": "stop"}], "usage": {"prompt_tokens": 500123,"completion_tokens": 2}},
                    {"id": "fake", "choices": [], "usage": {"prompt_tokens": 500123,"completion_tokens": 2}}]
                for event in events:
                    await asyncio.sleep(0)
                    yield "data: " + json.dumps(event)
                    yield ""
                yield "data: [DONE]"
                yield ""
        class FakeClient:
            def __init__(self, **kwargs):
                assert kwargs["trust_env"] is False
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def get(self, *args, **kwargs):
                return Response()
            def stream(self, *args, **kwargs):
                return Response()
        fake_httpx = types.SimpleNamespace(AsyncClient=FakeClient, Timeout=lambda **kw: kw, Limits=lambda **kw: kw)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"httpx": fake_httpx}), contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp); prepared = root/"prepared"; prepared.mkdir()
            plan = {"concurrency": 8, "model": "glm-5.3-flash", "max_output_tokens": 2048, "cases": []}
            for i in range(8):
                directory = prepared/f"case-{i:02d}"; directory.mkdir()
                client.put(directory/"request.json", {"model": plan["model"], "max_tokens": 2048})
                client.put(directory/"oracle.json", GOLD)
                (directory/"image.png").write_bytes(b"fixture")
                plan["cases"].append({"directory": directory.name, "request_sha256": client.sha(directory/"request.json"),
                    "oracle_sha256": client.sha(directory/"oracle.json"), "image_sha256": client.sha(directory/"image.png")})
            client.put(prepared/"plan.json", plan)
            key = root/"key"; key.write_text("local-fake-token-not-an-actual-secret-123456"); key.chmod(0o600)
            evidence = root/"runtime.json"; client.put(evidence, {"test": "offline fake response only"})
            args = argparse.Namespace(url="http://127.0.0.1:8888", deadline_seconds=60, key_file=key,
                prepared=prepared, output=root/"results", runtime_evidence=evidence)
            asyncio.run(client.run_async(args))
            result = client.load(args.output/"case-00/result.json")
            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["token_ids_count"], 2)
            self.assertEqual(result["content"], json.dumps(GOLD))
            self.assertEqual(result["reasoning"], "A brief check.")
            self.assertEqual(result["usage"]["completion_tokens"], 2)
            summary = client.load(args.output/"summary.json")
            self.assertTrue(summary["all8_completed"])
            self.assertTrue(summary["all8_exact_token_id_counts"])
            self.assertFalse(summary["observed8way60second_processed_context_window"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
