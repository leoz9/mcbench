"""Render capability radar PNG (Pillow only) for README."""
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

from .mccut import font

COLORS = [(255, 199, 44), (219, 0, 7), (90, 180, 255), (120, 220, 120), (200, 120, 255)]


def render_radar(board_path, out, top=4, foot="McBench v1.0 · offline frozen snapshot · higher is better"):
    b = json.loads(Path(board_path).read_text("utf-8"))
    rows = b["rows"][:top]
    keys = list(dict.fromkeys(k for r in rows for k, v in r["radar"].items() if v.get("value") is not None))
    labels = {k: v["label"] for r in rows for k, v in r["radar"].items()}
    W, H, cx, cy, R = 900, 760, 450, 380, 250
    img = Image.new("RGB", (W, H), (24, 24, 24)); d = ImageDraw.Draw(img)
    f, fs = font(20), font(18)
    N = len(keys)
    ang = [-math.pi / 2 + i * 2 * math.pi / N for i in range(N)]
    for s in (.25, .5, .75, 1):
        d.polygon([(cx + R * s * math.cos(a), cy + R * s * math.sin(a)) for a in ang], outline=(70, 70, 70))
    for k, a in zip(keys, ang):
        d.line([cx, cy, cx + R * math.cos(a), cy + R * math.sin(a)], fill=(60, 60, 60))
        lab = labels[k]
        d.text((cx + (R + 40) * math.cos(a), cy + (R + 30) * math.sin(a)), lab, font=f, fill=(245, 245, 245), anchor="mm")
    for i, r in enumerate(rows):
        pts = [(cx + R * ((r["radar"].get(k) or {}).get("value") or 0) / 100 * math.cos(a),
                cy + R * ((r["radar"].get(k) or {}).get("value") or 0) / 100 * math.sin(a)) for k, a in zip(keys, ang)]
        d.line(pts + [pts[0]], fill=COLORS[i % 5], width=4)
        d.text((20, 20 + 28 * i), f"■ {r['model']}  ({r['avg_score']})", font=fs, fill=COLORS[i % 5])
    d.text((20, H - 30), foot, font=fs, fill=(150, 150, 150))
    img.save(out)
    return out
