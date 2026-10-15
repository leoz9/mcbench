"""McBench-Vision: multimodal track (item recognition from synthetic frames → MCP pricing).

Frames are rendered from the frozen snapshot's menu names using Pillow (no copyrighted
product photography is redistributed). They are clearly marked as SYNTHETIC placeholders;
community may replace them with licensed photographs under the same schema.
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import mcd
from .env import make_mcp

BASE = {"orderType": 1, "beType": 1}
ROOT = Path(__file__).resolve().parent


def _font(size):
    for p in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def build_dataset(version="v1.0", n=12, seed=20261015):
    import random
    rng = random.Random(seed)
    mcp = make_mcp("offline", version)
    from .mock_server import MockBackend
    b = MockBackend(version); store = b.d["stores"][0]["storeCode"]
    menu = mcd.menu(mcp.call_tool("query-meals", {"storeCode": store, **BASE}))
    nut = mcd.nutrition(mcp.call_tool("list-nutrition-foods", {}))
    singles = [m for m in menu.values() if m["price"] and "套" not in m["name"] and "餐" not in m["name"]
               and mcd.kind(m["name"]) in ("汉堡", "饮品", "小食")]
    out_dir = ROOT / f"data/vision/{version}"; (out_dir / "frames").mkdir(parents=True, exist_ok=True)
    tasks = []
    fnt, fnt_s = _font(36), _font(18)
    for i in range(n):
        k = rng.randint(2, 4)
        picks = rng.sample(singles, k)
        img = Image.new("RGB", (720, 720), (245, 245, 240)); d = ImageDraw.Draw(img)
        d.rectangle([0, 0, 720, 60], fill=(219, 0, 7))
        d.text((16, 12), "McBench-Vision SYNTHETIC (placeholder)", font=fnt_s, fill=(255, 199, 44))
        y = 90
        for m in picks:
            d.rounded_rectangle([40, y, 680, y + 110], 16, fill=(38, 38, 38))
            d.text((60, y + 30), m["name"], font=fnt, fill=(255, 255, 255))
            d.text((60, y + 75), f"¥{m['price']} · {mcd.kind(m['name'])}", font=fnt_s, fill=(160, 160, 160))
            y += 130
        d.text((16, 680), "NOT official photography · names from frozen MCP snapshot", font=fnt_s, fill=(120, 120, 120))
        frame = f"frames/task_{i:02d}.png"; img.save(out_dir / frame)
        items = [{"productCode": m["code"], "quantity": 1} for m in picks]
        q = mcd.quote(mcp.call_tool("calculate-price", {"storeCode": store, **BASE, "items": items}))
        kcal = sum((mcd.match_nutrition(m["name"], nut) or {}).get("kcal") or 0 for m in picks)
        tasks.append({"id": f"vision-{i:02d}", "frame": frame, "labels": [{"code": m["code"], "name": m["name"]} for m in picks],
                      "payable": q["payable"], "kcal": kcal, "split": "dev" if i < n - 3 else "test"})
    meta = {"schema_version": "1.0", "snapshot": version, "synthetic": True,
            "notice": "Frames are Pillow-rendered placeholders using menu names from the frozen MCP snapshot; not official product photography. Replace with licensed photos under the same schema.",
            "tasks": tasks}
    (out_dir / "tasks.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    return out_dir, meta


def score_vision(pred_codes, task):
    gold = {x["code"] for x in task["labels"]}
    pred = set(pred_codes)
    tp = len(gold & pred); fp = len(pred - gold); fn = len(gold - pred)
    prec = tp / max(1, tp + fp); rec = tp / max(1, tp + fn)
    return {"precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(2 * prec * rec / max(1e-9, prec + rec), 3)}


def run_vision_track(a):
    """Offline baseline: 'oracle' reads the synthetic frame's embedded names from labels file
    (honest upper bound). Real vision models are not run here — document the adapter."""
    out_dir, meta = build_dataset()
    print(f"McBench-Vision dataset → {out_dir}  ({len(meta['tasks'])} synthetic frames)")
    print("⚠️  当前未跑真实视觉模型：Codex luna 的图像输入在非交互 exec 下未接入。")
    print("    适配器约定：向模型传入 frame 路径 + 提示「识别图中麦当劳餐品编码，再用 MCP 核价」。")
    print("    指标：item precision/recall/F1、price MAE、kcal MAE。详见 docs/vision.md。")
    # oracle baseline (knows labels — NOT a model)
    scores = [score_vision([x["code"] for x in t["labels"]], t) for t in meta["tasks"]]
    print(f"oracle upper bound F1={sum(s['f1'] for s in scores)/len(scores):.3f}")
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "vision_meta.json").write_text(json.dumps({"oracle": scores, "n": len(scores)}, indent=1), "utf-8")


def codex_vision(model, frame_path, timeout=300):
    """Ask a Codex CLI model (image attached with -i) to list the item names it sees."""
    import re
    import subprocess
    import tempfile
    from .codex_agent import codex_bin
    prompt = ('图中是若干麦当劳餐品卡片。只输出 JSON：{"items": ["餐品名1", "餐品名2", ...]}，'
              '餐品名逐字照抄，不要输出别的内容，不要运行命令。')
    work = tempfile.mkdtemp(prefix="mcbench-vis-")
    p = subprocess.run([codex_bin(), "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", work,
                        "-m", model, "-c", 'approval_policy="never"', "-i", str(frame_path), "--", prompt],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    m = re.findall(r'\{[^{}]*"items"[^{}]*\}', p.stdout)
    try:
        return json.loads(m[-1])["items"] if m else []
    except Exception:  # noqa
        return []


def run_models(models, version="v1.0", out="runs/vision"):
    out_dir, meta = build_dataset(version)
    from .mock_server import MockBackend
    b = MockBackend(version); store = b.d["stores"][0]["storeCode"]
    mcp = make_mcp("offline", version)
    menu = mcd.menu(mcp.call_tool("query-meals", {"storeCode": store, **BASE}))
    by_name = {v["name"]: c for c, v in menu.items()}
    rows = []
    for model in models:
        res = []
        for t in meta["tasks"]:
            names = codex_vision(model, out_dir / t["frame"])
            codes = [by_name[n] for n in names if n in by_name]
            s = score_vision(codes, t)
            pay = mcd.quote(mcp.call_tool("calculate-price", {"storeCode": store, **BASE,
                                                              "items": [{"productCode": c, "quantity": 1} for c in codes]}))["payable"] if codes else 0
            s.update(id=t["id"], pred=names, price_err=round(abs((pay or 0) - t["payable"]), 2))
            res.append(s); print(model, t["id"], s["f1"], s["price_err"])
        n = len(res)
        rows.append({"model": model, "f1": round(sum(r["f1"] for r in res) / n, 3),
                     "exact": round(sum(1 for r in res if r["f1"] == 1) / n, 3),
                     "price_mae": round(sum(r["price_err"] for r in res) / n, 2), "tasks": res})
    Path(out).mkdir(parents=True, exist_ok=True)
    Path(out, "vision_leaderboard.json").write_text(json.dumps({"synthetic": True, "rows": rows}, ensure_ascii=False, indent=1), "utf-8")
    return rows
