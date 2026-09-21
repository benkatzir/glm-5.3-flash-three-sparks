#!/usr/bin/env python3
"""Extra clips to isolate the 720p 'stationary' answer: same green circle rising,
at different sizes / lengths, plus controls. Runs in the serving image (cv2)."""
import argparse, hashlib, json, os
import numpy as np, cv2

BG = (200, 200, 200); GREEN = (0, 160, 0); RED = (0, 0, 255)


def frame(w, h):
    f = np.empty((h, w, 3), np.uint8); f[:] = BG; return f


def write(path, w, h, fps, n, draw, start, end):
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h)); assert vw.isOpened()
    for i in range(n):
        t = i / max(n - 1, 1)
        x = int(round(start[0] + (end[0] - start[0]) * t)); y = int(round(start[1] + (end[1] - start[1]) * t))
        f = frame(w, h); draw(f, x, y); vw.write(f)
    vw.release()


circ = lambda f, x, y: cv2.circle(f, (x, y), 70, GREEN, -1)
circ_small = lambda f, x, y: cv2.circle(f, (x, y), 40, GREEN, -1)
sq = lambda f, x, y: cv2.rectangle(f, (x - 50, y - 50), (x + 50, y + 50), RED, -1)

ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
clips = {
    "green-circle-up-480p-4s.mp4": (640, 480, 8, 32, circ_small, (320, 420), (320, 60)),
    "green-circle-up-720p-4s.mp4": (1280, 720, 8, 32, circ, (640, 640), (640, 80)),
    "green-circle-up-720p-8s-4fps.mp4": (1280, 720, 4, 32, circ, (640, 640), (640, 80)),
    "green-circle-down-720p-8s.mp4": (1280, 720, 8, 64, circ, (640, 80), (640, 640)),
    "red-square-right-720p-8s.mp4": (1280, 720, 8, 64, sq, (100, 360), (1180, 360)),
}
man = {}
for name, (w, h, fps, n, d, s, e) in clips.items():
    p = os.path.join(a.out, name); write(p, w, h, fps, n, d, s, e)
    man[name] = {"sha256": hashlib.sha256(open(p, "rb").read()).hexdigest(), "w": w, "h": h, "fps": fps, "frames": n}
json.dump(man, open(os.path.join(a.out, "diag-manifest.json"), "w"), indent=1); print(json.dumps(man, indent=1))
