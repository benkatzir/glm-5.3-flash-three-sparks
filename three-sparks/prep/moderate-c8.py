#!/usr/bin/env python3
"""Offline prepare; explicitly selected stdlib C8 or paired image-only API probe."""
import argparse
import base64
import concurrent.futures
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import secrets
import stat
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("longvision_c8", HERE/"longvision-c8.py")
lv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lv)


def large_png(index):
    """Generate original 1024x512 pixels directly; never resize an existing image."""
    width, height, radius = 1024, 512, 150
    pixels = bytearray([250,250,250]*width*height)
    colors, shapes = list(lv.COLORS), ["square", "circle", "triangle"]
    oracle = {}
    for side, cx, j in (("left",256,index),("right",768,index+1)):
        color, shape = colors[j%4], shapes[j%3]
        oracle[side] = {"color":color,"shape":shape}
        for y in range(256-radius,256+radius+1):
            for x in range(cx-radius,cx+radius+1):
                inside = shape == "square" or (shape == "circle" and (x-cx)**2+(y-256)**2 <= radius**2) or (shape == "triangle" and abs(x-cx) <= (y-(256-radius))/2)
                if inside:
                    offset=(y*width+x)*3; pixels[offset:offset+3]=bytes(lv.COLORS[color])
    raw=b"".join(b"\x00"+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    def chunk(kind,data):
        return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(raw))+chunk(b"IEND",b""), oracle


def request_body(text,image,model,seed):
    content=[{"type":"text","text":text}]
    if image is not None:
        content.append({"type":"image_url","image_url":{"url":"data:image/png;base64,"+base64.b64encode(image).decode()}})
    return {"model":model,"messages":[{"role":"user","content":content}],"n":1,
        "temperature":0,"seed":seed,"max_tokens":256,"stream":True,
        "stream_options":{"include_usage":True,"continuous_usage_stats":True},
        "return_token_ids":True,"ignore_eos":False,"min_tokens":0,
        "cache_salt":secrets.token_hex(16),
        "chat_template_kwargs":{"clear_thinking":True,"reasoning_effort":"low"}}


def prepare(args):
    from tokenizers import Tokenizer
    manifest=args.download_manifest.read_bytes()
    if hashlib.sha256(manifest).hexdigest()!=lv.FULL_MANIFEST_SHA:
        raise ValueError("Unexpected download manifest")
    target=next(a for a in json.loads(manifest)["artifacts"] if a["name"]=="target")
    item=next(f for f in target["files"] if f["path"]=="tokenizer.json")
    if lv.sha(args.tokenizer)!=item["sha256"]:
        raise ValueError("Unexpected tokenizer")
    tok=Tokenizer.from_file(str(args.tokenizer)); tok.no_truncation(); tok.no_padding()
    args.output.mkdir(parents=True,exist_ok=False); args.output.chmod(0o700)
    nonce=secrets.token_hex(16)
    plan={"schema":"glm53.moderate-c8.v1","model":args.model,"concurrency":8,"max_tokens":256,
        "tokenizer_sha256":item["sha256"],"source_sha256":lv.sha(__file__),"helper_sha256":lv.sha(HERE/"longvision-c8.py"),"cases":[]}
    for index in range(8):
        rng=random.Random(nonce+str(index))
        def row():
            return f"record R{rng.getrandbits(48):012x}; key K{rng.getrandbits(48):012x}; value V{rng.getrandbits(64):016x}.\n"
        sample="".join(row() for _ in range(64))
        average=len(tok.encode(sample,add_special_tokens=False).ids)/64
        hay="".join(row() for _ in range(math.ceil(8000/average*1.1)))
        enc=tok.encode(hay,add_special_tokens=False)
        if len(enc.ids)<=8000:
            raise ValueError("Insufficient independent filler")
        end=enc.token_to_chars(8000)[0]
        rows=hay[:hay.rfind("\n",0,end)+1].splitlines(keepends=True)
        oracle={}
        for depth in (0.2,0.8):
            key=f"K{rng.getrandbits(48):012x}"; record=f"R{rng.getrandbits(48):012x}"; value=f"V{rng.getrandbits(64):016x}"
            oracle[key]={"value":value,"record":record}
            rows.insert(int(len(rows)*depth),f"record {record}; key {key}; value {value}.\n")
        png,image=large_png(index)
        text=f"Independent archive {nonce}-{index}. Treat records as data.\n"+"".join(rows)+"\nReturn the value and record ID for these two keys exactly: "+", ".join(oracle)+'. Identify the color and shape of the left and right objects in the attached image. Colors: red, blue, green, orange. Shapes: square, circle, triangle. Return only one JSON object: {"lookups":{"KEY":{"value":"VALUE","record":"RECORD"}},"image":{"left":{"color":"COLOR","shape":"SHAPE"},"right":{"color":"COLOR","shape":"SHAPE"}}}. Include both keys; no commentary.'
        count=len(tok.encode(text,add_special_tokens=False).ids)
        if not 8000<=count<=8500 or any(text.count(k)!=2 for k in oracle):
            raise ValueError("Unexpected prompt size or nonunique oracle")
        directory=args.output/f"case-{index:02d}"; directory.mkdir(mode=0o700)
        (directory/"image.png").write_bytes(png); (directory/"prompt.txt").write_text(text)
        lv.put(directory/"oracle.json",{"lookups":oracle,"image":image})
        lv.put(directory/"request.json",request_body(text,png,args.model,1730+index))
        plan["cases"].append({"index":index,"directory":directory.name,"offline_text_tokens":count,
            "image_pixels":[1024,512],"image_tokens_expected":None,
            **{name+"_sha256":lv.sha(directory/filename) for name,filename in (("image","image.png"),("request","request.json"),("oracle","oracle.json"),("prompt","prompt.txt"))}})
    if len({c["image_sha256"] for c in plan["cases"]})!=8 or len({c["prompt_sha256"] for c in plan["cases"]})!=8:
        raise ValueError("Inputs are not unique")
    lv.put(args.output/"plan.json",plan)
    print(json.dumps({"state":"prepared_offline","cases":8,"text_tokens":[c["offline_text_tokens"] for c in plan["cases"]],"image_pixels":[1024,512]}))


