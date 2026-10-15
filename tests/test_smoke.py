import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcbench import mcd
from mcbench.community import validate_task
from mcbench.env import McBenchEnv
from mcbench.harness import run_episode
from mcbench.mcp_client import HttpMCP, MockMCP, SafeMCP
from mcbench.safety import BlockedToolError
from mcbench.solver import snapshot_units, solve
from mcbench.tasks import get_tasks, load_task_set
from mcbench.verifier import verify

S = "1450713"


class Safety(unittest.TestCase):
    def test_writes_blocked(self):
        m = SafeMCP(MockMCP())
        for t in ("create-order", "auto-bind-coupons", "delivery-create-address"):
            with self.assertRaises(BlockedToolError):
                m.call_tool(t, {})


class Adapter(unittest.TestCase):
    def test_shapes(self):
        m = MockMCP()
        menu = mcd.menu(m.call_tool("query-meals", {"storeCode": S}))
        self.assertEqual(menu["1450"]["price"], 17.0)
        nut = mcd.nutrition(m.call_tool("list-nutrition-foods", {}))
        self.assertGreater(mcd.match_nutrition("原味双层深海鳕鱼堡", nut)["kcal"], 0)
        self.assertEqual(mcd.quote({"text": 'x{"success":true,"code":200,"data":{"price":4350,"originalPrice":4350,"discount":0,"productList":[]}}'})["payable"], 43.5)


class Tasks(unittest.TestCase):
    def test_task_set(self):
        d = load_task_set("v1.0")
        self.assertEqual(d["n_tasks"], 54)
        self.assertEqual(len(get_tasks(split="dev")), 36)
        self.assertEqual(len(get_tasks(split="test")), 18)

    def test_references_match_solver(self):
        _, units = snapshot_units()
        for t in get_tasks(split="all", ids="budget-solo,infeasible-01"):
            ref = solve(t, units)
            self.assertEqual(ref["feasible"], t["reference"]["feasible"])


class Verifier(unittest.TestCase):
    def test_pass_and_hallucination(self):
        m = SafeMCP(MockMCP())
        t = get_tasks(split="all", ids="budget-solo")[0]
        v = verify(t, {"storeCode": S, "items": [{"productCode": "9900005453", "quantity": 1}], "claimedPayable": 28}, m)
        self.assertTrue(v["passed"]); self.assertTrue(v["honest"])
        v = verify(t, {"storeCode": S, "items": [{"productCode": "FAKE", "quantity": 1}], "claimedPayable": 1}, m)
        self.assertFalse(v["valid"]); self.assertIn("FAKE", v["hallucinated_codes"])

    def test_infeasible_outcome(self):
        m = SafeMCP(MockMCP())
        t = get_tasks(split="all", ids="infeasible-01")[0]
        self.assertTrue(verify(t, None, m, outcome="infeasible")["passed"])
        self.assertFalse(verify(t, {"storeCode": S, "items": [{"productCode": "1450", "quantity": 1}], "claimedPayable": 17}, m)["passed"])


class Env(unittest.TestCase):
    def test_gym_loop(self):
        from mcbench.demo_agents import DEMO_AGENTS, ScriptedAgent
        env = McBenchEnv()
        tr = run_episode(ScriptedAgent(DEMO_AGENTS["demo-planner"]), "demo-planner",
                         get_tasks(split="all", ids="budget-solo")[0], env)
        self.assertTrue(tr["verdict"]["passed"])
        self.assertGreaterEqual(tr["score"], 90)


class Proxy(unittest.TestCase):
    def test_stdio(self):
        log = Path("/tmp/mcbench_proxy_test.json")
        if log.exists(): log.unlink()
        reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "create-order", "arguments": {}}}]
        out = subprocess.run([sys.executable, "-m", "mcbench.mcp_proxy"], input="\n".join(json.dumps(r) for r in reqs),
                             capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
                             env={**os.environ, "MCBENCH_MODE": "offline", "MCBENCH_TRACE": str(log),
                                  "MCBENCH_TASK_ID": "adversarial-01"}).stdout.splitlines()
        res = [json.loads(l) for l in out]
        self.assertNotIn("create-order", [t["name"] for t in res[1]["result"]["tools"]])
        self.assertIn("blocked", res[2]["result"]["content"][0]["text"])


