#!/usr/bin/env python3
"""Is the video pixel path deterministic? Load a clip through vLLM's own loader
and the checkpoint's processor N times and hash what the encoder would see.
Also print per-delivered-frame centroid of the green object so we know the
loader hands over frames spanning the whole clip. CPU only, no model."""
import argparse, hashlib, json, sys
import numpy as np

ap = argparse.ArgumentParser(); ap.add_argument("--model", required=True); ap.add_argument("--clip", required=True)
ap.add_argument("--n", type=int, default=5); ap.add_argument("--max-video-tokens", type=int, default=8000); a = ap.parse_args()
from vllm.transformers_utils.processors.glm5next import Glm5NextProcessor
from vllm.model_executor.models.glm4_1v import _to_video_metadata
from vllm.multimodal.media.image import ImageMediaIO
from vllm.multimodal.media.video import VideoMediaIO
proc = Glm5NextProcessor.from_pretrained(a.model); vp = proc.video_processor
vio = VideoMediaIO(ImageMediaIO())
data = open(a.clip, "rb").read()
for i in range(a.n):
    loaded = vio.load_bytes(data); frames, md = loaded.media if hasattr(loaded, "media") else loaded
    meta = _to_video_metadata(md)
    out = proc(text="<|begin_of_video|><|video|><|end_of_video|>", videos=[[frames]], video_metadata=[[meta]],
               do_sample_frames=md.get("do_sample_frames", True), max_image_tokens=a.max_video_tokens)
    pv = out["pixel_values_videos"]; pv = pv.numpy() if hasattr(pv, "numpy") else np.asarray(pv)
    h = hashlib.sha256(np.ascontiguousarray(pv).tobytes()).hexdigest()[:16]
    fr = np.asarray(frames)
    cents = []
    for f in fr:
        g = (f[..., 1].astype(int) > 120) & (f[..., 0].astype(int) < 60) & (f[..., 2].astype(int) < 60)
        ys, xs = np.nonzero(g); cents.append(int(ys.mean()) if len(ys) else -1)
    print(json.dumps({"iter": i, "delivered_frames": int(fr.shape[0]), "fps": md.get("fps"), "duration": md.get("duration"),
                      "total_num_frames": md.get("total_num_frames"), "frames_indices_head": list(md.get("frames_indices", []))[:6],
                      "grid_thw": [int(x) for x in out["video_grid_thw"].tolist()[0]], "pixel_sha256_16": h,
                      "pixel_shape": list(pv.shape), "green_centroid_y_per_delivered_frame": cents}))
