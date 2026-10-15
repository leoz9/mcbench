"""Aggregate metrics (v1.1): every trace is (re)graded with mcbench.rubric, then
pass@1 (+Wilson CI), pass^k, per-dimension rubric means, category pass rates and radar."""
import math
from collections import defaultdict

from .rubric import WEIGHTS, effective_task, grade
from .tasks import load_task_set

CAT_DIMS = {  # radar dims derived from category pass rates
    "nutrition": ("营养推理", ["nutrition", "knapsack"]),
    "infeasible": ("不可行识别", ["infeasible", "boundary"]),
    "robustness": ("抗注入/干扰", ["adversarial", "injection", "distractor"]),
    "replanning": ("多轮改需求", ["followup", "clarification", "hidden"]),
}
RUBRIC_LABEL = {"constraints": "约束满足", "optimality": "最优性", "honesty": "价格诚实", "safety": "安全",
                "efficiency": "调用效率", "clarification": "澄清/不臆断"}

_META = {}


def task_meta(task_set, tid):
    if task_set not in _META:
        try:
            _META[task_set] = {t["id"]: t for t in load_task_set(task_set)["tasks"]}
        except Exception:  # noqa
            _META[task_set] = {}
    return _META[task_set].get(tid)


def _wilson(s, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = s / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)


def regrade(tr):
    task = task_meta(tr.get("task_set") or "v1.0", tr["task"])
    if not task:
        return tr.get("score", 0), bool((tr.get("verdict") or {}).get("passed")), {}
    g = grade(tr, effective_task(task, tr))
    return g["score"], g["passed"], g


def aggregate(traces):
    by = defaultdict(list)
    for t in traces:
        by[(t["model"], t["task"])].append(t)
    models = {}
    for (m, tid), rs in sorted(by.items()):
        rs = sorted(rs, key=lambda x: x.get("seed") or 0)
        md = models.setdefault(m, {"runtime": rs[0].get("runtime"), "by_task": {}, "by_cat": defaultdict(list),
                                   "scores": [], "passes": [], "dims": defaultdict(list), "tool_calls": 0,
                                   "seconds": 0.0, "tokens_in": 0, "tokens_out": 0, "safety": 0, "unsafe_runs": 0,
                                   "hallucinated": 0, "n_runs": 0, "gaps": []})
        gs = [regrade(r) for r in rs]
        passes = [g[1] for g in gs]
        task = task_meta(rs[0].get("task_set") or "v1.0", tid) or {}
        cat = rs[0].get("category") or task.get("category")
        p1 = sum(passes) / len(passes)
        md["by_task"][tid] = {"pass_at_1": round(p1, 3), "pass_hat_k": 1.0 if all(passes) else 0.0, "k": len(rs),
                              "score": gs[0][0], "category": cat, "difficulty": task.get("difficulty"),
                              "author": task.get("author"), "dimensions": task.get("dimensions"),
                              "notes": (gs[0][2] or {}).get("notes")}
        md["by_cat"][cat].append(p1)
        md["scores"].append(gs[0][0])
        md["passes"].append(p1)
        for (sc, ok, g), r in zip(gs, rs):
            for k, v in (g.get("dims") or {}).items():
                md["dims"][k].append(v)
            if g.get("gap") is not None:
                md["gaps"].append(g["gap"])
            md["tool_calls"] += r.get("tool_calls", 0)
            md["seconds"] += r.get("seconds", 0)
            u = r.get("usage") or {}
            md["tokens_in"] += u.get("prompt_tokens") or u.get("input_tokens") or 0
            md["tokens_out"] += u.get("completion_tokens") or u.get("output_tokens") or 0
            sv = r.get("safety_violations", 0) or 0
            md["safety"] += sv
            md["unsafe_runs"] += 1 if sv else 0
            md["hallucinated"] += len((r.get("verdict") or {}).get("hallucinated_codes") or [])
            md["n_runs"] += 1
    rows = []
    for m, md in models.items():
        n = len(md["passes"])
        p, lo, hi = _wilson(sum(md["passes"]), n)
        multi = [t for t in md["by_task"].values() if t["k"] > 1]
        pool = multi or list(md["by_task"].values())
        radar = {k: {"label": RUBRIC_LABEL[k], "value": round(100 * sum(v) / len(v), 1)} for k, v in md["dims"].items() if v}
        for key, (label, cats) in CAT_DIMS.items():
            vals = [x for c in cats for x in md["by_cat"].get(c, [])]
            radar[key] = {"label": label, "value": round(100 * sum(vals) / len(vals), 1) if vals else None}
        radar["consistency"] = {"label": "一致性 pass^k",
                                "value": round(100 * sum(t["pass_hat_k"] for t in multi) / len(multi), 1) if multi else None}
        rows.append({
            "model": m, "runtime": md["runtime"],
            "avg_score": round(sum(md["scores"]) / max(1, n), 1),
            "pass_at_1": round(p, 3), "pass_at_1_ci": [round(lo, 3), round(hi, 3)],
            "pass_hat_k": round(sum(t["pass_hat_k"] for t in pool) / max(1, len(pool)), 3),
            "k": max(t["k"] for t in md["by_task"].values()), "k_tasks": len(multi) or n,
            "n_tasks": n, "n_runs": md["n_runs"], "tool_calls": md["tool_calls"], "seconds": round(md["seconds"], 1),
            "tokens_in": md["tokens_in"], "tokens_out": md["tokens_out"],
            "safety_violations": md["safety"], "hallucinated_codes": md["hallucinated"],
            "median_gap": round(sorted(md["gaps"])[len(md["gaps"]) // 2], 4) if md["gaps"] else None,
            "rubric": {k: round(sum(v) / len(v), 3) for k, v in md["dims"].items() if v},
            "by_task": md["by_task"], "by_category": {c: round(sum(v) / len(v), 3) for c, v in md["by_cat"].items()},
            "radar": radar,
        })
    rows.sort(key=lambda r: (-r["avg_score"], -r["pass_at_1"]))
    return rows


__all__ = ["aggregate", "regrade", "WEIGHTS"]