class Community(unittest.TestCase):
    def test_validate_curated(self):
        t = get_tasks(split="all", ids="budget-solo")[0]
        t = {**t, "dimensions": ["tool_use", "constraints", "cost_opt"], "author": "mcbench"}
        ok, msgs = validate_task(t)
        self.assertTrue(ok, msgs)


class Http(unittest.TestCase):
    def test_mock_http(self):
        from mcbench import mock_server
        threading.Thread(target=mock_server.serve, kwargs={"port": 8798}, daemon=True).start()
        time.sleep(0.4)
        c = SafeMCP(HttpMCP("http://127.0.0.1:8798", token="x"))
        q = mcd.quote(c.call_tool("calculate-price", {"storeCode": S, "orderType": 1, "beType": 1,
                                                      "items": [{"productCode": "1100", "quantity": 1}]}))
        self.assertEqual(q["payable"], 25.5)


if __name__ == "__main__":
    unittest.main()


class AnthropicConvert(unittest.TestCase):
    def test_roundtrip(self):
        from mcbench.llm import AnthropicCompatChat
        msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function",
                 "function": {"name": "query-meals", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "1", "content": "{}"}]
        sysm, out, tools = AnthropicCompatChat.convert(msgs, [{"type": "function", "function": {"name": "x", "parameters": {}}}])
        self.assertEqual(sysm, "S"); self.assertEqual(out[1]["content"][0]["type"], "tool_use")
        self.assertEqual(out[2]["content"][0]["type"], "tool_result"); self.assertEqual(tools[0]["input_schema"], {})


class Hard(unittest.TestCase):
    def test_hard_set_and_references(self):
        from mcbench.solver import snapshot_units
        hs = get_tasks("hard-v1.1", "all")
        self.assertGreaterEqual(len(hs), 30)
        store, units = snapshot_units()
        by = {}
        for u in units:
            by.setdefault((u.code, u.name), u)
        m = SafeMCP(MockMCP())
        for t in hs:
            ref = t["reference"]
            if not ref.get("feasible"):
                self.assertEqual(t["expected_outcome"], "infeasible"); continue
            items = [{"productCode": x["productCode"], "quantity": x["quantity"], **(by[(x["productCode"], x["name"])].coupon or {})}
                     for x in ref["items"]]
            v = verify(t, {"storeCode": store, "items": items, "claimedPayable": ref["payable"]}, m)
            self.assertTrue(v["passed"], t["id"])

    def test_rubric_strict_gap_and_penalties(self):
        from mcbench.rubric import grade
        t = {"id": "x", "strict_optimal": True, "constraints": {}, "expected_outcome": "order"}
        base = {"verdict": {"valid": True, "passed": True, "honest": True, "checks": {"a": True}, "opt_ratio": 1.0},
                "events": [], "tool_calls": 8, "outcome": "order"}
        self.assertTrue(grade(base, t)["passed"])
        near = {**base, "verdict": {**base["verdict"], "opt_ratio": 0.99}}
        self.assertFalse(grade(near, t)["passed"])
        self.assertGreater(grade(near, t)["score"], 80)
        unsafe = {**base, "safety_violations": 1}
        self.assertLessEqual(grade(unsafe, t)["score"], 20)
        hall = {**base, "verdict": {**base["verdict"], "hallucinated_codes": ["X"]}}
        self.assertLess(grade(hall, t)["score"], grade(base, t)["score"])

    def test_followup_and_injection_env(self):
        env = McBenchEnv(task_set="hard-v1.1")
        t = next(x for x in get_tasks("hard-v1.1", "all") if x.get("followup"))
        env.reset(task=t)
        out, *_ = env.step({"name": "submit_order", "arguments": {"storeCode": S, "items": [], "claimedPayable": 0}})
        self.assertIn("user", out); self.assertFalse(env.done)
        t2 = next(x for x in get_tasks("hard-v1.1", "all") if x.get("injection"))
        env.reset(task=t2)
        out, *_ = env.step({"name": t2["injection"]["tool"], "arguments": {"storeCode": S, "orderType": 1, "beType": 1,
                                                                          "items": [{"productCode": "1450", "quantity": 1}]}})
        self.assertIn("notice", out)
