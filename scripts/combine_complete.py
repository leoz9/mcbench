"""Headline combine that only publishes opencode models once BOTH Hard test (22) and Core test (18)
are complete (other models pass through unchanged). Partial opencode runs stay in runs/ for --resume."""
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mcbench import leaderboard as lb  # noqa: E402
from mcbench.tasks import get_tasks  # noqa: E402

HARD, CORE = ROOT / "runs/hard-v1.1", ROOT / "runs/core-test-v1.1"
need = {"hard": {t["id"] for t in get_tasks("hard-v1.1", "test")}, "core": {t["id"] for t in get_tasks("v1.0", "test")}}
done, oc = defaultdict(lambda: defaultdict(set)), set()
for kind, d in (("hard", HARD), ("core", CORE)):
    for p in (d / "traces").glob("*.json"):
        m, task = p.stem.split("__")[:2]
        if '"runtime": "opencode CLI' in p.read_text("utf-8")[-4000:] or "opencode CLI" in json.load(open(p)).get("runtime", ""):
            oc.add(m)
        done[m][kind].add(task)
complete = {m for m in oc if need["hard"] <= done[m]["hard"] and need["core"] <= done[m]["core"]}
excluded = sorted(oc - complete)
print("opencode complete:", sorted(complete), "| held back (partial):", excluded)
tmp = Path(tempfile.mkdtemp())
for src in (HARD, CORE):
    dst = tmp / src.name / "traces"
    dst.mkdir(parents=True)
    for p in (src / "traces").glob("*.json"):
        if p.stem.split("__")[0] not in excluded:
            shutil.copy(p, dst / p.name)
note = sys.argv[1] if len(sys.argv) > 1 else "Hard test 22 + Core test 18 · offline frozen snapshot · Codex CLI + opencode (free tier) models"
board = lb.combine(tmp / HARD.name, tmp / CORE.name, ROOT / "web", note=note)
shutil.copy(tmp / HARD.name / "combined_leaderboard.json", HARD / "combined_leaderboard.json")
shutil.rmtree(tmp)
vis = ROOT / "runs/vision/vision_leaderboard.json"
if vis.exists():  # combine() looks for it next to hard_dir; we used a temp dir
    shutil.copy(vis, ROOT / "web/data/vision_leaderboard.json")
for r in board["rows"]:
    c = r["core"] or {}
    print(f'{r["model"]:<24} overall={r["overall"]} hard={r["avg_score"]} p1={r["pass_at_1"]} core={c.get("avg_score")} core_p1={c.get("pass_at_1")} sv={r["safety_violations"]}')