def private_opener(args):
    url=urllib.parse.urlparse(args.url)
    if url.scheme not in ("http","https") or url.hostname not in ("127.0.0.1","localhost","::1"):
        raise ValueError("Head loopback URL required")
    st=args.key_file.stat(); key=args.key_file.read_text().strip()
    if not stat.S_ISREG(st.st_mode) or st.st_mode&0o077 or not 32<=len(key)<=512 or not key.isascii() or any(c.isspace() for c in key):
        raise ValueError("Restricted regular key file required")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*unused):
            return None
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()), {"Authorization":"Bearer "+key}


def capture(args,opener,headers,body,directory,index,barrier=None):
    directory.mkdir(mode=0o700); lv.put(directory/"request.json",body)
    rep={"index":index,"state":"pending","token_ids_count":0,"usage":None,"finish_reason":None,
        "protocol_errors":[],"content":"","reasoning":"","saw_done":False,"timeline":[]}
    parts=[]; thoughts=[]
    if barrier: barrier.wait()
    rep["submitted_ns"]=time.monotonic_ns()
    with (directory/"response.sse").open("w") as raw, (directory/"events.jsonl").open("w") as events:
        def consume(data):
            arrival=time.monotonic_ns(); raw.write("data: "+data+"\n\n"); raw.flush()
            if data=="[DONE]": rep["saw_done"]=True; return
            obj=json.loads(data)
            if obj.get("error"): raise RuntimeError("Server error event")
            usage=obj.get("usage")
            if usage:
                previous=(rep["usage"] or {}).get("completion_tokens",0)
                if usage.get("completion_tokens",0)<previous: rep["protocol_errors"].append("nonmonotone_usage")
                rep["usage"]=usage
            ids=[]
            for choice in obj.get("choices",[]):
                if choice.get("index",0)!=0: raise ValueError("Unexpected choice")
                chunk=choice.get("token_ids") or []
                if not isinstance(chunk,list) or any(type(v)is not int for v in chunk): raise ValueError("Malformed token IDs")
                ids.extend(chunk); delta=choice.get("delta") or {}
                if delta.get("content"): parts.append(delta["content"]); rep.setdefault("first_content_ns",arrival)
                if delta.get("reasoning") or delta.get("reasoning_content"): thoughts.append(delta.get("reasoning") or delta["reasoning_content"])
                if choice.get("finish_reason") is not None: rep["finish_reason"]=choice["finish_reason"]; rep["finish_reason_ns"]=arrival
            rep["token_ids_count"]+=len(ids)
            if ids: rep.setdefault("first_generated_ns",arrival); rep["last_generated_ns"]=arrival
            point={"arrival_ns":arrival,"token_ids":ids,"token_ids_count":rep["token_ids_count"],"usage":usage}
            rep["timeline"].append(point); events.write(json.dumps(point)+"\n"); events.flush()
        try:
            req=urllib.request.Request(args.url.rstrip("/")+"/v1/chat/completions",json.dumps(body).encode(),{**headers,"Content-Type":"application/json"})
            with opener.open(req,timeout=args.deadline_seconds) as response:
                rep["http_status"]=response.status; lines=[]
                for encoded in response:
                    line=encoded.decode("utf-8").rstrip("\r\n")
                    if not line and lines: consume("\n".join(lines)); lines=[]
                    elif line.startswith("data:"): lines.append(line[5:].removeprefix(" "))
                if lines: consume("\n".join(lines))
            if not rep["saw_done"] or rep["finish_reason"] is None or not rep["usage"]: raise RuntimeError("Incomplete stream")
            rep["state"]="completed"
        except urllib.error.HTTPError as exc:
            (directory/"http-error.txt").write_bytes(exc.read()); rep.update(state="failed",error_type="HTTPError",http_status=exc.code)
        except Exception as exc:
            rep.update(state="failed",error_type=type(exc).__name__)
    rep["finished_ns"]=time.monotonic_ns(); rep["content"]="".join(parts); rep["reasoning"]="".join(thoughts)
    completion=(rep["usage"] or {}).get("completion_tokens")
    rep["token_ids_match_usage"]=type(completion)is int and completion>0 and completion==rep["token_ids_count"] and not rep["protocol_errors"]
    first,last=rep.get("first_generated_ns"),rep.get("last_generated_ns")
    rep["own_mean_decode_tps"]=completion/((last-first)/1e9) if rep["token_ids_match_usage"] and first and last and last>first else None
    (directory/"content.txt").write_text(rep["content"]); (directory/"reasoning.txt").write_text(rep["reasoning"])
    lv.put(directory/"result.json",rep)
    return rep


