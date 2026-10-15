"""Scripted DEMO agents (NOT real LLMs). They speak the same OpenAI tool-calling
protocol so the harness/verifier/replay path is exercised end to end without an
API key (against the mock or the live MCP). Never present them as model results."""
import itertools
import json

from . import mcd
from .tasks import TASKS

DEMO_LABEL = "脚本示例 Agent（非真实大模型）"
B = {"orderType": 1, "beType": 1}
STORE_Q = {"searchType": 2, "city": "上海", "keyword": "人民广场", "beType": 1}


class ScriptedAgent:
    scripted = True

    def __init__(self, policy):
        self.policy, self.gen, self.n = policy, None, 0

    def chat(self, messages, tools):
        if self.gen is None:
            prompt = next(m["content"] for m in messages if m["role"] == "user")
            task = next(t for t in TASKS if t["prompt"] == prompt)
            self.gen = self.policy(task)
            step = next(self.gen)
        else:
            results = []
            for m in reversed(messages):
                if m["role"] != "tool":
                    break
                results.insert(0, json.loads(m["content"]))
            try:
                step = self.gen.send(results)
            except StopIteration:
                step = ("完成。", [])
        text, calls = step
        tcs = []
        for name, args in calls:
            self.n += 1
            tcs.append({"id": f"call_{self.n}", "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
        return {"role": "assistant", "content": text, "tool_calls": tcs}, None


def _unit(code, name, price, leaves, nut, extra=None):
    kinds, kcal, prot, unknown, spicy, sugar_ok = {}, 0.0, 0.0, False, 0, True
    for leaf, q in leaves:
        k = mcd.kind(leaf)
        kinds[k] = kinds.get(k, 0) + q
        n = mcd.match_nutrition(leaf, nut)
        if n and n.get("kcal") is not None:
            kcal += n["kcal"] * q
            prot += (n.get("protein") or 0) * q
        else:
            unknown = True
        if mcd.SPICY.search(leaf) or (k == "汉堡" and mcd.SPICY.search(name)):
            spicy += q if k == "汉堡" else 0
            if k != "汉堡":
                spicy += 0
        if k == "饮品" and not mcd.SUGAR_FREE.search(leaf):
            sugar_ok = False
    any_spicy = any(mcd.SPICY.search(l) for l, _ in leaves) or bool(mcd.SPICY.search(name))
    return {"code": code, "name": name, "price": price, "kinds": kinds, "kcal": kcal, "protein": prot,
            "unknown": unknown, "spicy_burgers": spicy, "any_spicy": any_spicy, "sugar_ok": sugar_ok,
            "names": [l for l, _ in leaves], "extra": extra or {}}


def _feasible(task, units):
    c = task["constraints"]
    kinds = {}
    for u in units:
        for k, v in u["kinds"].items():
            kinds[k] = kinds.get(k, 0) + v
    if any(kinds.get(k, 0) < v for k, v in c.get("min_kind", {}).items()):
        return False
    price = sum(u["price"] for u in units)
    if price > c.get("max_payable", 1e9):
        return False
    if ("max_kcal" in c or "min_protein" in c) and any(u["unknown"] for u in units):
        return False
    if sum(u["kcal"] for u in units) > c.get("max_kcal", 1e9) or sum(u["protein"] for u in units) < c.get("min_protein", 0):
        return False
    if c.get("sugar_free_drinks") and not all(u["sugar_ok"] for u in units):
        return False
    if c.get("no_spicy") and any(u["any_spicy"] for u in units):
        return False
    if "min_non_spicy_burgers" in c:
        nb = sum(u["kinds"].get("汉堡", 0) - u["spicy_burgers"] for u in units)
        if nb < c["min_non_spicy_burgers"]:
            return False
    if c.get("must_include_name") and not any(c["must_include_name"] in n for u in units for n in u["names"]):
        return False
    if c.get("use_coupon") and not any(u["extra"].get("couponId") for u in units):
        return False
    return True


def _items(units):
    out = {}
    for u in units:
        key = u["code"]
        if key not in out:
            out[key] = {"productCode": key, "quantity": 0, **u["extra"]}
        out[key]["quantity"] += 1
    return list(out.values())


def _basics():
    r = yield ("先按位置搜索门店。", [("query-nearby-stores", STORE_Q)])
    st = r[0]["stores"][0]
    store = st["storeCode"]
    r = yield (f"选最近的 {st['storeName']}，查菜单、营养和可用券。",
               [("query-meals", {"storeCode": store, **B}), ("list-nutrition-foods", {}),
                ("query-store-coupons", {"storeCode": store, **B})])
    menu = {m["code"]: m for m in r[0]["meals"]}
    nut = {f["name"]: f for f in r[1]["foods"]}
    return store, menu, nut, r[2].get("coupons", [])


def planner(task):
    """Strong script: expands cheap combos via query-meal-detail, quotes coupon items,
    enumerates combinations, then verifies the best two with calculate-price."""
    store, menu, nut, coupons = yield from _basics()
    c = task["constraints"]
    singles = [m for m in menu.values() if m["price"] and "套" not in m["name"] and "餐" not in m["name"]
               and m["category"] not in ("小食拼盘/多人餐",) and "徽章" not in m["name"] and "帽" not in m["name"]]
    combos = sorted([m for m in menu.values() if m["price"] and ("套" in m["name"] or "餐" in m["name"])
                     and m["category"] not in ("小食拼盘/多人餐",) and m["price"] <= c.get("max_payable", 60)],
                    key=lambda m: m["price"])[:6]
    calls = [("query-meal-detail", {"storeCode": store, **B, "code": m["code"]}) for m in combos]
    calls += [("calculate-price", {"storeCode": store, **B, "items": [
        {"productCode": cp["products"][0]["productCode"], "quantity": 1, "couponId": cp["couponId"], "couponCode": cp["couponCode"]}]})
        for cp in coupons if c.get("use_coupon")]
    res = yield (f"展开 {len(combos)} 个便宜套餐的组成" + ("，并逐张试算优惠券价格。" if c.get("use_coupon") else "。"), calls)
    units = [_unit(m["code"], m["name"], m["price"], [(m["name"], 1)], nut) for m in singles]
    for m, d in zip(combos, res[:len(combos)]):
        leaves = []
        for r in d.get("rounds", []):
            ch = next((x for x in r["choices"] if x.get("isDefault") == 1), None)
            if ch:
                leaves.append((ch["name"], r.get("quantity") or 1))
        if leaves:
            units.append(_unit(m["code"], m["name"], m["price"], leaves, nut))
    cdet = []
    for cp, q in zip([cp for cp in coupons if c.get("use_coupon")], res[len(combos):]):
        if q.get("success"):
            cdet.append((cp, q["payable"]))
    if cdet:
        dets = yield ("查看券商品的组成。", [("query-meal-detail", {"storeCode": store, **B, "code": cp["products"][0]["productCode"]}) for cp, _ in cdet])
        for (cp, price), d in zip(cdet, dets):
            leaves = [(next((x for x in r["choices"] if x.get("isDefault") == 1), r["choices"][0])["name"], r.get("quantity") or 1)
                      for r in d.get("rounds", []) if r["choices"]] or [(cp["title"], 1)]
            units.append(_unit(cp["products"][0]["productCode"], cp["title"], price, leaves, nut,
                               {"couponId": cp["couponId"], "couponCode": cp["couponCode"]}))
    need = sum(c.get("min_kind", {}).values())
    size = min(max(2, need), 6)
    pool = []
    for k in c.get("min_kind", {}):
        pool += sorted([u for u in units if list(u["kinds"]) == [k] and _feasible(
            {"constraints": {x: y for x, y in c.items() if x in ("no_spicy", "sugar_free_drinks")}}, [u])
            and (not ("max_kcal" in c or "min_protein" in c) or not u["unknown"])], key=lambda u: u["price"])[:4]
    pool += [u for u in units if len(u["kinds"]) > 1 and u not in pool]
    if c.get("must_include_name"):
        pool += [u for u in units if any(c["must_include_name"] in n for n in u["names"]) and u not in pool][:1]
    if c.get("use_coupon"):
        pool += [u for u in units if u["extra"] and u not in pool]
    if task["objective"] == "max_kcal":
        pool += sorted([u for u in units if list(u["kinds"]) == ["小食"] and not u["unknown"]], key=lambda u: u["price"])[:3]
    best = []
    for n in range(1, size + 1):
        for combo in itertools.combinations_with_replacement(pool, n):
            if _feasible(task, combo):
                best.append(combo)
    if task["objective"] == "max_kcal":
        best.sort(key=lambda cb: -sum(u["kcal"] for u in cb))
    else:
        best.sort(key=lambda cb: sum(u["price"] for u in cb))
    best = best[:2]
    if not best:
        yield ("没有找到满足条件的组合。", [])
        return
    calls = [("calculate-price", {"storeCode": store, **B, "items": _items(cb)}) for cb in best]
    quotes = yield (f"本地筛出 {len(best)} 个候选，用 calculate-price 核价。", calls)
    ok = [i for i, q in enumerate(quotes) if q.get("success")]
    if not ok:
        yield ("核价失败。", [])
        return
    i = ok[0] if task["objective"] == "max_kcal" else min(ok, key=lambda j: quotes[j]["payable"])
    pay = quotes[i]["payable"]
    items = calls[i][1]["items"]
    names = {u["code"]: u["name"] for u in units}
    desc = "、".join(f"{names.get(x['productCode'], x['productCode'])}×{x['quantity']}" for x in items)
    yield (f"最终方案：{desc}，应付 ¥{pay}。", [("submit_order", {"storeCode": store, "items": items,
                                                              "claimedPayable": pay, "explanation": desc})])


def greedy(task):
    """Medium script: cheapest single item per required kind; ignores coupons, nutrition and dietary rules."""
    store, menu, nut, coupons = yield from _basics()
    items = []
    for k, n in task["constraints"].get("min_kind", {}).items():
        cands = [m for m in menu.values() if m["price"] and mcd.kind(m["name"]) == k and "套" not in m["name"]
                 and "餐" not in m["name"] and m["category"] not in ("小食拼盘/多人餐", "蘸酱炸鸡")]
        m = min(cands, key=lambda m: m["price"])
        items.append({"productCode": m["code"], "quantity": n})
    q = (yield ("每类挑最便宜的单品，核一下价。", [("calculate-price", {"storeCode": store, **B, "items": items})]))[0]
    yield (f"应付 ¥{q.get('payable')}，提交。", [("submit_order", {"storeCode": store, "items": items,
                                                                 "claimedPayable": q.get("payable")})])


def hasty(task):
    """Weak script: grabs the first set meal, tries create-order (blocked), claims a guessed price."""
    r = yield ("直接点个套餐吧。", [("query-nearby-stores", STORE_Q)])
    store = r[0]["stores"][0]["storeCode"]
    menu = (yield ("看看菜单。", [("query-meals", {"storeCode": store, **B})]))[0]["meals"]
    m = next(x for x in menu if "三件套" in (x["name"] or ""))
    n = task["constraints"].get("min_kind", {}).get("汉堡", 1)
    items = [{"productCode": m["code"], "quantity": n}]
    yield ("顺手下个单。", [("create-order", {"storeCode": store, **B, "items": items})])
    yield ("下单被拦截了，那就提交方案（价格凭印象）。", [("submit_order", {"storeCode": store, "items": items,
                                                                    "claimedPayable": 25 * n})])


DEMO_AGENTS = {"demo-planner": planner, "demo-greedy": greedy, "demo-hasty": hasty}
