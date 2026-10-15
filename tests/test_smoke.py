import sys, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcbench import mcd
from mcbench.mcp_client import HttpMCP, MockMCP, SafeMCP
from mcbench.safety import BlockedToolError
from mcbench.tasks import TASK_BY_ID
from mcbench.verifier import verify

S = "1450713"


class T(unittest.TestCase):
    def test_write_tools_blocked(self):
        m = SafeMCP(MockMCP())
        for t in ("create-order", "auto-bind-coupons", "delivery-create-address", "mall-create-order"):
            with self.assertRaises(BlockedToolError):
                m.call_tool(t, {})
        self.assertNotIn("create-order", [t["name"] for t in m.list_tools()])

    def test_adapter_parses_real_shapes(self):
        m = MockMCP()
        menu = mcd.menu(m.call_tool("query-meals", {"storeCode": S}))
        self.assertEqual(menu["1450"]["name"], "麦香鸡")
        self.assertEqual(menu["1450"]["price"], 17.0)
        nut = mcd.nutrition(m.call_tool("list-nutrition-foods", {}))
        self.assertGreater(len(nut), 100)
        self.assertEqual(mcd.match_nutrition("可乐", nut)["kcal"], nut["可乐中杯"]["kcal"])
        text = {"text": "## 说明\n" + '{"success":true,"code":200,"data":{"price":4350,"originalPrice":4350,"discount":0,"productList":[]}}\n## 尾巴'}
        self.assertEqual(mcd.quote(text)["payable"], 43.5)

    def test_verifier_recomputes(self):
        m = SafeMCP(MockMCP())
        sub = {"storeCode": S, "items": [{"productCode": "1450", "quantity": 1}, {"productCode": "3010", "quantity": 1}],
               "claimedPayable": 26.5}
        v = verify(TASK_BY_ID["budget-solo"], sub, m)
        self.assertTrue(v["passed"], v); self.assertEqual(v["payable"], 26.5); self.assertTrue(v["honest"])
        v = verify(TASK_BY_ID["calorie-lunch"], sub, m)
        self.assertFalse(v["checks"]["sugar_free"])
        v = verify(TASK_BY_ID["budget-solo"], {"storeCode": S, "items": [{"productCode": "FAKE", "quantity": 1}],
                                               "claimedPayable": 1}, m)
        self.assertFalse(v["valid"])

    def test_combo_expands_to_default_components(self):
        m = SafeMCP(MockMCP())
        v = verify(TASK_BY_ID["budget-solo"], {"storeCode": S, "items": [{"productCode": "9900005453", "quantity": 1}],
                                               "claimedPayable": 28}, m)
        self.assertEqual(v["kinds"], {"汉堡": 1, "小食": 1, "饮品": 1})

    def test_http_client_against_mock_server(self):
        from mcbench import mock_server
        threading.Thread(target=mock_server.serve, kwargs={"port": 8799}, daemon=True).start()
        time.sleep(0.5)
        c = SafeMCP(HttpMCP("http://127.0.0.1:8799", token="dummy"))
        self.assertIn("calculate-price", [t["name"] for t in c.list_tools()])
        q = mcd.quote(c.call_tool("calculate-price", {"storeCode": S, "orderType": 1, "beType": 1,
                                                      "items": [{"productCode": "1100", "quantity": 1}]}))
        self.assertEqual(q["payable"], 25.5)


if __name__ == "__main__":
    unittest.main()
