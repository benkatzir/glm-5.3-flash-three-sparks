#!/usr/bin/env python3
"""Live health/auth/image smoke probe. Reads the secret file without printing it.

Usage: python3 probe-private-api.py --url http://127.0.0.1:8888
 --key-file /home/ben/glm53-lab/private/api-key [--auth-only]
This checks authorization, not native-relative model quality or long context.
"""
import argparse
import base64
import json
from pathlib import Path
import urllib.error
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--key-file", type=Path, required=True)
    p.add_argument("--auth-only", action="store_true")
    p.add_argument("--image", type=Path, default=Path(__file__).with_name("smoke-fixtures") / "shapes.png")
    a = p.parse_args()
    key = a.key_file.read_text().strip()
    # Do not use environment-configured outbound HTTP proxies for local API keys.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path, method="GET", body=None, auth=None):
        headers = {"Content-Type": "application/json"}
        if auth is not None:
            headers["Authorization"] = "Bearer " + auth
        req = urllib.request.Request(a.url.rstrip("/") + path, data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
        try:
            with opener.open(req, timeout=1800) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
    code, _ = request("/health")
    if code != 200:
        raise SystemExit(f"Health failed: HTTP{code}")
    for path, method in [("/v1/models", "GET"), ("/v1/chat/completions", "POST"), ("/invocations", "POST"), ("/invocations", "OPTIONS"), ("/metrics", "GET")]:
        for auth in (None, "invalid-local-probe-key"):
            code, _ = request(path, method, {} if method == "POST" else None, auth)
            if code != 401:
                raise SystemExit(f"AUTH GATE FAILED: {method} {path} yielded HTTP{code}")
    code, body = request("/v1/models", auth=key)
    if code != 200:
        raise SystemExit(f"Authorized models failed: HTTP{code}")
    model = json.loads(body)["data"][0]["id"]
    print(json.dumps({"auth_gate": "pass", "model": model, "health": 200}))
    if a.auth_only:
        return
    data = base64.b64encode(a.image.read_bytes()).decode()
    payload = {"model": model, "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + data}}, {"type": "text", "text": "Describe the color, shape and left/right position of both objects in this image. Be concise."}]}], "max_tokens": 512, "temperature": 0, "chat_template_kwargs": {"clear_thinking": True, "reasoning_effort": "low"}}
    code, body = request("/v1/chat/completions", "POST", payload, key)
    if code != 200:
        raise SystemExit(f"Vision request failed: HTTP{code}")
    answer = json.loads(body)
    content = answer["choices"][0]["message"].get("content", "")
    print(json.dumps({"vision_answer": content, "expected": "left red square; right blue circle", "usage": answer.get("usage"), "finish_reason": answer["choices"][0].get("finish_reason")}))
    if not all(word in content.lower() for word in ["red", "square", "blue", "circle"]):
        raise SystemExit("Vision semantic smoke failed: expected object/color words missing")


if __name__ == "__main__":
    main()
