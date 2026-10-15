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
