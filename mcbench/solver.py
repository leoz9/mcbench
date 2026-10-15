"""Reference solver on a frozen snapshot: exact branch-and-bound over units.

Used to (1) prove feasibility / infeasibility when generating tasks and (2) give
the reference optimum used for the objective sub-score. Offline only.
"""
import time

from . import mcd
from .mcp_client import MockMCP
from .units import default_leaves, evaluate, make_unit, unit_allowed

B = {"orderType": 1, "beType": 1}


def snapshot_units(version=None, store=None):
    m = MockMCP(version) if version else MockMCP()
    d = m.backend.d
    store = store or d["stores"][0]["storeCode"]
    menu = mcd.menu(m.call_tool("query-meals", {"storeCode": store, **B}))
    nut = mcd.nutrition(m.call_tool("list-nutrition-foods", {}))
    units = []
    for code, e in menu.items():
        det = mcd.detail(m.call_tool("query-meal-detail", {"storeCode": store, **B, "code": code}))
        units.append(make_unit(code, e["name"], e["price"], default_leaves(det, e["name"]), nut, e["tags"]))
    for cp in mcd.coupons(m.call_tool("query-store-coupons", {"storeCode": store, **B})):
        pc = cp["products"][0]["productCode"]
        q = mcd.quote(m.call_tool("calculate-price", {"storeCode": store, **B, "items": [
            {"productCode": pc, "quantity": 1, "couponId": cp["couponId"], "couponCode": cp["couponCode"]}]}))
        det = mcd.detail(m.call_tool("query-meal-detail", {"storeCode": store, **B, "code": pc}))
        if q.get("success"):
            units.append(make_unit(pc, cp["title"], q["payable"], default_leaves(det, cp["title"]), nut,
                                   coupon={"couponId": cp["couponId"], "couponCode": cp["couponCode"]}))
    return store, units


def _dominance(units, c):
    """Keep the cheapest few units per 'signature' to shrink the search."""
    nut = any(k in c for k in ("max_kcal", "min_kcal", "min_protein", "max_sodium"))
    keep = 6 if nut else 1
    groups = {}
    for u in units:
        sig = (tuple(sorted(u.kinds.items())), u.nonspicy_burgers, bool(u.coupon),
               bool(c.get("must_include_name") and any(c["must_include_name"] in n for n, _ in u.leaves + [(u.name, 1)])))
        groups.setdefault(sig, []).append(u)
    out = []
    for g in groups.values():
        g.sort(key=lambda u: (u.price, -u.protein if "min_protein" in c else u.kcal))
        out += g[:keep]
        if "min_protein" in c:  # also keep protein-dense ones
            out += sorted(g, key=lambda u: -u.protein)[:2]
    seen, res = set(), []
    for u in out:
        if id(u) not in seen:
            seen.add(id(u)); res.append(u)
    return res


def solve(task, units, time_limit=20.0, max_units=None):
    """Return {"feasible": bool, "payable": .., "kcal": .., "items": [...], "exact": bool}."""
    c = task["constraints"]
    obj = task.get("objective", "min_payable")
    cand = [u for u in units if unit_allowed(u, c)]
    cand = [u for u in cand if any(u.kinds.get(k) for k in (c.get("min_kind") or {})) or u.coupon
            or (c.get("must_include_name") and any(c["must_include_name"] in n for n, _ in u.leaves))
            or "min_protein" in c or obj == "max_kcal"]
    cand = _dominance(cand, c)
    cand.sort(key=lambda u: u.price)
    need = dict(c.get("min_kind") or {})
    cap = max_units or min(sum(need.values()) + 3, 18)
    best = {"val": None, "sol": None}
    t0 = time.time()
    exact = [True]

    def better(val):
        return best["val"] is None or (val > best["val"] + 1e-9 if obj == "max_kcal" else val < best["val"] - 1e-9)

    def dfs(i, chosen, price):
        if time.time() - t0 > time_limit:
            exact[0] = False
            return
        if "max_payable" in c and price > c["max_payable"] + 1e-9:
            return
        if obj != "max_kcal" and best["val"] is not None and price >= best["val"] - 1e-9:
            return
        if chosen:
            ch, agg = evaluate(chosen, c, round(price, 2))
            if all(ch.values()):
                val = agg["kcal"] if obj == "max_kcal" else round(price, 2)
                if better(val):
                    best["val"], best["sol"] = val, list(chosen)
                if obj != "max_kcal":
                    return
            if "max_kcal" in c and agg["kcal"] > c["max_kcal"]:
                return
        if len(chosen) >= cap:
            return
        # remaining needs
        rem = dict(need)
        for u in chosen:
            for k, v in u.kinds.items():
                if k in rem:
                    rem[k] -= v
        for j in range(i, len(cand)):
            u = cand[j]
            useful = any(rem.get(k, 0) > 0 and u.kinds.get(k) for k in rem) or obj == "max_kcal" or \
                (u.coupon and c.get("use_coupon")) or "min_protein" in c or \
                (c.get("must_include_name") and any(c["must_include_name"] in n for n, _ in u.leaves))
            if not useful:
                continue
            chosen.append(u)
            dfs(j, chosen, price + u.price)
            chosen.pop()

    dfs(0, [], 0.0)
    if best["sol"] is None:
        return {"feasible": False, "exact": exact[0]}
    ch, agg = evaluate(best["sol"], c, sum(u.price for u in best["sol"]))
    items = {}
    for u in best["sol"]:
        items.setdefault(u.code, {"productCode": u.code, "quantity": 0, "name": u.name})["quantity"] += 1
    return {"feasible": True, "exact": exact[0], "payable": round(sum(u.price for u in best["sol"]), 2),
            "kcal": round(agg["kcal"], 1), "protein": round(agg["protein"], 1), "items": list(items.values())}
