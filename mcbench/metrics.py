"""Aggregate metrics: pass@1, pass^k, cost, latency, efficiency, CI, radar dimensions."""
import math
from collections import defaultdict

from .tasks import load_task_set
from .verifier import score_runs

DIMS = [
    ("tool_use", "工具调用", ["budget", "nutrition", "group", "coupon", "dietary", "multi_constraint"]),
    ("constraints", "约束满足", ["budget", "nutrition", "group", "coupon", "dietary", "multi_constraint", "clarification"]),
    ("cost_opt", "成本优化", ["budget", "coupon", "group"]),
    ("nutrition", "营养推理", ["nutrition"]),
    ("safety", "安全(零违规)", ["adversarial"]),
    ("clarification", "澄清追问", ["clarification"]),
    ("infeasible", "不可行识别", ["infeasible"]),
    ("efficiency", "调用效率", None),  # derived from tool_calls
    ("consistency", "一致性 pass^k", None),
]


def _wilson(s, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = s / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)


def _phk(by_task):
    """pass^k over the multi-run subset if any task has k>1, else over all tasks (k=1)."""
    multi = [t for t in by_task.values() if t["k"] > 1]
    pool = multi or list(by_task.values())
    return round(sum(1 for t in pool if t["pass_hat_k"]) / max(1, len(pool)), 3)


def aggregate(traces):
    """traces: list of McBench traces (possibly multiple runs per (model, task))."""
    by = defaultdict(list)
    for t in traces:
        by[(t["model"], t["task"])].append(t)
    # flatten to one representative per (model,task) for score_runs (uses best run for opt_ratio)
    flat = [{"model": m, "task": tid, "verdict": min(rs, key=lambda x: x.get("seed") or 0)["verdict"],  # score = first run (no best-of-k)
             "tool_calls": sum(r["tool_calls"] for r in rs) / len(rs),
             "safety_violations": sum(r.get("safety_violations", 0) for r in rs) / len(rs)}
            for (m, tid), rs in by.items()]
    score_runs(flat)
    score_map = {(r["model"], r["task"]): r["score"] for r in flat}

    meta = {}
    try:
        meta = {t["id"]: t for t in load_task_set()["tasks"]}
    except Exception:  # noqa
        pass
    models = {}
    for (m, tid), rs in by.items():
        md = models.setdefault(m, {"model": m, "runtime": rs[0].get("runtime"), "by_task": {},
                                   "by_cat": defaultdict(list), "scores": [], "passes": [],
                                   "tool_calls": 0, "seconds": 0.0, "tokens_in": 0, "tokens_out": 0,
                                   "safety": 0, "hallucinated": 0, "n_runs": 0, "unsafe_runs": 0})
        passes = [bool(r["verdict"].get("passed")) for r in rs]
        p1 = sum(passes) / len(passes)
        pk = 1.0 if all(passes) else 0.0
        md["by_task"][tid] = {"pass_at_1": round(p1, 3), "pass_hat_k": pk, "k": len(rs),
                              "score": score_map[(m, tid)],
                              "category": rs[0].get("category") or rs[0]["verdict"].get("category"),
                              "difficulty": rs[0].get("difficulty") or rs[0]["verdict"].get("difficulty"),
                              "author": (meta.get(tid) or {}).get("author"),
                              "dimensions": (meta.get(tid) or {}).get("dimensions")}
        md["by_cat"][md["by_task"][tid]["category"]].append(p1)
        md["scores"].append(score_map[(m, tid)])
        md["passes"].append(p1)
        for r in rs:
            md["tool_calls"] += r.get("tool_calls", 0)
            md["seconds"] += r.get("seconds", 0)
            u = r.get("usage") or {}
            md["tokens_in"] += u.get("prompt_tokens") or u.get("input_tokens") or 0
            md["tokens_out"] += u.get("completion_tokens") or u.get("output_tokens") or 0
            sv = r.get("safety_violations", 0) or r["verdict"].get("safety_violations", 0) or 0
            md["safety"] += sv
            md["unsafe_runs"] += 1 if sv else 0
            md["hallucinated"] += len(r["verdict"].get("hallucinated_codes") or [])
            md["n_runs"] += 1

    rows = []
    for m, md in models.items():
        n = len(md["passes"])
        p, lo, hi = _wilson(sum(md["passes"]), n)
        p_all = sum(md["passes"]) / max(1, n)
        radar = {}
        for key, label, cats in DIMS:
            if key == "efficiency":
                # calls-efficiency only counts on solved tasks (failing fast is not efficient)
                avg = md["tool_calls"] / max(1, md["n_runs"])
                radar[key] = {"label": label, "value": round(min(1.0, 8 / max(1, avg)) * p_all * 100, 1)}
            elif key == "consistency":
                multi = [t for t in md["by_task"].values() if t["k"] > 1]
                radar[key] = {"label": label, "value": round(100 * _phk(md["by_task"]), 1) if multi else None}
            elif key == "safety":
                radar[key] = {"label": label, "value": round(100 * (1 - md["unsafe_runs"] / max(1, md["n_runs"])), 1)}
            else:
                vals = [v for c in (cats or []) for v in md["by_cat"].get(c, [])]
                radar[key] = {"label": label, "value": round(100 * sum(vals) / len(vals), 1) if vals else None}
        rows.append({
            "model": m, "runtime": md["runtime"],
            "avg_score": round(sum(md["scores"]) / max(1, len(md["scores"])), 1),
            "pass_at_1": round(p, 3), "pass_at_1_ci": [round(lo, 3), round(hi, 3)],
            "pass_hat_k": _phk(md["by_task"]),
            "k": max(t["k"] for t in md["by_task"].values()),
            "k_tasks": sum(1 for t in md["by_task"].values() if t["k"] > 1) or n,
            "n_tasks": n, "n_runs": md["n_runs"],
            "tool_calls": md["tool_calls"], "seconds": round(md["seconds"], 1),
            "tokens_in": md["tokens_in"], "tokens_out": md["tokens_out"],
            "safety_violations": md["safety"], "hallucinated_codes": md["hallucinated"],
            "by_task": md["by_task"], "by_category": {c: round(sum(v) / len(v), 3) for c, v in md["by_cat"].items()},
            "radar": radar,
        })
    rows.sort(key=lambda r: (-r["avg_score"], -r["pass_at_1"]))
    return rows
