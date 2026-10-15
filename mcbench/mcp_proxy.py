"""McBench guarded stdio MCP server (for external agent runtimes such as Codex CLI).

Wraps a McBenchEnv episode: exposes ONLY allowlisted read-only McDonald's tools +
calculate-price + local submit_order / ask_user / report_infeasible. Write tools are
never listed and are rejected (and counted as safety violations) if called by name.
After every call the full McBench trace is written to $MCBENCH_TRACE (JSON), so the
run is scored by the same verifier as every other agent.

Env: MCBENCH_TASK_ID, MCBENCH_TASK_SET (v1.0), MCBENCH_MODE (offline|live), MCBENCH_TRACE.
"""
import json
import os
import sys

from .env import McBenchEnv
from .mock_server import _fixture
from .safety import ALLOWED_TOOLS
from .tasks import LOCAL_TOOLS

RO = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}


def tool_list():
    tools = [{"name": t["name"], "description": (t.get("description") or "")[:900],
              "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}}, "annotations": RO}
             for t in _fixture("tool_schemas.json") if t["name"] in ALLOWED_TOOLS]
    for lt in LOCAL_TOOLS:
        f = lt["function"]
        tools.append({"name": f["name"], "description": f["description"], "inputSchema": f["parameters"], "annotations": RO})
    return tools


def main():
    mode = os.environ.get("MCBENCH_MODE", "offline")
    task_id = os.environ.get("MCBENCH_TASK_ID")
    trace_path = os.environ.get("MCBENCH_TRACE")
    state = {}

    def env():
        if "env" not in state:  # lazy: live connection opened on first tool call
            e = McBenchEnv(mode=mode, task_set=os.environ.get("MCBENCH_TASK_SET", "v1.0"))
            e.reset(task_id=task_id) if task_id else e.reset(task_id="budget-solo")
            state["env"] = e
        return state["env"]

    def dump():
        if trace_path and "env" in state:
            with open(trace_path, "w", encoding="utf-8") as f:
                json.dump(state["env"].trace, f, ensure_ascii=False)

    tools = tool_list()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid, method = req.get("id"), req.get("method")
        if rid is None:
            continue
        err = None
        if method == "initialize":
            result = {"protocolVersion": (req.get("params") or {}).get("protocolVersion", "2025-03-26"),
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "mcbench-guarded-mcd", "version": "1.0"}}
        elif method == "tools/list":
            result = {"tools": tools}
        elif method == "tools/call":
            p = req.get("params") or {}
            e = env()
            if e.done:
                out = {"error": "episode already finished"}
            else:
                out, _r, term, trunc, _info = e.step({"name": p.get("name"), "arguments": p.get("arguments") or {}})
                if not (term or trunc):
                    pass
            dump()
            result = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                      "isError": bool(out.get("blocked") or out.get("error"))}
        elif method == "ping":
            result = {}
        elif method in ("resources/list", "resources/templates/list", "prompts/list"):
            result = {"resources/list": {"resources": []}, "resources/templates/list": {"resourceTemplates": []},
                      "prompts/list": {"prompts": []}}[method]
        else:
            err = {"code": -32601, "message": "method not found"}
        msg = {"jsonrpc": "2.0", "id": rid}
        msg.update({"error": err} if err else {"result": result})
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
