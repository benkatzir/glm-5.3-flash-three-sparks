#!/usr/bin/env python3
"""Deterministic synthetic video/image assets for the GLM-5.3 Flash vision arm.

Runs inside the serving image (cv2 + numpy present), no GPU, no model.

Writes two groups:
  <out>/fixtures/   the two 4-second clips the boot-time geometry gate reads
                    (copied to $TP3_DIR/fixtures on every node)
  <out>/tests/      extra clips and PNGs used only by the API tests
                    (never placed under $TP3_DIR, so the gate never sees them)

Every asset is drawn from constants, so the pixel content is identical on
every run; the mp4 container bytes depend on the encoder build, so manifest.json
records sha256 of what was actually produced.
"""
import argparse, hashlib, json, os
import numpy as np
import cv2

BG = (200, 200, 200)  # light gray, BGR


def frame(w, h):
    f = np.empty((h, w, 3), np.uint8)
    f[:] = BG
    return f


def write_video(path, w, h, fps, frames):
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert vw.isOpened(), path
    for f in frames:
        vw.write(f)
    vw.release()


def moving(w, h, n, draw, start, end):
    out = []
    for i in range(n):
        t = i / max(n - 1, 1)
        x = int(round(start[0] + (end[0] - start[0]) * t))
        y = int(round(start[1] + (end[1] - start[1]) * t))
        f = frame(w, h)
        draw(f, x, y)
        out.append(f)
    return out


def sq(color, s):
    return lambda f, x, y: cv2.rectangle(f, (x - s // 2, y - s // 2), (x + s // 2, y + s // 2), color, -1)


def rect(color, rw, rh):
    return lambda f, x, y: cv2.rectangle(f, (x - rw // 2, y - rh // 2), (x + rw // 2, y + rh // 2), color, -1)


def circ(color, r):
    return lambda f, x, y: cv2.circle(f, (x, y), r, color, -1)


def tri(color, s):
    def d(f, x, y):
        pts = np.array([[x, y - s], [x - s, y + s], [x + s, y + s]], np.int32)
        cv2.fillPoly(f, [pts], color)
    return d


RED, BLUE, GREEN, YELLOW, BLACK = (0, 0, 255), (255, 0, 0), (0, 160, 0), (0, 220, 255), (0, 0, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    fx, ts = os.path.join(a.out, "fixtures"), os.path.join(a.out, "tests")
    os.makedirs(fx, exist_ok=True); os.makedirs(ts, exist_ok=True)
    spec = {}

    # --- gate fixtures: 640x480, 8 fps, 32 frames = 4.0 s (upstream's geometry)
    p = os.path.join(fx, "red-square-right.mp4")
    write_video(p, 640, 480, 8, moving(640, 480, 32, sq(RED, 100), (80, 240), (560, 240)))
    spec[p] = "red square, 640x480 8fps 32f, moves left->right"
    p = os.path.join(fx, "blue-rect-down.mp4")
    write_video(p, 640, 480, 8, moving(640, 480, 32, rect(BLUE, 160, 90), (320, 70), (320, 410)))
    spec[p] = "blue rectangle, 640x480 8fps 32f, moves top->bottom"

    # --- API-test-only clips
    p = os.path.join(ts, "green-circle-up-720p.mp4")
    write_video(p, 1280, 720, 8, moving(1280, 720, 64, circ(GREEN, 70), (640, 640), (640, 80)))
    spec[p] = "green circle, 1280x720 8fps 64f (8 s), moves bottom->top"
    p = os.path.join(ts, "yellow-triangle-left-1080p.mp4")
    write_video(p, 1920, 1080, 8, moving(1920, 1080, 64, tri(YELLOW, 110), (1700, 540), (220, 540)))
    spec[p] = "yellow triangle, 1920x1080 8fps 64f (8 s), moves right->left"
    p = os.path.join(ts, "short-2frame-0.25s.mp4")
    write_video(p, 640, 480, 8, moving(640, 480, 2, sq(RED, 100), (200, 240), (440, 240)))
    spec[p] = "2 frames at 8 fps = 0.25 s; below the sampler floor, must be HTTP 400 not a dead engine"

    # --- images for the 4-image tests
    for name, draw in [("red-circle.png", circ(RED, 90)), ("blue-square.png", sq(BLUE, 180)),
                       ("green-triangle.png", tri(GREEN, 100))]:
        f = frame(400, 400); draw(f, 200, 200)
        p = os.path.join(ts, name); cv2.imwrite(p, f); spec[p] = name[:-4]
    f = frame(600, 240)
    cv2.putText(f, "ELEPHANT", (40, 160), cv2.FONT_HERSHEY_SIMPLEX, 3.0, BLACK, 10, cv2.LINE_AA)
    p = os.path.join(ts, "elephant-text.png"); cv2.imwrite(p, f); spec[p] = "the word ELEPHANT"

    man = {}
    for p, desc in spec.items():
        b = open(p, "rb").read()
        info = {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b), "description": desc}
        if p.endswith(".mp4"):
            c = cv2.VideoCapture(p)
            info.update(frames=int(c.get(cv2.CAP_PROP_FRAME_COUNT)), fps=c.get(cv2.CAP_PROP_FPS),
                        width=int(c.get(cv2.CAP_PROP_FRAME_WIDTH)), height=int(c.get(cv2.CAP_PROP_FRAME_HEIGHT)))
            c.release()
        man[os.path.relpath(p, a.out)] = info
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    print(json.dumps(man, indent=1))


if __name__ == "__main__":
    main()