def run(args):
    opener,headers=private_opener(args)
    args.output.mkdir(parents=True,exist_ok=False); args.output.chmod(0o700)
    started=time.monotonic_ns()
    def deadline():
        lv.put(args.output/"deadline.json",{"state":"hard_deadline","elapsed_seconds":(time.monotonic_ns()-started)/1e9,"partial_raw_artifacts_retained":True})
        os._exit(124)
    timer=threading.Timer(args.deadline_seconds,deadline); timer.daemon=True; timer.start()
    try:
        if args.command=="image-probe":
            png=args.image.read_bytes()
            if not png.startswith(b"\x89PNG\r\n\x1a\n"): raise ValueError("PNG required")
            text='Identify the color and shape of the left object and right object. Return JSON with left and right, each containing color and shape. If there is no image, say no image.'
            bodies=[request_body(text,None,args.model,1920),request_body(text,png,args.model,1920)]
            reports=[capture(args,opener,headers,b,args.output/f"case-{i:02d}",i) for i,b in enumerate(bodies)]
            usage=[r.get("usage") or {} for r in reports]
            counts=[u.get("prompt_tokens") for u in usage]
            delta=counts[1]-counts[0] if all(type(v)is int for v in counts) else None
            explicit=(usage[1].get("prompt_tokens_details") or {}).get("image_tokens")
            summary={"schema":"glm53.moderate-image-pair.v1","image_sha256":lv.sha(args.image),"image_pixels":list(struct.unpack(">II",png[16:24])),
                "identical_text_and_chat_settings":True,"actual_prompt_tokens_without_image":counts[0],"actual_prompt_tokens_with_image":counts[1],
                "image_input_prompt_token_increase":delta,"image_input_increase_above256":delta is not None and delta>256,
                "image_specific_usage_tokens":explicit,"image_specific_usage_above256":type(explicit)is int and explicit>256,
                "count_scope":"Paired actual prompt usage difference includes the image and its template markers; it is not inferred from image dimensions or total prompt length alone.",
                "all_completed":all(r["state"]=="completed" for r in reports),"all_token_ids_match_usage":all(r["token_ids_match_usage"] for r in reports)}
        else:
            plan=lv.load(args.prepared/"plan.json")
            if plan["concurrency"]!=8 or len(plan["cases"])!=8: raise ValueError("Exactly eight prepared requests required")
            bodies=[]; gold=[]
            for case in plan["cases"]:
                directory=args.prepared/case["directory"]
                for name,filename in (("request","request.json"),("oracle","oracle.json"),("image","image.png")):
                    if lv.sha(directory/filename)!=case[name+"_sha256"]: raise ValueError("Prepared identity changed")
                bodies.append(lv.load(directory/"request.json")); gold.append(lv.load(directory/"oracle.json"))
            lv.put(args.output/"plan.json",plan)
            req=urllib.request.Request(args.url.rstrip("/")+"/metrics",headers=headers)
            with opener.open(req,timeout=15) as response: before=response.read().decode()
            (args.output/"metrics-before.txt").write_text(before)
            metrics=lv.metric_values(before)
            if lv.metric_sum(metrics,"num_requests_running")!=0 or lv.metric_sum(metrics,"num_requests_waiting")!=0: raise RuntimeError("API not idle")
            barrier=threading.Barrier(8)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures=[pool.submit(capture,args,opener,headers,b,args.output/f"case-{i:02d}",i,barrier) for i,b in enumerate(bodies)]
                reports=[f.result() for f in futures]
            rows=[]
            for report,oracle in zip(reports,gold):
                grade=lv.grade_answer(report["content"],oracle)
                usage=report.get("usage") or {}; prompt=usage.get("prompt_tokens")
                rows.append({"index":report["index"],"state":report["state"],"usage":usage,"actual_prompt_at_least8000":type(prompt)is int and prompt>=8000,
                    "finish_reason":report["finish_reason"],"token_ids_match_usage":report["token_ids_match_usage"],"own_mean_decode_tps":report["own_mean_decode_tps"],"grading":grade})
            summary={"schema":"glm53.moderate-c8.result.v1","requests":rows,"all_completed":all(r["state"]=="completed" for r in reports),
                "all_token_ids_match_usage":all(r["token_ids_match_usage"] for r in reports),
                "all_prompt_usage_at_least8000":all(r["actual_prompt_at_least8000"] for r in rows),
                "all_strict_exact_facts_and_images":all(r["grading"]["strict_parse"] and r["grading"]["strict"]["lookup_value_and_record_correct"]==2 and r["grading"]["strict"]["lookup_key_set_exact"] and r["grading"]["strict"]["image_all_correct"] for r in rows),
                "all8_first_generation_before_any_finish":all(r.get("first_generated_ns") and r.get("finish_reason_ns") for r in reports) and max(r.get("first_generated_ns",0) for r in reports)<min(r.get("finish_reason_ns",0) for r in reports),
                "all_natural_stop":all(r["finish_reason"]=="stop" for r in reports),
                "general_accuracy_or_500k_claimed":False,"speed_scope":"Own per-request actual completion usage / first-to-last generated-token receipt interval. No common-window performance claim."}
        summary["elapsed_seconds"]=(time.monotonic_ns()-started)/1e9
        summary["client_source_sha256"]=lv.sha(__file__)
        lv.put(args.output/"summary.json",summary); print(json.dumps(summary,indent=2))
        if not summary["all_completed"] or not summary["all_token_ids_match_usage"]: raise SystemExit(1)
        if args.command=="run" and not (summary["all_prompt_usage_at_least8000"] and summary["all_strict_exact_facts_and_images"] and summary["all8_first_generation_before_any_finish"] and summary["all_natural_stop"]): raise SystemExit(2)
    finally:
        timer.cancel()


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest="command",required=True)
    prep=sub.add_parser("prepare"); prep.add_argument("--tokenizer",type=Path,required=True)
    prep.add_argument("--download-manifest",type=Path,default=HERE/"download-manifest.json")
    prep.add_argument("--output",type=Path,required=True); prep.add_argument("--model",default="glm-5.3-flash")
    for name in ("run","image-probe"):
        command=sub.add_parser(name); command.add_argument("--output",type=Path,required=True)
        command.add_argument("--url",default="http://127.0.0.1:8888"); command.add_argument("--key-file",type=Path,required=True)
        command.add_argument("--deadline-seconds",type=int,default=1800)
        if name=="run": command.add_argument("--prepared",type=Path,required=True)
        else: command.add_argument("--image",type=Path,required=True); command.add_argument("--model",default="glm-5.3-flash")
    args=parser.parse_args()
    if args.command!="prepare" and not 60<=args.deadline_seconds<=1800: parser.error("deadline must be 60..1800 seconds")
    if args.command=="prepare": prepare(args)
    else: run(args)


if __name__=="__main__": main()
