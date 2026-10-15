"""Programmatic verifier: recomputes price (calculate-price) and nutrition
(list-nutrition-foods + query-meal-detail default combo components) from MCP data —
never trusts the agent's own numbers. Works on both live and mock (same shapes)."""
from . import mcd

BASE = {"orderType": 1, "beType": 1}


class Catalog:
    """Caches menu / nutrition / combo details per store for verification."""

    def __init__(self, mcp, store):
        self.mcp, self.store = mcp, store
        self.menu = mcd.menu(mcp.call_tool("query-meals", {"storeCode": store, **BASE}))
        self.nut = mcd.nutrition(mcp.call_tool("list-nutrition-foods", {}))
        self._det = {}

    def detail(self, code):
        if code not in self._det:
            self._det[code] = mcd.detail(self.mcp.call_tool("query-meal-detail", {"storeCode": self.store, **BASE, "code": code}))
        return self._det[code]

    def leaves(self, item, fallback_name):
        """-> list of (leaf_name, qty_per_unit). Combos expand to default (or chosen) round items."""
        det = self.detail(item["productCode"])
        if not det.get("rounds"):
            return [(fallback_name or det.get("name"), 1)]
        chosen = {}
        for r in item.get("roundList") or []:
            for ci in r.get("comboItemList") or []:
                chosen.setdefault(str(r.get("round")), []).append(ci)
        out = []
        for r in det["rounds"]:
            sel = chosen.get(str(r["id"]))
            if sel:
                names = {c["code"]: c["name"] for c in r["choices"]}
                out += [(names.get(ci.get("code"), ci.get("code")), ci.get("quantity", 1)) for ci in sel]
            else:
                d = next((c for c in r["choices"] if c.get("isDefault") == 1), r["choices"][0] if r["choices"] else None)
                if d:
                    out.append((d["name"], r.get("quantity") or 1))
        return out


def verify(task, submission, mcp, catalog_cache=None):
    res = {"task": task["id"], "valid": False, "checks": {}, "errors": []}
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
        res["errors"].append(f"calculate-price rejected order (invalid/hallucinated items?): {q.get('error')}")
        return res
    names = {l["productCode"]: l["productName"] for l in q["lines"]}
    kinds, kcal, protein, unknown, spicy_b, nonspicy_b, all_names = {}, 0.0, 0.0, [], 0, 0, []
    drinks_ok = True
    for it in clean:
        parent = cat.menu.get(it["productCode"], {})
        parent_txt = (parent.get("name") or names.get(it["productCode"]) or "") + " ".join(parent.get("tags") or [])
        for leaf, per in cat.leaves(it, names.get(it["productCode"])):
            n = per * it["quantity"]
            k = mcd.kind(leaf)
            kinds[k] = kinds.get(k, 0) + n
            all_names.append(leaf)
            nut = mcd.match_nutrition(leaf, cat.nut)
            if nut and nut.get("kcal") is not None:
                kcal += nut["kcal"] * n
                protein += (nut.get("protein") or 0) * n
            else:
                unknown.append(leaf)
            spicy = bool(mcd.SPICY.search(leaf) or mcd.SPICY.search(parent_txt) and k == "汉堡")
            if k == "汉堡":
                spicy_b += n if spicy else 0
                nonspicy_b += 0 if spicy else n
            if k == "饮品" and not mcd.SUGAR_FREE.search(leaf):
                drinks_ok = False
            if spicy:
                res.setdefault("spicy_items", []).append(leaf)
    con, ch = task["constraints"], res["checks"]
    payable = q["payable"]
    if "max_payable" in con:
        ch["budget"] = payable <= con["max_payable"] + 1e-9
    if "max_kcal" in con:
        ch["kcal"] = not unknown and kcal <= con["max_kcal"]
    if "min_protein" in con:
        ch["protein"] = not unknown and protein >= con["min_protein"]
    for k, n in con.get("min_kind", {}).items():
        ch[f"count_{k}"] = kinds.get(k, 0) >= n
    if con.get("sugar_free_drinks"):
        ch["sugar_free"] = drinks_ok
    if con.get("no_spicy"):
        ch["no_spicy"] = not res.get("spicy_items")
    if "min_non_spicy_burgers" in con:
        ch["non_spicy"] = nonspicy_b >= con["min_non_spicy_burgers"]
    if "must_include_name" in con:
        ch["must_include"] = any(con["must_include_name"] in n for n in all_names)
    if con.get("use_coupon"):
        avail = mcd.coupons(mcp.call_tool("query-store-coupons", {"storeCode": store, **BASE}))
        ch["coupon"] = (not avail) or (q["discount"] > 0 and any(i.get("couponCode") or i.get("couponId") for i in clean))
    claimed = submission.get("claimedPayable")
    try:
        honest = claimed is not None and abs(float(claimed) - payable) < 0.01
    except (TypeError, ValueError):
        honest = False
    res.update(valid=True, payable=payable, subtotal=q["subtotal"], discount=q["discount"], kcal=round(kcal, 1),
               protein=round(protein, 1), nutrition_unknown=unknown, kinds=kinds, claimed=claimed, honest=honest,
               lines=q["lines"], passed=all(ch.values()))
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
        s += 5.0 * min(1.0, 8 / max(1, r.get("tool_calls", 1)))
        r["score"] = round(s, 1)
    return results
