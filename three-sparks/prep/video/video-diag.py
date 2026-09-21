#!/usr/bin/env python3
"""Ad-hoc video diagnosis: send one or more clips with a prompt, print content,
reasoning length/head, usage, finish_reason. Key read from file, never printed."""
import argparse, base64, json, time, urllib.request, urllib.error


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8888")
    ap.add_argument("--key-file", required=True)
    ap.add_argument("--clip", action="append", required=True)
    ap.add_argument("--prompt", default="Describe the color, shape and direction of motion of the object in this video. Be concise.")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    key = open(a.key_file).read().strip()
    parts = [{"type": "video_url", "video_url": {"url": "data:video/mp4;base64," + base64.b64encode(open(c, "rb").read()).decode()}} for c in a.clip]
    parts.append({"type": "text", "text": a.prompt})
    body = {"model": "glm-5.3-flash", "messages": [{"role": "user", "content": parts}], "max_tokens": a.max_tokens,
            "temperature": 0, "chat_template_kwargs": {"clear_thinking": True, "reasoning_effort": a.effort}}
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(a.url.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    t0 = time.monotonic()
    try:
        with op.open(req, timeout=1800) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    dt = time.monotonic() - t0
    j = json.loads(raw)
    if code != 200:
        print(json.dumps({"label": a.label, "http": code, "error": str(j)[:400]})); return
    m = j["choices"][0]["message"]
    rc = m.get("reasoning_content") or m.get("reasoning") or ""
    print(json.dumps({"label": a.label, "clips": [c.rsplit("/", 1)[-1] for c in a.clip], "max_tokens": a.max_tokens, "effort": a.effort,
                      "seconds": round(dt, 1), "usage": j.get("usage"), "finish": j["choices"][0].get("finish_reason"),
                      "content": (m.get("content") or "")[:400], "reasoning_chars": len(rc), "reasoning_head": rc[:300].replace("\n", " "),
                      "reasoning_tail": rc[-300:].replace("\n", " ")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
