"""Regenerate the headline Overall table in README.md / README_EN.md from web/data/leaderboard.json."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = json.load(open(ROOT / "web/data/leaderboard.json", encoding="utf-8"))["rows"]
rows = [r for r in rows if r["overall"] is not None]
cols = [("overall", lambda r: r["overall"]), ("hard", lambda r: r["avg_score"]), ("hp1", lambda r: r["pass_at_1"]),
        ("core", lambda r: r["core"]["avg_score"]), ("cp1", lambda r: r["core"]["pass_at_1"])]
best = {k: max(f(r) for r in rows if not r["model"].startswith("demo-")) for k, f in cols}


def label(r, zh):
    m, rt = r["model"], r["runtime"] or ""
    if m == "demo-planner":
        return m + ("（精确求解器脚本，上界参考）" if zh else " (exact-solver script, upper reference)")
    if rt.startswith("Codex CLI"):
        s = "Codex CLI"
    elif rt.startswith("opencode CLI"):
        s = "opencode 免费档" if zh else "opencode, free tier"
    else:
        return m
    return m + (f"（{s}）" if zh else f" ({s})")


def fmt(k, v, r):
    s = f"{v * 100:.1f}%".replace(".0%", "%") if k in ("hp1", "cp1") else f"{v:.1f}"
    return f"**{s}**" if (not r["model"].startswith("demo-") and v == best[k]) else s


def table(zh):
    hdr = ("| Agent | Overall | Hard 分 | Hard pass@1 | Core 分 | Core pass@1 |" if zh else
           "| Agent | Overall | Hard score | Hard pass@1 | Core score | Core pass@1 |")
    out = [hdr, "|---|---:|---:|---:|---:|---:|"]
    for i, r in enumerate(rows):
        name = label(r, zh)
        if i == 0:
            name = re.sub(r"^([^（ (]+)", r"**\1**", name)
        out.append("| " + " | ".join([name] + [fmt(k, f(r), r) for k, f in cols]) + " |")
    return "\n".join(out)


for fn, zh in (("README.md", True), ("README_EN.md", False)):
    p = ROOT / fn
    s = p.read_text("utf-8")
    pat = re.compile(r"^\| Agent \| Overall \|.*?\n(?:\|.*\n)+", re.M)
    assert pat.search(s), fn
    s = pat.sub(table(zh) + "\n", s, count=1)
    p.write_text(s, "utf-8")
    print(fn, "updated")
