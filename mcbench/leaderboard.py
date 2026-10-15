import json
import shutil
from pathlib import Path

from .metrics import aggregate


def load_traces(run_dir):
    return [json.loads(p.read_text("utf-8")) for p in sorted(Path(run_dir).glob("traces/*.json"))]


def build(run_dir, note=None):
    traces = load_traces(run_dir)
    rows = aggregate(traces)
    vis = Path(run_dir).parent / "vision" / "vision_leaderboard.json"
    if vis.exists():  # merge McBench-Vision F1 as the multimodal radar dimension
        vrows = {r["model"]: r for r in json.loads(vis.read_text("utf-8"))["rows"]}
        for r in rows:
            v = vrows.get(r["model"]) or vrows.get(r["model"].removesuffix("-codex"))
            if v:
                r["radar"]["multimodal"] = {"label": "多模态(合成帧)", "value": round(100 * v["f1"], 1)}
                r["vision"] = {k: v[k] for k in ("f1", "exact", "price_mae")}
    mode = traces[0]["mcp_mode"] if traces else "?"
    board = {"schema_version": "1.0", "mcp_mode": mode, "is_mock": mode in ("mock", "offline") and all(r["model"].startswith("demo-") for r in rows),
             "task_set": traces[0].get("task_set") if traces else None,
             "rows": rows, "n_traces": len(traces), "note": note or ""}
    Path(run_dir, "leaderboard.json").write_text(json.dumps(board, ensure_ascii=False, indent=1), "utf-8")
    return board


def print_board(board):
    if board["is_mock"]:
        print("⚠️  MOCK 演示：冻结快照 + 脚本基线（非大模型）。")
    elif board["mcp_mode"] in ("mock", "offline"):
        print("ℹ️  离线冻结快照（录制自 mcp.mcd.cn，已脱敏，可复现）。")
    print(f"\n{'#':<3}{'Agent':<22}{'均分':>6}{'pass@1':>8}{'pass^k':>8}{'任务':>6}{'调用':>6}{'安全违规':>8}")
    for i, r in enumerate(board["rows"], 1):
        print(f"{i:<3}{r['model']:<22}{r['avg_score']:>6}{r['pass_at_1']:>8.3f}{r['pass_hat_k']:>8.3f}"
              f"{r['n_tasks']:>6}{r['tool_calls']:>6}{r['safety_violations']:>8}")
    print()


def export_web(run_dir, web_dir, sub="data"):
    dst = Path(web_dir, sub)
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "traces").mkdir(parents=True)
    shutil.copy(Path(run_dir, "leaderboard.json"), dst / "leaderboard.json")
    for p in Path(run_dir, "traces").glob("*.json"):
        shutil.copy(p, dst / "traces" / p.name)
    return dst


def combine(hard_dir, core_dir, web_dir, core_split="test", w_hard=0.6, note=""):
    """Headline board: McBench-Hard (v1.1) + Core (v1.0, held-out test split for comparability).
    Overall = 0.6·Hard + 0.4·Core (avg rubric score)."""
    from .tasks import get_tasks
    hard = load_traces(hard_dir)
    core_ids = {t["id"] for t in get_tasks("v1.0", core_split)}
    core = [t for t in load_traces(core_dir) if t["task"] in core_ids]
    hrows = {r["model"]: r for r in aggregate(hard)}
    crows = {}
    for r in aggregate(core):
        crows[r["model"].removesuffix("-codex")] = r
    rows = []
    for cm, c in crows.items():  # models with Core results but no Hard run yet
        if cm not in {k.removesuffix("-codex") for k in hrows}:
            hrows[cm] = {"runtime": c["runtime"], "avg_score": None, "pass_at_1": None, "pass_at_1_ci": [], "pass_hat_k": None,
                         "median_gap": None, "tool_calls": 0, "n_runs": 0, "n_tasks": 0, "safety_violations": 0,
                         "hallucinated_codes": 0, "tokens_in": 0, "tokens_out": 0, "seconds": 0, "rubric": {},
                         "radar": c["radar"], "by_task": {}, "by_category": {}, "pending": True}
    for m, h in hrows.items():
        c = crows.get(m.removesuffix("-codex"))
        overall = round(w_hard * h["avg_score"] + (1 - w_hard) * c["avg_score"], 1) if (c and h["avg_score"] is not None) else None
        rows.append({"model": m, "runtime": h["runtime"], "overall": overall,
                     "avg_score": h["avg_score"], "pass_at_1": h["pass_at_1"], "pass_at_1_ci": h["pass_at_1_ci"],
                     "pass_hat_k": h["pass_hat_k"], "median_gap": h["median_gap"], "tool_calls": h["tool_calls"],
                     "n_runs": h["n_runs"], "n_tasks": h["n_tasks"], "safety_violations": h["safety_violations"],
                     "hallucinated_codes": h["hallucinated_codes"], "tokens_in": h["tokens_in"], "tokens_out": h["tokens_out"],
                     "seconds": h["seconds"], "rubric": h["rubric"], "radar": h["radar"], "by_task": h["by_task"],
                     "by_category": h["by_category"],
                     "core": ({k: c[k] for k in ("avg_score", "pass_at_1", "pass_at_1_ci", "n_tasks", "rubric", "by_category")}
                              | {"model": c["model"], "by_task": c["by_task"]}) if c else None})
    rows.sort(key=lambda r: (r["overall"] is None, -(r["overall"] or 0), -((r["core"] or {}).get("avg_score") or 0)))
    board = {"schema_version": "1.1", "headline": "McBench-Hard v1.1", "mcp_mode": "offline", "is_mock": False,
             "task_set": "hard-v1.1 + v1.0", "core_split": core_split, "weights": {"hard": w_hard, "core": 1 - w_hard},
             "rows": rows, "note": note}
    dst = Path(web_dir, "data")
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "traces").mkdir(parents=True)
    (dst / "core" / "traces").mkdir(parents=True)
    for p in Path(hard_dir, "traces").glob("*.json"):
        shutil.copy(p, dst / "traces" / p.name)
    for p in Path(core_dir, "traces").glob("*.json"):
        if p.stem.split("__")[1] in core_ids:
            shutil.copy(p, dst / "core" / "traces" / p.name)
    Path(dst, "leaderboard.json").write_text(json.dumps(board, ensure_ascii=False, indent=1), "utf-8")
    Path(hard_dir, "combined_leaderboard.json").write_text(json.dumps(board, ensure_ascii=False, indent=1), "utf-8")
    return board
