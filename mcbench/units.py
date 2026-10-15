"""Shared order semantics used by BOTH the verifier and the reference solver.

A *unit* is one purchasable line (single item, set meal, or coupon product) with
its expanded leaves (default combo components), kinds (汉堡/饮品/小食/其他),
nutrition and dietary flags. `evaluate()` turns a multiset of units into the
constraint checks defined in docs/scoring.md.
"""
from dataclasses import dataclass, field

from . import mcd

CAFFEINE = ("咖啡", "美式", "拿铁", "奶铁", "浓缩", "卡布奇诺", "玛奇朵", "红茶", "阿芙佳朵")


@dataclass
class Unit:
    code: str
    name: str
    price: float | None
    leaves: list = field(default_factory=list)   # [(leaf_name, qty)]
    kinds: dict = field(default_factory=dict)
    kcal: float = 0.0
    protein: float = 0.0
    sodium: float = 0.0
    unknown: list = field(default_factory=list)
    spicy_burgers: int = 0
    nonspicy_burgers: int = 0
    spicy_leaves: list = field(default_factory=list)
    sugary_drinks: list = field(default_factory=list)
    coupon: dict = field(default_factory=dict)    # {"couponId","couponCode"} for coupon products

    def item(self):
        return {"productCode": self.code, "quantity": 1, **self.coupon}


def make_unit(code, name, price, leaves, nut, parent_tags=(), coupon=None):
    u = Unit(code=code, name=name, price=price, leaves=list(leaves), coupon=dict(coupon or {}))
    parent_txt = (name or "") + " ".join(parent_tags or [])
    for leaf, q in leaves:
        k = mcd.kind(leaf)
        u.kinds[k] = u.kinds.get(k, 0) + q
        n = mcd.match_nutrition(leaf, nut)
        if n and n.get("kcal") is not None:
            u.kcal += n["kcal"] * q
            u.protein += (n.get("protein") or 0) * q
            u.sodium += (n.get("sodium") or 0) * q
        else:
            u.unknown.append(leaf)
        spicy = bool(mcd.SPICY.search(leaf)) or (k == "汉堡" and bool(mcd.SPICY.search(parent_txt)))
        if spicy:
            u.spicy_leaves.append(leaf)
        if k == "汉堡":
            if spicy:
                u.spicy_burgers += q
            else:
                u.nonspicy_burgers += q
        if k == "饮品" and not mcd.SUGAR_FREE.search(leaf):
            u.sugary_drinks.append(leaf)
    return u


def default_leaves(det, fallback_name, chosen=None):
    """Expand a set meal to its default (or explicitly chosen) round items."""
    if not det or not det.get("rounds"):
        return [(fallback_name or (det or {}).get("name"), 1)]
    out = []
    for r in det["rounds"]:
        sel = (chosen or {}).get(str(r.get("id")))
        if sel:
            names = {c["code"]: c["name"] for c in r["choices"]}
            out += [(names.get(ci.get("code"), ci.get("code")), ci.get("quantity", 1)) for ci in sel]
            continue
        d = next((c for c in r["choices"] if c.get("isDefault") == 1), r["choices"][0] if r["choices"] else None)
        if d:
            out.append((d["name"], r.get("quantity") or 1))
    return out


def all_names(units):
    return [leaf for u in units for leaf, _ in u.leaves] + [u.name or "" for u in units]


def evaluate(units, constraints, payable):
    """units: list of Unit (repeated for quantity). Returns (checks, aggregates)."""
    agg = {"kinds": {}, "kcal": 0.0, "protein": 0.0, "sodium": 0.0, "unknown": [], "spicy": [], "nonspicy_burgers": 0}
    for u in units:
        for k, v in u.kinds.items():
            agg["kinds"][k] = agg["kinds"].get(k, 0) + v
        agg["kcal"] += u.kcal
        agg["protein"] += u.protein
        agg["sodium"] += u.sodium
        agg["unknown"] += u.unknown
        agg["spicy"] += u.spicy_leaves
        agg["nonspicy_burgers"] += u.nonspicy_burgers
    c, ch = constraints, {}
    need_nut = any(k in c for k in ("max_kcal", "min_kcal", "min_protein", "max_sodium"))
    nut_ok = not agg["unknown"]
    if "max_payable" in c:
        ch["budget"] = payable is not None and payable <= c["max_payable"] + 1e-9
    if "max_kcal" in c:
        ch["kcal_max"] = nut_ok and agg["kcal"] <= c["max_kcal"]
    if "min_kcal" in c:
        ch["kcal_min"] = nut_ok and agg["kcal"] >= c["min_kcal"]
    if "min_protein" in c:
        ch["protein"] = nut_ok and agg["protein"] >= c["min_protein"]
    if "max_sodium" in c:
        ch["sodium"] = nut_ok and agg["sodium"] <= c["max_sodium"]
    for k, n in (c.get("min_kind") or {}).items():
        ch[f"count_{k}"] = agg["kinds"].get(k, 0) >= n
    for k, n in (c.get("max_kind") or {}).items():
        ch[f"max_{k}"] = agg["kinds"].get(k, 0) <= n
    if c.get("sugar_free_drinks"):
        ch["sugar_free"] = not any(u.sugary_drinks for u in units)
    if c.get("no_spicy"):
        ch["no_spicy"] = not agg["spicy"]
    if "min_non_spicy_burgers" in c:
        ch["non_spicy"] = agg["nonspicy_burgers"] >= c["min_non_spicy_burgers"]
    if c.get("no_caffeine"):
        ch["no_caffeine"] = not any(any(w in n for w in CAFFEINE) for n in all_names(units))
    for kw in c.get("exclude_keywords") or []:
        ch[f"exclude_{kw}"] = not any(kw in n for n in all_names(units))
    if c.get("must_include_name"):
        ch["must_include"] = any(c["must_include_name"] in n for n in all_names(units))
    if c.get("use_coupon"):
        ch["coupon"] = any(u.coupon for u in units)
    if c.get("distinct_codes"):
        codes = [u.code for u in units]
        ch["distinct"] = len(codes) == len(set(codes))
    if "max_items" in c:
        ch["max_items"] = len(units) <= c["max_items"]
    if need_nut:
        agg["nutrition_verifiable"] = nut_ok
    return ch, agg


def unit_allowed(u, c):
    """Per-unit filter (necessary conditions) used to prune the solver's search."""
    if u.price is None or u.kinds.get("其他") and len(u.kinds) == 1:
        return False
    need_nut = any(k in c for k in ("max_kcal", "min_kcal", "min_protein", "max_sodium"))
    if need_nut and u.unknown:
        return False
    if c.get("sugar_free_drinks") and u.sugary_drinks:
        return False
    if c.get("no_spicy") and u.spicy_leaves:
        return False
    names = [leaf for leaf, _ in u.leaves] + [u.name or ""]
    if c.get("no_caffeine") and any(any(w in n for w in CAFFEINE) for n in names):
        return False
    if any(any(kw in n for n in names) for kw in c.get("exclude_keywords") or []):
        return False
    if "max_kcal" in c and u.kcal > c["max_kcal"]:
        return False
    if "max_payable" in c and u.price > c["max_payable"]:
        return False
    return True
