"""Agent harness: runs one (agent, task) episode against an MCP server, records a trace."""
import json
import time

from .safety import BlockedToolError
from .tasks import SYSTEM_PROMPT, SUBMIT_TOOL
from .verifier import verify


def mcp_tools_to_openai(tools):
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t.get("inputSchema") or {"type": "object", "properties": {}}}}
            for t in tools]


def run_episode(agent, agent_name, task, mcp, max_steps=16):
    tools = mcp_tools_to_openai(mcp.list_tools()) + [SUBMIT_TOOL]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": task["prompt"]}]
    trace = {"model": agent_name, "task": task["id"], "task_title": task["title"], "prompt": task["prompt"],
             "mcp_mode": mcp.mode, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "events": []}
    ev = trace["events"]
    submission, n_calls, t0 = None, 0, time.time()
    for step in range(max_steps):
        msg, usage = agent.chat(messages, tools)
        messages.append(msg)
        if msg.get("content"):
            ev.append({"t": round(time.time() - t0, 2), "type": "thought", "text": msg["content"]})
        if not msg.get("tool_calls"):
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
                    out = mcp.call_tool(name, args)
                except BlockedToolError as e:
                    out = {"blocked": True, "error": str(e)}
                except Exception as e:  # noqa
                    out = {"error": str(e)}
            ev.append({"t": round(time.time() - t0, 2), "type": "tool_result", "name": name, "result": out})
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(out, ensure_ascii=False)})
        if submission:
            break
    verdict = verify(task, submission, mcp)
    trace.update(submission=submission, verdict=verdict, tool_calls=n_calls, steps=step + 1,
                 seconds=round(time.time() - t0, 2))
    ev.append({"t": trace["seconds"], "type": "verdict", "verdict": verdict})
    return trace
