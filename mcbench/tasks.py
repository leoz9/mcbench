"""Standard McBench tasks. Each has a natural-language prompt + machine-checkable constraints."""

TASKS = [
    {"id": "budget-solo", "title": "30 元一人午餐",
     "prompt": "我在上海人民广场附近，想点一份一人午餐：至少 1 个汉堡和 1 杯饮品，总价（应付）不超过 30 元，尽量吃饱（热量尽量高但不超过 900 kcal）。",
     "constraints": {"max_payable": 30, "min_category": {"汉堡": 1, "饮品": 1}, "max_kcal": 900},
     "objective": "max_kcal"},
    {"id": "calorie-lunch", "title": "700 kcal 高蛋白午餐",
     "prompt": "帮我在人民广场附近搭配一份午餐：总热量不超过 700 kcal，蛋白质至少 30g，包含 1 个汉堡，饮品要无糖。价格越低越好。",
     "constraints": {"max_kcal": 700, "min_protein": 30, "min_category": {"汉堡": 1, "饮品": 1}, "drink_tag": "无糖"},
     "objective": "min_payable"},
    {"id": "group-6", "title": "6 人团餐 200 元",
     "prompt": "公司 6 个人加班，在人民广场附近点餐：每人至少 1 个汉堡 + 1 杯饮品（可以是套餐），其中 2 人不吃辣，总应付不超过 200 元，可以用券，越便宜越好。",
     "constraints": {"max_payable": 200, "min_category": {"汉堡": 6, "饮品": 6}, "min_non_spicy_burgers": 2},
     "objective": "min_payable"},
    {"id": "best-coupon", "title": "用好优惠券",
     "prompt": "我要在人民广场店点：2 份巨无霸套餐 + 1 份麦辣鸡翅(2块)。请查一下我在门店可用的优惠券，选应付金额最低的方案（只能用一张券）。",
     "constraints": {"exact_items": {"C001": 2, "S001": 1}},
     "objective": "min_payable"},
    {"id": "family-3", "title": "三口之家不吃辣",
     "prompt": "一家三口（含一个小朋友）在人民广场附近，预算 100 元以内：3 个汉堡、3 杯饮品、至少 1 份小食，全部不要辣的，小朋友要一杯纯牛奶。越便宜越好。",
     "constraints": {"max_payable": 100, "min_category": {"汉堡": 3, "饮品": 3, "小食": 1}, "no_tag": "辣",
                     "must_include": ["D004"]},
     "objective": "min_payable"},
]

TASK_BY_ID = {t["id"]: t for t in TASKS}

SYSTEM_PROMPT = """你是麦当劳点餐助手，正在参加 McBench 评测。
通过 MCP 工具查询门店、菜单、营养和优惠券，用 calculate-price 核价。
完成后必须调用 submit_order 提交最终方案（这是 dry-run，不会真实下单）。
严禁编造商品编码或价格；所有数字以工具返回为准。create-order 等下单工具已被禁用。"""

SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_order",
        "description": "提交最终点餐方案（dry-run，仅用于评分，不会下单）",
        "parameters": {"type": "object", "properties": {
            "storeCode": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object", "properties": {
                "productCode": {"type": "string"}, "quantity": {"type": "integer"}},
                "required": ["productCode", "quantity"]}},
            "couponCode": {"type": "string"},
            "claimedPayable": {"type": "number", "description": "你认为的应付总价"},
            "explanation": {"type": "string"}},
            "required": ["storeCode", "items", "claimedPayable"]}}}
