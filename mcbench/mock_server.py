"""MOCK McDonald's MCP backend (demo mode). 模拟服务器：数据由真实只读响应录制而来（见 fixtures/），非实时。

Responses mimic the real server's shapes ({success, code, message, data}; prices in
fen for calculate-price; nutrition as a compact table string) so the same adapter
(mcbench/mcd.py) and verifier work in both demo and live mode.
Can also be served over HTTP (JSON-RPC, Streamable-HTTP JSON mode) for client tests.
"""
import json
from importlib import resources
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MOCK_LABEL = "MOCK（录制数据回放，非麦当劳官方实时数据）"


def _fixture(name):
    return json.loads(resources.files("mcbench").joinpath(f"fixtures/{name}").read_text("utf-8"))


def ok(data):
    return {"success": True, "code": 200, "message": "请求成功", "data": data, "_mock": MOCK_LABEL}


def err(code, msg):
    return {"success": False, "code": code, "message": msg, "_mock": MOCK_LABEL}


class MockBackend:
    def __init__(self):
        self.d = _fixture("mock_data.json")
        self.schemas = _fixture("tool_schemas.json")
        self.store_codes = {s["storeCode"] for s in self.d["stores"]}

    def list_tools(self):
        return self.schemas

    def _price(self, args):
        if args.get("storeCode") not in self.store_codes:
            return err(60001, "门店不存在或不可用")
        lines, orig, total = [], 0, 0
        valid = {(c["couponId"], c["couponCode"]): c for c in self.d["coupons"]}
        for it in args.get("items") or []:
            code, q = it.get("productCode"), int(it.get("quantity") or 0)
            if q < 1:
                return err(60002, "数量必须大于等于1")
            if code in self.d["meals"]:
                m = self.d["meals"][code]
                unit_o = unit = round(float(m["currentPrice"]) * 100)
                name = m["name"]
            elif code in self.d["couponPrices"] and (it.get("couponId"), it.get("couponCode")) in valid:
                cp = self.d["couponPrices"][code]
                unit_o, unit, name = round(cp["originalPrice"] * 100), round(cp["couponPrice"] * 100), cp["name"]
            else:
                return err(60006, "商品已售罄或不可售，换一个商品或检查orderType/beType")
            lines.append({"productCode": code, "productName": name, "quantity": q,
                          "originalSubtotal": unit_o * q, "subtotal": unit * q})
            orig += unit_o * q
            total += unit * q
        if not lines:
            return err(60003, "商品列表不能为空")
        return ok({"productOriginalPrice": orig, "productPrice": total, "originalPrice": orig,
                   "discount": orig - total, "price": total, "productList": lines})

    def call(self, name, args):
        d = self.d
        if name == "now-time-info":
            return ok({"formatted": "2026-10-15 12:00:00", "_note": "mock time"})
        if name == "query-nearby-stores":
            return ok(d["stores"])
        if name in ("query-meals", "query-meal-detail", "query-store-coupons", "calculate-price") and \
                args.get("storeCode") not in self.store_codes:
            return err(60001, "门店不存在或不可用")
        if name == "query-meals":
            return ok({"categories": d["categories"], "meals": d["meals"]})
        if name == "query-meal-detail":
            x = d["details"].get(args.get("code"))
            return ok(x) if x else err(60006, "商品不存在")
        if name == "list-nutrition-foods":
            return ok(d["nutrition"])
        if name == "query-store-coupons":
            return ok(d["coupons"])
        if name == "query-my-coupons":
            return ok(d["coupons"])
        if name == "campaign-calendar":
            return ok([])
        if name == "calculate-price":
            return self._price(args)
        if name == "create-order":
            return err(403, "MOCK server refuses orders")
        return err(404, f"unknown tool {name}")


def serve(port=8765):
    backend = MockBackend()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            m, rid = req.get("method"), req.get("id")
            if m == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "mcbench-mock-mcd", "version": "0.2"}}
            elif m == "tools/list":
                result = {"tools": backend.list_tools()}
            elif m == "tools/call":
                p = req.get("params", {})
                out = backend.call(p.get("name"), p.get("arguments") or {})
                # real server wraps JSON inside markdown text; mimic that
                text = "## (mock) 展示说明省略\n" + json.dumps(out, ensure_ascii=False)
                result = {"content": [{"type": "text", "text": text}]}
            else:
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
