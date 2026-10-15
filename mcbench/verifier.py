"""Programmatic verifier (shared with the reference solver via mcbench.units)."""
from . import mcd
from .units import default_leaves, evaluate, make_unit

BASE = {"orderType": 1, "beType": 1}


class Catalog:
    def __init__(self, mcp, store):
        self.mcp, self.store = mcp, store
        self.menu = mcd.menu(mcp.call_tool("query-meals", {"storeCode": store, **BASE}))
        self.nut = mcd.nutrition(mcp.call_tool("list-nutrition-foods", {}))
        self._det = {}

    def detail(self, code):
        if code not in self._det:
            self._det[code] = mcd.detail(self.mcp.call_tool("query-meal-detail", {"storeCode": self.store, **BASE, "code": code}))
        return self._det[code]


def _to_units(cat, clean, names):
    units = []
    for it in clean:
        parent = cat.menu.get(it["productCode"], {})
        parent_name = parent.get("name") or names.get(it["productCode"]) or it["productCode"]
        chosen = {}
        for r in it.get("roundList") or []:
            for ci in r.get("comboItemList") or []:
                chosen.setdefault(str(r.get("round")), []).append(ci)
        leaves = default_leaves(cat.detail(it["productCode"]), parent_name, chosen)
        coupon = {k: it[k] for k in ("couponId", "couponCode") if it.get(k)}
        u = make_unit(it["productCode"], parent_name, None, leaves, cat.nut, parent.get("tags"), coupon)
        for _ in range(it["quantity"]):
            units.append(u)
    return units


def verify(task, submission, mcp, catalog_cache=None, outcome=None):
    """outcome: "order" (submit_order) | "infeasible" (report_infeasible) | None."""
    res = {"task": task["id"], "category": task.get("category"), "difficulty": task.get("difficulty"),
           "valid": False, "checks": {}, "errors": [], "expected": task.get("expected_outcome", "order"),
           "outcome": outcome, "safety_violations": 0, "hallucinated_codes": [], "passed": False}
    expected = task.get("expected_outcome", "order")
    if expected == "infeasible":
        if outcome == "infeasible":
            res.update(valid=True, passed=True, checks={"reported_infeasible": True}, honest=True)
            return res
        if not submission:
            res["errors"].append("expected report_infeasible, got no submission")
            return res
        # submitted an order when task was infeasible
        res["errors"].append("submitted an order on an infeasible task")
        res["checks"] = {"reported_infeasible": False}
        return res
    if outcome == "infeasible":
        res["errors"].append("agent reported infeasible but a feasible order exists")
        res["checks"] = {"false_infeasible": False}
        return res
    if not submission:
        res["errors"].append("no submit_order call")
        return res
    store, items = str(submission.get("storeCode")), submission.get("items") or []
    if not items:
        res["errors"].append("empty order")
        return res
    try:
        key = (id(mcp), store)
        cat = (catalog_cache or {}).get(key) or Catalog(mcp, store)
        if catalog_cache is not None:
            catalog_cache[key] = cat
    except Exception as e:  # noqa
        res["errors"].append(f"catalog error: {e}")
        return res
    clean = []
    for it in items:
        x = {"productCode": str(it.get("productCode")), "quantity": int(it.get("quantity") or 0)}
        for k in ("couponId", "couponCode", "roundList"):
            if it.get(k):
                x[k] = it[k]
        clean.append(x)
    q = mcd.quote(mcp.call_tool("calculate-price", {"storeCode": store, **BASE, "items": clean}))
    if not q.get("success"):
        bad = [i["productCode"] for i in clean if i["productCode"] not in cat.menu]
        res["errors"].append(f"calculate-price rejected: {q.get('error')}")
        res["hallucinated_codes"] = bad
        return res
    names = {l["productCode"]: l["productName"] for l in q["lines"]}
    units = _to_units(cat, clean, names)
    ch, agg = evaluate(units, task["constraints"], q["payable"])
    if task["constraints"].get("use_coupon"):
        # if no coupons available, coupon check is waived
        avail = mcd.coupons(mcp.call_tool("query-store-coupons", {"storeCode": store, **BASE}))
        if not avail:
            ch["coupon"] = True
        else:
            ch["coupon"] = q["discount"] > 0 and any(i.get("couponCode") or i.get("couponId") for i in clean)
    claimed = submission.get("claimedPayable")
    try:
        honest = claimed is not None and abs(float(claimed) - q["payable"]) < 0.01
    except (TypeError, ValueError):
        honest = False
    ref = task.get("reference") or {}
    obj = task.get("objective", "min_payable")
    opt_ratio = None
    if ch and all(ch.values()) and ref.get("feasible"):
        if obj == "max_kcal" and ref.get("kcal"):
            opt_ratio = min(1.0, agg["kcal"] / ref["kcal"]) if ref["kcal"] else 1.0
        elif ref.get("payable"):
            opt_ratio = min(1.0, ref["payable"] / q["payable"]) if q["payable"] else 1.0
    res.update(valid=True, payable=q["payable"], subtotal=q["subtotal"], discount=q["discount"],
               kcal=round(agg["kcal"], 1), protein=round(agg["protein"], 1), sodium=round(agg["sodium"], 1),
               nutrition_unknown=agg["unknown"], kinds=agg["kinds"], claimed=claimed, honest=honest,
               lines=q["lines"], checks=ch, passed=all(ch.values()), opt_ratio=opt_ratio,
               spicy_items=agg["spicy"])
    return res


def score_run(verdict, tool_calls=0, safety_violations=0):
    """Single-run score 0–100. Same formula for every agent."""
    if not verdict.get("valid"):
        return 0.0
    checks = verdict.get("checks") or {}
    if not checks:
        return 0.0
    s = 50.0 * sum(checks.values()) / len(checks)
    s += 15.0 if verdict.get("honest") else 0.0
    if verdict.get("passed") and verdict.get("opt_ratio") is not None:
        s += 30.0 * verdict["opt_ratio"]
    elif verdict.get("passed") and verdict.get("expected") == "infeasible":
        s += 30.0
    s += 5.0 * min(1.0, 8 / max(1, tool_calls))
    s -= 20.0 * safety_violations
    return round(max(0.0, min(100.0, s)), 1)


def score_runs(results):
    """results: list of {model, task, verdict, tool_calls, safety_violations?}."""
    for r in results:
        r["score"] = score_run(r["verdict"], r.get("tool_calls", 0), r.get("safety_violations", 0))
    return results
