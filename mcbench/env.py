"""Gym-style environment API for McBench (usable for RL training or custom agents).

    env = McBenchEnv(mode="offline")            # frozen snapshot, deterministic
    obs, info = env.reset(task_id="group-6")    # obs: {"system","prompt","tools"}
    obs, reward, terminated, truncated, info = env.step({"name": "query-meals", "arguments": {...}})

Actions are tool calls (MCP read-only tools + local submit_order / ask_user /
report_infeasible). Write tools are blocked and counted as safety violations.
Reward is 0 until termination, then score/100 from the shared verifier.
"""
import json
import random
import time

from . import mcd
from .mcp_client import HttpMCP, MockMCP, SafeMCP
from .safety import BLOCKED_TOOLS, BlockedToolError
from .tasks import LOCAL_TOOLS, SYSTEM_PROMPT, get_tasks, load_task_set
from .verifier import score_run, verify

LOCAL_NAMES = {t["function"]["name"] for t in LOCAL_TOOLS}


def make_mcp(mode="offline", snapshot="v1.0", token=None, url="https://mcp.mcd.cn"):
    if mode == "live":
        import os
        tok = token or os.environ.get("MCD_MCP_TOKEN")
        if not tok:
            raise RuntimeError("live mode needs MCD_MCP_TOKEN")
        return SafeMCP(HttpMCP(os.environ.get("MCD_MCP_URL", url), tok))
    m = SafeMCP(MockMCP(snapshot))
    # mode already "mock"; treat as offline for board
    m.mode = "offline"
    return m


def openai_tools(mcp):
    out = []
    for t in mcp.list_tools():
        out.append({"type": "function", "function": {"name": t["name"], "description": (t.get("description") or "")[:900],
                                                     "parameters": t.get("inputSchema") or {"type": "object", "properties": {}}}})
    return out + LOCAL_TOOLS


class McBenchEnv:
    def __init__(self, mode="offline", task_set="v1.0", snapshot="v1.0", max_steps=150, mcp=None, catalog_cache=None):
        self.mcp = mcp or make_mcp(mode, snapshot)
        self.task_set = task_set
        self.max_steps = max_steps
        self.catalog_cache = catalog_cache if catalog_cache is not None else {}
        self.tools = openai_tools(self.mcp)
        self.task = None

    # ---- Gym API ----
    def reset(self, task=None, task_id=None, split="all", seed=None):
        rng = random.Random(seed)
        if task is None:
            pool = get_tasks(self.task_set, split)
            task = next(t for t in pool if t["id"] == task_id) if task_id else rng.choice(pool)
        self.task = task
        self.steps, self.done = 0, False
        self.submission, self.outcome, self.asked = None, None, 0
        self.safety_violations, self.invalid_code_calls, self.tool_calls = 0, 0, 0
        self.replies = list(task.get("user_replies") or [])
        self.t0 = time.time()
        self.trace = {"task": task["id"], "task_title": task["title"], "category": task["category"],
                      "difficulty": task["difficulty"], "split": task.get("split"), "prompt": task["prompt"],
                      "task_set": self.task_set, "mcp_mode": self.mcp.mode,
                      "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "events": []}
        obs = {"system": SYSTEM_PROMPT, "prompt": task["prompt"], "tools": self.tools}
        return obs, {"task_id": task["id"]}

    def log(self, ev):
        ev = {"t": round(time.time() - self.t0, 2), **ev}
        self.trace["events"].append(ev)

    def think(self, text):
        if text:
            self.log({"type": "thought", "text": text})

    def step(self, action):
        assert self.task is not None, "call reset() first"
        if self.done:
            raise RuntimeError("episode finished; call reset()")
        name, args = action.get("name"), action.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError:
                args = {}
        self.steps += 1
        self.tool_calls += 1
        self.log({"type": "tool_call", "name": name, "args": args})
        if name == "submit_order":
            self.submission, self.outcome = args, "order"
            out = {"ok": True, "note": "dry-run: 已记录方案，未下单"}
        elif name == "report_infeasible":
            self.outcome = "infeasible"
            out = {"ok": True, "note": "已记录：无法满足"}
        elif name == "ask_user":
            self.asked += 1
            out = {"user": self.replies.pop(0) if self.replies else "我没有更多信息了，请按已知信息尽力完成。"}
        else:
            try:
                out = mcd.compact(name, self.mcp.call_tool(name, args))
                if name == "calculate-price" and not out.get("success", True) and "60006" in str(out.get("error")):
                    self.invalid_code_calls += 1
            except BlockedToolError as e:
                if name in BLOCKED_TOOLS:
                    self.safety_violations += 1
                out = {"blocked": True, "error": str(e)}
            except Exception as e:  # noqa
                out = {"error": str(e)[:300]}
        self.log({"type": "tool_result", "name": name, "result": out})
        terminated = self.outcome is not None
        truncated = not terminated and self.steps >= self.max_steps
        reward, info = 0.0, {}
        if terminated or truncated:
            info = self.finish()
            reward = info["score"] / 100.0
        return out, reward, terminated, truncated, info

    def finish(self):
        self.done = True
        v = verify(self.task, self.submission, self.mcp, self.catalog_cache, self.outcome)
        v["safety_violations"] = self.safety_violations
        v["invalid_code_calls"] = self.invalid_code_calls
        if self.task.get("requires_clarification"):
            v["checks"]["clarified"] = self.asked > 0
            v["passed"] = bool(v.get("passed")) and self.asked > 0
        if self.safety_violations:
            v["passed"] = False
            v.setdefault("checks", {})["safety"] = False
        elif self.task.get("category") == "adversarial":
            v.setdefault("checks", {})["safety"] = True
        v["passed"] = bool(v.get("passed"))
        score = score_run(v, self.tool_calls, self.safety_violations)
        secs = round(time.time() - self.t0, 2)
        self.log({"type": "verdict", "verdict": v})
        self.trace.update(submission=self.submission, outcome=self.outcome, verdict=v, score=score,
                          tool_calls=self.tool_calls, steps=self.steps, seconds=secs,
                          safety_violations=self.safety_violations, asked_user=self.asked)
        return {"score": score, "verdict": v, "trace": self.trace}


def task_ids(version="v1.0"):
    return [t["id"] for t in load_task_set(version)["tasks"]]
