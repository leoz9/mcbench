import json, os, subprocess, sys, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcbench.mcp_client import HttpMCP, MockMCP, SafeMCP
from mcbench.safety import BlockedToolError
from mcbench.tasks import TASK_BY_ID
from mcbench.verifier import verify


class T(unittest.TestCase):
    def test_create_order_blocked(self):
        with self.assertRaises(BlockedToolError):
            SafeMCP(MockMCP()).call_tool("create-order", {})
        self.assertNotIn("create-order", [t["name"] for t in SafeMCP(MockMCP()).list_tools()])

    def test_verifier_recomputes(self):
        m = SafeMCP(MockMCP())
        v = verify(TASK_BY_ID["best-coupon"], {"storeCode": "MOCK001", "couponCode": "CPN-MOCK-A",
                   "items": [{"productCode": "C001", "quantity": 2}, {"productCode": "S001", "quantity": 1}],
                   "claimedPayable": 79}, m)
        self.assertTrue(v["passed"]); self.assertEqual(v["payable"], 79.0); self.assertTrue(v["honest"])
        v = verify(TASK_BY_ID["budget-solo"], {"storeCode": "MOCK001", "items": [{"productCode": "FAKE", "quantity": 1}],
                   "claimedPayable": 1}, m)
        self.assertFalse(v["valid"])

    def test_http_client_against_mock_server(self):
        from mcbench import mock_server
        threading.Thread(target=mock_server.serve, kwargs={"port": 8799}, daemon=True).start()
        time.sleep(0.5)
        c = SafeMCP(HttpMCP("http://127.0.0.1:8799", token="dummy"))
        self.assertIn("calculate-price", [t["name"] for t in c.list_tools()])
        q = c.call_tool("calculate-price", {"storeCode": "MOCK001", "items": [{"productCode": "B001", "quantity": 1}]})
        self.assertEqual(q["payable"], 24.0)


if __name__ == "__main__":
    unittest.main()
