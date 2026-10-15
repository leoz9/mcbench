"""Scripted baseline agents (NOT LLMs). Same OpenAI tool-calling protocol as real models.

- demo-planner: reads the task's *structured* constraints (oracle access to the spec, not
  to answers), fetches menu/nutrition/coupons/set-meal details via MCP tools, then runs the
  exact solver; reports infeasible / asks the user when appropriate.
- demo-greedy: cheapest single item per required kind; ignores coupons, diet, feasibility.
- demo-hasty: grabs a set meal, tries create-order (a safety violation), guesses the price.
"""
import json
import re

from . import mcd
from .solver import solve
from .tasks import load_task_set
from .units import default_leaves, make_unit

DEMO_LABEL = "脚本基线（非大模型）"
B = {"orderType": 1, "beType": 1}
STORE_Q = {"searchType": 2, "city": "上海", "keyword": "人民广场", "beType": 1}
SETMEAL = re.compile(r"套|餐|拼|随心|精选|件|盒|分享")
_ALL = None


def _task_for(prompt):
    global _ALL
    if _ALL is None:
        _ALL = load_task_set("v1.0")["tasks"]
    return next(t for t in _ALL if t["prompt"] == prompt)


class ScriptedAgent:
    scripted = True

    def __init__(self, policy, runtime=DEMO_LABEL):
        self.policy, self.gen, self.n, self.runtime = policy, None, 0, runtime

    def chat(self, messages, tools):
        if self.gen is None:
            prompt = next(m["content"] for m in messages if m["role"] == "user")
            self.gen = self.policy(_task_for(prompt))
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


def _basics(coupons=True):
    r = yield ("先按位置搜索门店。", [("query-nearby-stores", STORE_Q)])
    st = r[0]["stores"][0]
    store = st["storeCode"]
    calls = [("query-meals", {"storeCode": store, **B}), ("list-nutrition-foods", {})]
    if coupons:
        calls.append(("query-store-coupons", {"storeCode": store, **B}))
    r = yield (f"选最近的 {st['storeName']}，查菜单、营养" + ("和可用券。" if coupons else "。"), calls)
    menu = {m["code"]: m for m in r[0]["meals"]}
    nut = {f["name"]: f for f in r[1]["foods"]}
    return store, menu, nut, (r[2].get("coupons", []) if coupons else [])


def planner(task):
    if task.get("requires_clarification"):
        yield ("信息不全，先问清楚。", [("ask_user", {"question": "请问几个人、预算多少、有什么忌口？"})])
    store, menu, nut, coupons = yield from _basics()
    nutd = {k: v for k, v in nut.items()}
    sm = list(menu)  # fetch every item detail (some singles have a pick-one round)
    calls = [("query-meal-detail", {"storeCode": store, **B, "code": c}) for c in sm]
    cps = coupons if task["constraints"].get("use_coupon") else []
    calls += [("query-meal-detail", {"storeCode": store, **B, "code": cp["products"][0]["productCode"]}) for cp in cps]
    calls += [("calculate-price", {"storeCode": store, **B, "items": [{"productCode": cp["products"][0]["productCode"], "quantity": 1,
                                                                     "couponId": cp["couponId"], "couponCode": cp["couponCode"]}]}) for cp in cps]
    res = yield (f"查询全部 {len(sm)} 个餐品的组成" + ("，试算优惠券。" if cps else "。"), calls)
    dets = dict(zip(sm, res[:len(sm)]))
    units = []
    for c, m in menu.items():
        units.append(make_unit(c, m["name"], m["price"], default_leaves(dets.get(c), m["name"]), nutd, m.get("tags")))
    for i, cp in enumerate(cps):
        d, q = res[len(sm) + i], res[len(sm) + len(cps) + i]
        if q.get("success"):
            units.append(make_unit(cp["products"][0]["productCode"], cp["title"], q["payable"], default_leaves(d, cp["title"]),
                                   nutd, coupon={"couponId": cp["couponId"], "couponCode": cp["couponCode"]}))
    ref = solve(task, units, time_limit=8)
    if not ref["feasible"]:
        yield ("穷举后没有任何组合能同时满足所有约束。", [("report_infeasible", {"reason": "在该门店菜单与价格下，无法同时满足全部约束"})])
        return
    by = {u.code: u for u in units}
    items = [{"productCode": x["productCode"], "quantity": x["quantity"], **by[x["productCode"]].coupon} for x in ref["items"]]
    q = (yield ("求解出最优组合，核价。", [("calculate-price", {"storeCode": store, **B, "items": items})]))[0]
    desc = "、".join(f"{x['name']}×{x['quantity']}" for x in ref["items"])
    yield (f"最终方案：{desc}，应付 ¥{q.get('payable')}。", [("submit_order", {"storeCode": store, "items": items,
                                                                       "claimedPayable": q.get("payable"), "explanation": desc})])


def greedy(task):
    store, menu, nut, _ = yield from _basics(coupons=False)
    items = []
    for k, n in (task["constraints"].get("min_kind") or {"汉堡": 1, "饮品": 1}).items():
        cands = [m for m in menu.values() if m["price"] and mcd.kind(m["name"]) == k and not SETMEAL.search(m["name"])]
        if cands:
            m = min(cands, key=lambda m: m["price"])
            items.append({"productCode": m["code"], "quantity": n})
    q = (yield ("每类挑最便宜的单品，核一下价。", [("calculate-price", {"storeCode": store, **B, "items": items})]))[0]
    yield (f"应付 ¥{q.get('payable')}，提交。", [("submit_order", {"storeCode": store, "items": items,
                                                                 "claimedPayable": q.get("payable")})])


def hasty(task):
    r = yield ("直接点个套餐吧。", [("query-nearby-stores", STORE_Q)])
    store = r[0]["stores"][0]["storeCode"]
    menu = (yield ("看看菜单。", [("query-meals", {"storeCode": store, **B})]))[0]["meals"]
    m = next(x for x in menu if "三件套" in (x["name"] or ""))
    n = (task["constraints"].get("min_kind") or {}).get("汉堡", 1)
    items = [{"productCode": m["code"], "quantity": n}]
    yield ("顺手下个单。", [("create-order", {"storeCode": store, **B, "items": items})])
    yield ("下单被拦截了，那就提交方案（价格凭印象）。", [("submit_order", {"storeCode": store, "items": items,
                                                                    "claimedPayable": 25 * n})])


DEMO_AGENTS = {"demo-planner": planner, "demo-greedy": greedy, "demo-hasty": hasty}
