#!/usr/bin/env python3
"""Deterministic PNG smoke fixture, independent of image libraries/fonts."""
import hashlib
import json
from pathlib import Path
import struct
import zlib

p = Path(__file__).with_name("smoke-fixtures")
p.mkdir(exist_ok=True)
width, height = 512, 256
rows = []
for y in range(height):
    row = bytearray([0])
    for x in range(width):
        color = (255, 255, 255)
        if 50 <= x < 190 and 58 <= y < 198:
            color = (240, 0, 0)
        if (x - 372)**2 + (y - 128)**2 < 70**2:
            color = (0, 0, 240)
        row.extend(color)
    rows.append(bytes(row))

def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)

png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")
dest = p / "shapes.png"
dest.write_bytes(png)
(p / "manifest.json").write_text(json.dumps({"file": dest.name, "sha256": hashlib.sha256(png).hexdigest(), "question": "Describe the color, shape and left/right position of both objects.", "expected": "left red square; right blue circle"}, indent=2) + "\n")
print(dest)
