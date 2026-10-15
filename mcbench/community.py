"""Community task contribution helpers: template + validation against frozen snapshot."""
import json
from pathlib import Path

from .solver import snapshot_units, solve
from .tasks import load_task_set

REQUIRED = ("id", "category", "difficulty", "title", "prompt", "constraints", "objective", "dimensions", "author")
CATEGORIES = {"budget", "nutrition", "group", "coupon", "dietary", "multi_constraint", "clarification",
              "adversarial", "infeasible", "vision"}
DIFFS = {"easy", "medium", "hard"}
DIMS = {"tool_use", "constraints", "cost_opt", "nutrition", "safety", "clarification", "infeasible", "efficiency", "multimodal"}
TEMPLATE = '''# McBench community task (YAML or JSON). See docs/contributing-tasks.md.
id: {id}
category: {category}          # one of: budget|nutrition|group|coupon|dietary|multi_constraint|clarification|adversarial|infeasible
difficulty: {difficulty}      # easy|medium|hard
title: "示例任务标题"
prompt: >
  到店自取（beType=1, orderType=1）；门店用 query-nearby-stores（searchType=2, city=上海, keyword=人民广场）。
  【在此写清自然语言需求；信息不足时可要求 Agent 用 ask_user。】
constraints:
  max_payable: 40
  min_kind: {{汉堡: 1, 饮品: 1}}
objective: min_payable          # or max_kcal
expected_outcome: order         # order | infeasible
dimensions: [tool_use, constraints, cost_opt]
author: "Your GitHub handle"
license: CC-BY-4.0
notes: ""
'''


def new_task(tid, category="budget", difficulty="medium"):
    Path("tasks/community").mkdir(parents=True, exist_ok=True)
    path = Path("tasks/community") / f"{tid}.yml"
    path.write_text(TEMPLATE.format(id=tid, category=category, difficulty=difficulty), "utf-8")
    return path


def _load(path):
    text = Path(path).read_text("utf-8")
    if path.suffix in (".yml", ".yaml"):
        try:
            import yaml
            return yaml.safe_load(text)
        except ImportError:
            # tiny YAML subset: only for our template fields
            raise SystemExit("请 pip install pyyaml，或提交 .json")
    return json.loads(text)


def validate_task(t, units=None):
    msgs = []
    for k in REQUIRED:
        if k not in t:
            msgs.append(f"missing field: {k}")
    if t.get("category") not in CATEGORIES:
        msgs.append(f"bad category: {t.get('category')}")
    if t.get("difficulty") not in DIFFS:
        msgs.append(f"bad difficulty: {t.get('difficulty')}")
    if not set(t.get("dimensions") or []) <= DIMS:
        msgs.append(f"unknown dimensions: {set(t.get('dimensions') or []) - DIMS}")
    if not isinstance(t.get("constraints"), dict):
        msgs.append("constraints must be an object")
        return False, msgs
    if units is None:
        _, units = snapshot_units()
    ref = solve({"constraints": t["constraints"], "objective": t.get("objective", "min_payable")}, units)
    want = t.get("expected_outcome", "order")
    if want == "order" and not ref["feasible"]:
        msgs.append("marked order but solver found no feasible solution on snapshot v1.0")
    if want == "infeasible" and ref["feasible"]:
        msgs.append(f"marked infeasible but solver found a solution (payable={ref.get('payable')})")
    if want == "infeasible" and not ref.get("exact", True):
        msgs.append("infeasible claim not proven (solver timed out)")
    return not msgs, msgs


def validate_path(path):
    root = Path(path)
    files = list(root.glob("*.yml")) + list(root.glob("*.yaml")) + list(root.glob("*.json")) if root.is_dir() else [root]
    if not files:
        return True, ["(no community tasks found)"]
    _, units = snapshot_units()
    ok_all, msgs = True, []
    for f in files:
        try:
            t = _load(f)
        except Exception as e:  # noqa
            ok_all = False; msgs.append(f"{f}: parse error: {e}"); continue
        ok, m = validate_task(t, units)
        ok_all = ok_all and ok
        msgs.append(f"{f}: {'OK' if ok else 'FAIL'} — " + ("; ".join(m) if m else "schema + solver check passed"))
    # uniqueness vs official set
    official = {t["id"] for t in load_task_set()["tasks"]}
    for f in files:
        try:
            t = _load(f)
            if t.get("id") in official:
                ok_all = False; msgs.append(f"{f}: id '{t['id']}' already in official set — pick a new id (e.g. community-<handle>-01)")
        except Exception:
            pass
    return ok_all, msgs
