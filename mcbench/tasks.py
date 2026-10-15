"""Standard McBench tasks. Each has a natural-language prompt + machine-checkable constraints.
Prompts are written against real McDonald's China MCP behaviour (到店自取: beType=1, orderType=1)."""

LOC = "我在上海人民广场附近，到店自取（beType=1, orderType=1；搜门店用 searchType=2, city=上海, keyword=人民广场），选最近的门店。"

TASKS = [
    {"id": "budget-solo", "title": "30 元一人午餐",
     "prompt": LOC + "一人午餐：至少 1 个汉堡和 1 杯饮品（套餐也可以），应付不超过 30 元，尽量吃饱：总热量尽量高但不超过 900 kcal（热量以 list-nutrition-foods 为准）。",
     "constraints": {"max_payable": 30, "min_kind": {"汉堡": 1, "饮品": 1}, "max_kcal": 900},
     "objective": "max_kcal"},
    {"id": "calorie-lunch", "title": "700 kcal 高蛋白午餐",
     "prompt": LOC + "午餐：总热量不超过 700 kcal，蛋白质至少 25g，至少 1 个汉堡和 1 杯无糖饮品（如无糖可乐/美式/纯悦）。营养以 list-nutrition-foods 为准，应付越低越好。",
     "constraints": {"max_kcal": 700, "min_protein": 25, "min_kind": {"汉堡": 1, "饮品": 1}, "sugar_free_drinks": True},
     "objective": "min_payable"},
    {"id": "group-6", "title": "6 人团餐 200 元",
     "prompt": LOC + "6 个同事加班：每人至少 1 个汉堡 + 1 杯饮品（可以是套餐），其中至少 2 个汉堡不能是辣的，应付不超过 200 元，越便宜越好。",
     "constraints": {"max_payable": 200, "min_kind": {"汉堡": 6, "饮品": 6}, "min_non_spicy_burgers": 2},
     "objective": "min_payable"},
    {"id": "best-coupon", "title": "用好优惠券",
     "prompt": LOC + "先查我在该门店可用的优惠券（query-store-coupons）。搭配至少 1 个汉堡 + 1 份小食，如果有可用券必须至少用上一张（在 calculate-price 的商品项里带 couponId 和 couponCode），应付越低越好。",
     "constraints": {"min_kind": {"汉堡": 1, "小食": 1}, "use_coupon": True},
     "objective": "min_payable"},
    {"id": "family-3", "title": "三口之家不吃辣",
     "prompt": LOC + "一家三口（含一个小朋友）：3 个汉堡、3 杯饮品、至少 1 份小食，全部不要辣的，其中要有一盒纯牛奶给小朋友，应付不超过 100 元，越便宜越好。",
     "constraints": {"max_payable": 100, "min_kind": {"汉堡": 3, "饮品": 3, "小食": 1}, "no_spicy": True,
                     "must_include_name": "纯牛奶"},
     "objective": "min_payable"},
]

TASK_BY_ID = {t["id"]: t for t in TASKS}

SYSTEM_PROMPT = """你是麦当劳点餐助手，正在参加 McBench 评测。
通过 MCP 工具查询门店、菜单、套餐组成、营养和优惠券，用 calculate-price 核价（价格单位：元）。
套餐默认按 query-meal-detail 中 isDefault=1 的选项计算组成。
完成后必须调用 submit_order 提交最终方案（dry-run，不会真实下单），claimedPayable 填 calculate-price 返回的应付金额。
严禁编造商品编码或价格；create-order 等下单/改账户工具已被禁用。工具调用次数有限，请高效。"""

SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_order",
        "description": "提交最终点餐方案（dry-run，仅用于评分，不会下单）。items 格式与 calculate-price 相同（用券时在商品项里带 couponId/couponCode）。",
        "parameters": {"type": "object", "properties": {
            "storeCode": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object", "properties": {
                "productCode": {"type": "string"}, "quantity": {"type": "integer"},
                "couponId": {"type": "string"}, "couponCode": {"type": "string"}},
                "required": ["productCode", "quantity"]}},
            "claimedPayable": {"type": "number", "description": "应付总价（元）"},
            "explanation": {"type": "string"}},
            "required": ["storeCode", "items", "claimedPayable"]}}}
