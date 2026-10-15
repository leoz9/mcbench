"""Programmatic verifier: recomputes price (calculate-price) and nutrition
(list-nutrition-foods) from MCP data — never trusts the agent's own numbers."""


def build_catalog(mcp, store):
    meals = mcp.call_tool("query-meals", {"storeCode": store}).get("meals", [])
    nut = {f["code"]: f for f in mcp.call_tool("list-nutrition-foods", {}).get("foods", [])}
    cat = {}
    for m in meals:
        entry = {"name": m["name"], "category": m["category"], "tags": m.get("tags", []), "components": []}
        if m["category"] == "套餐":
            d = mcp.call_tool("query-meal-detail", {"storeCode": store, "code": m["code"]})
            entry["components"] = d.get("components", [])
        entry["nutrition"] = nut.get(m["code"])
        cat[m["code"]] = entry
    return cat


def _expand(cat, items):
    """Yield (category, tags, qty) for every leaf item (combos expanded)."""
    for it in items:
        e, q = cat[it["productCode"]], int(it["quantity"])
        if e["components"]:
            for c in e["components"]:
                yield c["category"], c.get("tags", []) + e["tags"], q
        else:
            yield e["category"], e["tags"], q


def verify(task, submission, mcp):
    res = {"task": task["id"], "valid": False, "checks": {}, "errors": []}
    if not submission:
        res["errors"].append("no submit_order call")
        return res
    store, items = submission.get("storeCode"), submission.get("items") or []
    try:
        cat = build_catalog(mcp, store)
    except Exception as e:  # noqa
        res["errors"].append(f"catalog error: {e}")
        return res
    unknown = [i.get("productCode") for i in items if i.get("productCode") not in cat]
    if not items or unknown:
        res["errors"].append(f"empty or hallucinated product codes: {unknown}")
        return res
    quote = mcp.call_tool("calculate-price", {"storeCode": store, "items": items,
                                              **({"couponCode": submission["couponCode"]} if submission.get("couponCode") else {})})
    if not quote.get("success", True) or "payable" not in quote:
        res["errors"].append(f"calculate-price failed: {quote.get('error')}")
        return res
    payable = quote["payable"]
    kcal = protein = 0.0
    for it in items:
        n = cat[it["productCode"]]["nutrition"] or {}
        kcal += n.get("kcal", 0) * it["quantity"]
        protein += n.get("protein", 0) * it["quantity"]
    counts = {}
    for c, tags, q in _expand(cat, items):
        counts[c] = counts.get(c, 0) + q
    con, ch = task["constraints"], res["checks"]
    if "max_payable" in con:
        ch["budget"] = payable <= con["max_payable"] + 1e-9
    if "max_kcal" in con:
        ch["kcal"] = kcal <= con["max_kcal"]
    if "min_protein" in con:
        ch["protein"] = protein >= con["min_protein"]
    for c, n in con.get("min_category", {}).items():
        ch[f"count_{c}"] = counts.get(c, 0) >= n
    if "drink_tag" in con:
        ch["drink_tag"] = all(con["drink_tag"] in tags for c, tags, q in _expand(cat, items) if c == "饮品")
    if "no_tag" in con:
        ch["no_tag"] = not any(con["no_tag"] in tags for c, tags, q in _expand(cat, items))
    if "min_non_spicy_burgers" in con:
        ns = sum(q for c, tags, q in _expand(cat, items) if c == "汉堡" and "辣" not in tags)
        ch["non_spicy"] = ns >= con["min_non_spicy_burgers"]
    if "must_include" in con:
        have = {i["productCode"] for i in items}
        ch["must_include"] = all(x in have or any(cc["code"] == x for i in items for cc in cat[i["productCode"]]["components"])
                                 for x in con["must_include"])
    if "exact_items" in con:
        got = {}
        for i in items:
            got[i["productCode"]] = got.get(i["productCode"], 0) + i["quantity"]
        ch["exact_items"] = got == con["exact_items"]
    claimed = submission.get("claimedPayable")
    res.update(valid=True, payable=payable, subtotal=quote.get("subtotal"), discount=quote.get("discount"),
               kcal=round(kcal, 1), protein=round(protein, 1), claimed=claimed,
               honest=claimed is not None and abs(float(claimed) - payable) < 0.01,
               passed=all(ch.values()))
    return res


def score_runs(results):
    """results: list of dicts {model, task, verdict, tool_calls}. Adds 'score' (0-100).
    Objective score is relative to the best passing run on the same task."""
    from .tasks import TASK_BY_ID
    best = {}
    for r in results:
        v, t = r["verdict"], TASK_BY_ID[r["task"]]
        if v.get("passed"):
            val = v["kcal"] if t["objective"] == "max_kcal" else v["payable"]
            b = best.get(r["task"])
            best[r["task"]] = val if b is None else (max(b, val) if t["objective"] == "max_kcal" else min(b, val))
    for r in results:
        v, t = r["verdict"], TASK_BY_ID[r["task"]]
        if not v.get("valid"):
            r["score"] = 0.0
            continue
        checks = v["checks"]
        s = 50.0 * sum(checks.values()) / max(1, len(checks))
        s += 15.0 if v.get("honest") else 0.0
        if v.get("passed") and r["task"] in best:
            val = v["kcal"] if t["objective"] == "max_kcal" else v["payable"]
            ratio = (val / best[r["task"]]) if t["objective"] == "max_kcal" else (best[r["task"]] / val if val else 1)
            s += 30.0 * min(1.0, ratio)
        s += 5.0 * min(1.0, 6 / max(1, r.get("tool_calls", 1)))
        r["score"] = round(s, 1)
    return results
