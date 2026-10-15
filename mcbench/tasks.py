"""Versioned McBench task set loader. Legacy TASKS (5) kept for back-compat."""
import json
from importlib import resources

SYSTEM_PROMPT = """你是麦当劳点餐助手，正在参加 McBench 评测。
通过 MCP 工具查询门店、菜单、套餐组成、营养和优惠券，用 calculate-price 核价（价格单位：元）。
套餐默认按 query-meal-detail 中 isDefault=1 的选项计算组成。
完成后必须调用 submit_order 提交最终方案（dry-run，不会真实下单），claimedPayable 填 calculate-price 返回的应付金额。
如果任务确实无法满足，请调用 report_infeasible 说明原因，不要硬凑。
信息不足时请用 ask_user 追问。严禁编造商品编码或价格；create-order 等下单/改账户工具已被禁用。"""

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
            "claimedPayable": {"type": "number"}, "explanation": {"type": "string"}},
            "required": ["storeCode", "items", "claimedPayable"]}}}

ASK_USER_TOOL = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": "向用户追问缺少的信息（人数、预算、忌口等）。仅当任务提示信息不足时使用。",
        "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}}

REPORT_INFEASIBLE_TOOL = {
    "type": "function",
    "function": {
        "name": "report_infeasible",
        "description": "在确认无法满足所有约束时调用，说明原因。不要在有可行方案时调用。",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}}

LOCAL_TOOLS = [SUBMIT_TOOL, ASK_USER_TOOL, REPORT_INFEASIBLE_TOOL]


def load_task_set(version="v1.0"):
    return json.loads(resources.files("mcbench").joinpath(f"data/tasks/{version}.json").read_text("utf-8"))


def get_tasks(version="v1.0", split="dev", categories=None, difficulty=None, ids=None):
    data = load_task_set(version)
    out = data["tasks"]
    if split and split != "all":
        out = [t for t in out if t["split"] == split]
    if categories:
        cats = set(categories.split(","))
        out = [t for t in out if t["category"] in cats]
    if difficulty:
        out = [t for t in out if t["difficulty"] == difficulty]
    if ids:
        want = set(ids.split(","))
        out = [t for t in out if t["id"] in want]
    return out


# Backward-compat: the original 5 curated tasks (v0).
TASKS = [t for t in load_task_set("v1.0")["tasks"] if t.get("source") == "curated"]
TASK_BY_ID = {t["id"]: t for t in TASKS}
