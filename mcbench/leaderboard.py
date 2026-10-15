import json
import shutil
from pathlib import Path

from .verifier import score_runs


def load_traces(run_dir):
    return [json.loads(p.read_text("utf-8")) for p in sorted(Path(run_dir).glob("traces/*.json"))]


def build(run_dir):
    traces = load_traces(run_dir)
    results = [{"model": t["model"], "task": t["task"], "verdict": t["verdict"], "tool_calls": t["tool_calls"],
                "file": f"traces/{t['model']}__{t['task']}.json"} for t in traces]
    score_runs(results)
    models = {}
    for r in results:
        m = models.setdefault(r["model"], {"model": r["model"], "scores": {}, "passed": 0, "honest": 0,
                                           "blocked_attempts": 0, "tool_calls": 0, "payable_total": 0.0})
        m["scores"][r["task"]] = r["score"]
        m["passed"] += 1 if r["verdict"].get("passed") else 0
        m["honest"] += 1 if r["verdict"].get("honest") else 0
        m["tool_calls"] += r["tool_calls"]
    for t in traces:
        models[t["model"]]["blocked_attempts"] += sum(1 for e in t["events"] if e["type"] == "tool_result"
                                                      and isinstance(e["result"], dict) and e["result"].get("blocked"))
    rows = []
    for m in models.values():
        m["avg_score"] = round(sum(m["scores"].values()) / max(1, len(m["scores"])), 1)
        m["n_tasks"] = len(m["scores"])
        rows.append(m)
    rows.sort(key=lambda m: -m["avg_score"])
    mode = traces[0]["mcp_mode"] if traces else "?"
    board = {"mcp_mode": mode, "is_mock": mode == "mock", "rows": rows, "runs": results,
             "tasks": sorted({r["task"] for r in results})}
    Path(run_dir, "leaderboard.json").write_text(json.dumps(board, ensure_ascii=False, indent=1), "utf-8")
    return board


def print_board(board):
    if board["is_mock"]:
        print("⚠️  MOCK 模式：模拟 MCP 数据 + 脚本示例 Agent，仅用于演示流程，非真实模型成绩。")
    tasks = board["tasks"]
    print(f"\n{'#':<3}{'Agent':<18}{'均分':>6}{'通过':>6}{'诚实':>6}{'调用':>6}{'拦截':>6}  " + " ".join(f"{t[:10]:>11}" for t in tasks))
    for i, r in enumerate(board["rows"], 1):
        print(f"{i:<3}{r['model']:<18}{r['avg_score']:>6}{r['passed']:>4}/{r['n_tasks']}{r['honest']:>5}"
              f"{r['tool_calls']:>6}{r['blocked_attempts']:>6}  " + " ".join(f"{r['scores'].get(t, '-'):>11}" for t in tasks))
    print()


def export_web(run_dir, web_dir):
    dst = Path(web_dir, "data")
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "traces").mkdir(parents=True)
    shutil.copy(Path(run_dir, "leaderboard.json"), dst / "leaderboard.json")
    for p in Path(run_dir, "traces").glob("*.json"):
        shutil.copy(p, dst / "traces" / p.name)
    return dst
