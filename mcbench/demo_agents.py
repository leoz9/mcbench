"""Scripted DEMO agents (NOT real LLMs). They speak the same OpenAI tool-calling
protocol so the harness/verifier/replay path is exercised end to end without an
API key. Their results must never be presented as real model results."""
import itertools
import json

from .tasks import TASKS

DEMO_LABEL = "脚本示例 Agent（非真实大模型）"


class ScriptedAgent:
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


def _menu_and_nut(task):
    stores = (yield ("先找附近门店。", [("query-nearby-stores", {"address": "上海市人民广场"})]))[0]["stores"]
    store = stores[0]["storeCode"]
    r = yield (f"选最近的 {stores[0]['storeName']}，查菜单、营养和优惠券。",
               [("query-meals", {"storeCode": store}), ("list-nutrition-foods", {}),
                ("query-store-coupons", {"storeCode": store})])
    meals = {m["code"]: m for m in r[0]["meals"]}
    nut = {f["code"]: f for f in r[1]["foods"]}
    return store, meals, nut, r[2]["coupons"]


def _ok(task, meals, nut, combo, payable):
    c = task["constraints"]
    cnt = {}
    for code in combo:
        cnt[meals[code]["category"]] = cnt.get(meals[code]["category"], 0) + 1
    if any(cnt.get(k, 0) < v for k, v in c.get("min_category", {}).items()):
        return False
    tags = [t for code in combo for t in meals[code]["tags"]]
    if c.get("no_tag") and c["no_tag"] in tags:
        return False
    if c.get("drink_tag") and any(c["drink_tag"] not in meals[x]["tags"] for x in combo if meals[x]["category"] == "饮品"):
        return False
    if "min_non_spicy_burgers" in c and sum(1 for x in combo if meals[x]["category"] == "汉堡" and "辣" not in meals[x]["tags"]) < c["min_non_spicy_burgers"]:
        return False
    if any(x not in combo for x in c.get("must_include", [])):
        return False
    kcal = sum(nut[x]["kcal"] for x in combo)
    prot = sum(nut[x]["protein"] for x in combo)
    return kcal <= c.get("max_kcal", 1e9) and prot >= c.get("min_protein", 0) and payable <= c.get("max_payable", 1e9)


def _items(combo):
    out = {}
    for x in combo:
        out[x] = out.get(x, 0) + 1
    return [{"productCode": k, "quantity": v} for k, v in out.items()]


def planner(task):
    """Strong script: enumerates single items, checks constraints, then quotes every coupon."""
    store, meals, nut, coupons = yield from _menu_and_nut(task)
    c = task["constraints"]
    if "exact_items" in c:
        best = [[k] * v for k, v in c["exact_items"].items()]
        cands = [list(itertools.chain(*best))]
    else:
        need = dict(c.get("min_category", {}))
        pools = []
        for cat, n in need.items():
            pool = sorted([m for m in meals.values() if m["category"] == cat], key=lambda m: m["price"])[:5]
            pools.append([list(x) for x in itertools.combinations_with_replacement([m["code"] for m in pool], n)])
        sides = [[]] + [[m["code"]] for m in meals.values() if m["category"] == "小食"] if "小食" not in need else [[]]
        cands = []
        for parts in itertools.product(*pools, sides):
            combo = list(itertools.chain(*parts))
            sub = sum(meals[x]["price"] for x in combo)
            if _ok(task, meals, nut, combo, sub):
                cands.append(combo)
        key = (lambda cb: -sum(nut[x]["kcal"] for x in cb)) if task["objective"] == "max_kcal" else \
            (lambda cb: sum(meals[x]["price"] for x in cb))
        cands = sorted(cands, key=key)[:2]
    if not cands:
        yield ("没有找到满足条件的方案。", [])
        return
    calls = []
    for cb in cands:
        calls.append(("calculate-price", {"storeCode": store, "items": _items(cb)}))
        for cp in coupons:
            calls.append(("calculate-price", {"storeCode": store, "items": _items(cb), "couponCode": cp["couponCode"]}))
    quotes = yield (f"本地筛出 {len(cands)} 个候选，逐一用 calculate-price 试每张券核价。", calls)
    best, bi = None, None
    for i, (call, q) in enumerate(zip(calls, quotes)):
        if q.get("success") and _ok(task, meals, nut, [p["productCode"] for p in call[1]["items"] for _ in range(p["quantity"])], q["payable"]):
            k = q["payable"] if task["objective"] != "max_kcal" else -sum(nut[p["productCode"]]["kcal"] * p["quantity"] for p in call[1]["items"])
            if best is None or k < best:
                best, bi = k, i
    if bi is None:
        yield ("核价后没有可行方案。", [])
        return
    args, q = calls[bi][1], quotes[bi]
    names = "、".join(f"{meals[p['productCode']]['name']}×{p['quantity']}" for p in args["items"])
    yield (f"最终方案：{names}，应付 ¥{q['payable']}。", [("submit_order", {**args, "claimedPayable": q["payable"],
                                                                        "explanation": names})])


def greedy(task):
    """Medium script: cheapest item per category, ignores coupons & dietary tags, quotes once."""
    store, meals, nut, coupons = yield from _menu_and_nut(task)
    c = task["constraints"]
    if "exact_items" in c:
        items = [{"productCode": k, "quantity": v} for k, v in c["exact_items"].items()]
    else:
        items = []
        for cat, n in c.get("min_category", {}).items():
            m = min((m for m in meals.values() if m["category"] == cat), key=lambda m: m["price"])
            items.append({"productCode": m["code"], "quantity": n})
    q = (yield ("每类挑最便宜的，核一下价。", [("calculate-price", {"storeCode": store, "items": items})]))[0]
    yield (f"应付 ¥{q.get('payable')}，提交。", [("submit_order", {"storeCode": store, "items": items,
                                                                 "claimedPayable": q.get("payable")})])


def hasty(task):
    """Weak script: skips nutrition/coupons, guesses a combo and claims a price without quoting;
    also tries create-order once (to demonstrate the dry-run block)."""
    stores = (yield ("直接点个套餐吧。", [("query-nearby-stores", {"address": "上海市人民广场"})]))[0]["stores"]
    store = stores[0]["storeCode"]
    c = task["constraints"]
    if "exact_items" in c:
        items = [{"productCode": k, "quantity": v} for k, v in c["exact_items"].items()]
        coupon, claim = "CPN-MOCK-B", 61.0
    else:
        n = c.get("min_category", {}).get("汉堡", 1)
        items, coupon, claim = [{"productCode": "C002", "quantity": n}], None, 29.9 * n
    yield ("顺手下个单。", [("create-order", {"storeCode": store, "items": items})])
    args = {"storeCode": store, "items": items, "claimedPayable": claim}
    if coupon:
        args["couponCode"] = coupon
    yield ("下单被拦截了，那就提交方案（价格凭印象）。", [("submit_order", args)])


DEMO_AGENTS = {
    "demo-planner": planner,
    "demo-greedy": greedy,
    "demo-hasty": hasty,
}
