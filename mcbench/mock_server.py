"""MOCK McDonald's MCP backend (demo mode). 模拟数据，非官方实时数据。

Implements a subset of tool names from https://github.com/M-China/mcd-mcp-server
with fixture data. Argument schemas here are McBench's own guesses for demo
purposes; the real server's schemas are discovered live via tools/list.
Can also be served over HTTP (JSON-RPC, Streamable-HTTP style) for client tests.
"""
import json
from importlib import resources
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MOCK_LABEL = "MOCK（模拟数据，非麦当劳官方实时数据）"


def load_fixture():
    return json.loads(resources.files("mcbench").joinpath("fixtures/mock_data.json").read_text("utf-8"))


TOOL_SCHEMAS = [
    {"name": "now-time-info", "description": "获取当前时间信息", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "query-nearby-stores", "description": "查询用户提供地址附近的麦当劳餐厅",
     "inputSchema": {"type": "object", "properties": {"address": {"type": "string"}}, "required": ["address"]}},
    {"name": "query-meals", "description": "查询当前门店可售卖的餐品菜单（分类、餐品编码、价格、标签）",
     "inputSchema": {"type": "object", "properties": {"storeCode": {"type": "string"}}, "required": ["storeCode"]}},
    {"name": "query-meal-detail", "description": "根据餐品编码查询套餐组成",
     "inputSchema": {"type": "object", "properties": {"storeCode": {"type": "string"}, "code": {"type": "string"}}, "required": ["code"]}},
    {"name": "list-nutrition-foods", "description": "获取常见餐品的营养成分数据（能量kcal、蛋白质g、脂肪g、碳水g、钠mg）",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "query-store-coupons", "description": "查询用户在当前门店下可使用的优惠券",
     "inputSchema": {"type": "object", "properties": {"storeCode": {"type": "string"}}, "required": ["storeCode"]}},
    {"name": "calculate-price", "description": "根据商品列表（可含优惠券）计算商品金额、优惠金额及应付总价",
     "inputSchema": {"type": "object", "properties": {
         "storeCode": {"type": "string"},
         "items": {"type": "array", "items": {"type": "object", "properties": {
             "productCode": {"type": "string"}, "quantity": {"type": "integer"}}, "required": ["productCode", "quantity"]}},
         "couponCode": {"type": "string"}}, "required": ["storeCode", "items"]}},
    {"name": "create-order", "description": "创建订单（McBench 中永远被拦截）",
     "inputSchema": {"type": "object", "properties": {}}},
]


class MockBackend:
    def __init__(self, data=None):
        self.data = data or load_fixture()
        self.meals = {m["code"]: m for m in self.data["meals"]}
        self.coupons = {c["couponCode"]: c for c in self.data["coupons"]}

    def list_tools(self):
        return TOOL_SCHEMAS

    def nutrition(self, code):
        m = self.meals[code]
        if "components" in m:
            out = {k: 0.0 for k in ("kcal", "protein", "fat", "carb", "sodium")}
            for c in m["components"]:
                for k in out:
                    out[k] += self.meals[c][k]
            return out
        return {k: m[k] for k in ("kcal", "protein", "fat", "carb", "sodium")}

    def price(self, store, items, coupon=None):
        if store not in {s["storeCode"] for s in self.data["stores"]}:
            return {"success": False, "error": f"unknown storeCode {store}"}
        lines, subtotal = [], 0.0
        for it in items:
            code, qty = it.get("productCode"), int(it.get("quantity", 1))
            if code not in self.meals or qty <= 0:
                return {"success": False, "error": f"invalid product {code}"}
            m = self.meals[code]
            lines.append({"productCode": code, "name": m["name"], "unitPrice": m["price"], "quantity": qty})
            subtotal += m["price"] * qty
        discount, note = 0.0, None
        if coupon:
            c = self.coupons.get(coupon)
            if not c:
                note = "coupon not found"
            elif c["type"] == "threshold":
                if subtotal >= c["minSpend"]:
                    discount = c["discount"]
                else:
                    note = f"未满 {c['minSpend']} 元，券不可用"
            elif c["type"] == "item":
                if any(i["productCode"] == c["itemCode"] for i in items):
                    discount = c["discount"]
                else:
                    note = "购物车中无适用商品"
        return {"success": True, "storeCode": store, "lines": lines, "subtotal": round(subtotal, 2),
                "discount": discount, "payable": round(subtotal - discount, 2), "couponNote": note,
                "_mock": MOCK_LABEL}

    def call(self, name, args):
        d = self.data
        if name == "now-time-info":
            return {"now": "2026-10-24 12:00:00 (mock)", "_mock": MOCK_LABEL}
        if name == "query-nearby-stores":
            return {"stores": d["stores"], "_mock": MOCK_LABEL}
        if name == "query-meals":
            return {"storeCode": args.get("storeCode"), "_mock": MOCK_LABEL, "meals": [
                {k: m[k] for k in ("code", "name", "category", "price", "tags")} for m in d["meals"]]}
        if name == "query-meal-detail":
            m = self.meals.get(args.get("code"))
            if not m:
                return {"success": False, "error": "not found"}
            comps = [{"code": c, "name": self.meals[c]["name"], "category": self.meals[c]["category"],
                      "tags": self.meals[c]["tags"]} for c in m.get("components", [])]
            return {"code": m["code"], "name": m["name"], "components": comps, "_mock": MOCK_LABEL}
        if name == "list-nutrition-foods":
            return {"_mock": MOCK_LABEL, "foods": [dict(code=m["code"], name=m["name"], **self.nutrition(m["code"]))
                                                    for m in d["meals"]]}
        if name == "query-store-coupons":
            return {"coupons": d["coupons"], "_mock": MOCK_LABEL}
        if name == "calculate-price":
            return self.price(args.get("storeCode"), args.get("items", []), args.get("couponCode"))
        if name == "create-order":
            return {"success": False, "error": "MOCK server refuses orders"}
        return {"success": False, "error": f"unknown tool {name}"}


def serve(port=8765):
    """Serve the mock over HTTP JSON-RPC (Streamable HTTP, JSON response mode)."""
    backend = MockBackend()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            m, rid = req.get("method"), req.get("id")
            if m == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "mcbench-mock-mcd", "version": "0.1"}}
            elif m == "tools/list":
                result = {"tools": backend.list_tools()}
            elif m == "tools/call":
                p = req.get("params", {})
                out = backend.call(p.get("name"), p.get("arguments") or {})
                result = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}
            else:  # notifications
                self.send_response(202); self.end_headers(); return
            body = json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "mock-session")
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"[{MOCK_LABEL}] mock MCP at http://127.0.0.1:{port}")
    srv.serve_forever()
