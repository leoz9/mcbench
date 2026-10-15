"""Run one submission on the OFFLINE frozen snapshot (subprocess entry point).

Usage: python -m app.evalrun <spec.json> <out_dir>
The API key (if any) arrives ONLY via env MCBENCH_SUBMIT_KEY; spec.json never contains it.
"""
import json
import os
import sys
from pathlib import Path

from mcbench.cli import save_trace
from mcbench.demo_agents import DEMO_AGENTS, ScriptedAgent
from mcbench.env import McBenchEnv, make_mcp
from mcbench.harness import run_episode
from mcbench.metrics import aggregate
from mcbench.tasks import get_tasks


def make_agent(spec):
    p = spec["provider"]
    if p == "scripted":
        return ScriptedAgent(DEMO_AGENTS[spec["model"]], runtime="社区提交 · 脚本代理（非大模型）")
    if p == "anthropic":
        from mcbench.llm import AnthropicCompatChat
        return AnthropicCompatChat(spec["model"], spec["base_url"], "MCBENCH_SUBMIT_KEY", spec.get("temperature", 0.0))
    from mcbench.llm import OpenAICompatChat
    return OpenAICompatChat(spec["model"], spec["base_url"], "MCBENCH_SUBMIT_KEY", spec.get("temperature", 0.0))


def run_set(spec, task_set, split, out, limit):
    tasks = get_tasks(task_set, split)
    if limit:
        tasks = tasks[:limit]
    trs = []
    for t in tasks:
        env = McBenchEnv(mode="offline", task_set=task_set, mcp=make_mcp("offline"), max_steps=int(os.environ.get("EVAL_MAX_STEPS", 150)))
        tr = run_episode(make_agent(spec), spec["name"], t, env)
        tr["runtime"] = f"社区提交 · {spec['provider']} · {spec['model']}"
        if not trs and not tr.get("tool_calls"):  # preflight: endpoint unreachable / bad key → fail fast, don't publish zeros
            errs = [e["text"] for e in tr.get("events", []) if e.get("type") == "error"]
            if errs:
                sys.exit(f"endpoint error: {errs[0][:200]}")
        save_trace(out, tr)
        trs.append(tr)
        print(f"{task_set} {t['id']} score={tr['score']}", flush=True)
    return aggregate(trs)[0]


def main():
    spec = json.loads(Path(sys.argv[1]).read_text("utf-8"))
    out = Path(sys.argv[2])
    limit = int(os.environ.get("EVAL_LIMIT", 0))
    h = run_set(spec, os.environ.get("EVAL_HARD_SET", "hard-v1.1"), os.environ.get("EVAL_HARD_SPLIT", "test"), out / "hard", limit)
    c = run_set(spec, os.environ.get("EVAL_CORE_SET", "v1.0"), "test", out / "core", limit)
    w = float(os.environ.get("EVAL_W_HARD", 0.6))
    row = {k: h.get(k) for k in ("avg_score", "pass_at_1", "pass_at_1_ci", "pass_hat_k", "median_gap", "tool_calls", "n_runs",
                                  "n_tasks", "safety_violations", "hallucinated_codes", "tokens_in", "tokens_out", "seconds",
                                  "rubric", "radar", "by_task", "by_category")}
    row.update(model=spec["name"], runtime=h.get("runtime") or spec["provider"],
               overall=round(w * h["avg_score"] + (1 - w) * c["avg_score"], 1),
               core={k: c.get(k) for k in ("avg_score", "pass_at_1", "pass_at_1_ci", "n_tasks", "rubric", "by_category", "by_task")} | {"model": spec["name"]})
    (out / "row.json").write_text(json.dumps(row, ensure_ascii=False), "utf-8")


if __name__ == "__main__":
    main()
