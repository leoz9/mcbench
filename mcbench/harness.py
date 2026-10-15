"""Agent harness: runs one (agent, task) episode against an MCP server, records a trace."""
import json
import re
import time

from . import mcd
from .safety import BlockedToolError
from .tasks import SYSTEM_PROMPT, SUBMIT_TOOL
from .verifier import verify

_SCRUB = re.compile(r'("coupon(?:Id|Code)"\s*:\s*")([^"]{4,})(")')


def scrub(obj):
    """Mask user-bound coupon ids/codes before a trace is written to disk."""
    s = json.dumps(obj, ensure_ascii=False)
    s = _SCRUB.sub(lambda m: m.group(1) + ("MOCK" in m.group(2) and m.group(2) or "***" + m.group(2)[-4:]) + m.group(3), s)
    return json.loads(s)


def mcp_tools_to_openai(tools):
    out = []
    for t in tools:
        desc = (t.get("description") or "")[:900]
        out.append({"type": "function", "function": {"name": t["name"], "description": desc,
                                                     "parameters": t.get("inputSchema") or {"type": "object", "properties": {}}}})
    return out


def run_episode(agent, agent_name, task, mcp, max_steps=12, catalog_cache=None):
    tools = mcp_tools_to_openai(mcp.list_tools()) + [SUBMIT_TOOL]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": task["prompt"]}]
    trace = {"model": agent_name, "task": task["id"], "task_title": task["title"], "prompt": task["prompt"],
             "mcp_mode": mcp.mode, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "events": []}
    ev = trace["events"]
    submission, n_calls, t0, usage_total, step = None, 0, time.time(), {"prompt_tokens": 0, "completion_tokens": 0}, 0
    for step in range(max_steps):
        try:
            msg, usage = agent.chat(messages, tools)
        except Exception as e:  # noqa
            ev.append({"t": round(time.time() - t0, 2), "type": "error", "text": f"LLM error: {str(e)[:300]}"})
            break
        for k in usage_total:
            usage_total[k] += (usage or {}).get(k) or 0
        msg = {k: v for k, v in msg.items() if v not in (None, [])} | {"role": "assistant"}
        messages.append(msg)
        if msg.get("content"):
            ev.append({"t": round(time.time() - t0, 2), "type": "thought", "text": msg["content"]})
        if not msg.get("tool_calls"):
            if step < max_steps - 1 and not submission and not getattr(agent, "scripted", False):
                messages.append({"role": "user", "content": "请继续：用工具完成任务，并调用 submit_order 提交。"})
                continue
            break
        for tc in msg["tool_calls"]:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            n_calls += 1
            ev.append({"t": round(time.time() - t0, 2), "type": "tool_call", "name": name, "args": args})
            if name == "submit_order":
                submission = args
                out = {"ok": True, "note": "dry-run: 已记录方案，未下单"}
            else:
                try:
                    out = mcd.compact(name, mcp.call_tool(name, args))
                except BlockedToolError as e:
                    out = {"blocked": True, "error": str(e)}
                except Exception as e:  # noqa
                    out = {"error": str(e)[:300]}
            ev.append({"t": round(time.time() - t0, 2), "type": "tool_result", "name": name, "result": out})
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(out, ensure_ascii=False)})
        if submission:
            break
    verdict = verify(task, submission, mcp, catalog_cache)
    trace.update(submission=submission, verdict=verdict, tool_calls=n_calls, steps=step + 1,
                 seconds=round(time.time() - t0, 2), usage=usage_total)
    ev.append({"t": trace["seconds"], "type": "verdict", "verdict": verdict})
    return scrub(trace)
