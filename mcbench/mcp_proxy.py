"""McBench guarded stdio MCP server (for external agent runtimes such as Codex CLI).

Exposes ONLY McBench's allowlisted read-only McDonald's tools + calculate-price +
a local dry-run `submit_order`. Write tools are never listed and are rejected by
SafeMCP even if called by name. Every call is appended to $MCBENCH_TRACE (JSONL)
so McBench can rebuild a trace and score it with the same verifier.

Run:  MCBENCH_MODE=live|mock MCBENCH_TRACE=/tmp/t.jsonl python -m mcbench.mcp_proxy
"""
import json
import os
import sys
import time

from . import mcd
from .mcp_client import HttpMCP, MockMCP, SafeMCP
from .safety import BlockedToolError
from .tasks import SUBMIT_TOOL

T0 = time.time()


def log(rec):
    path = os.environ.get("MCBENCH_TRACE")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time() - T0, 2), **rec}, ensure_ascii=False) + "\n")


def main():
    mode = os.environ.get("MCBENCH_MODE", "mock")
    from .safety import ALLOWED_TOOLS
    from .mock_server import _fixture
    # Tool schemas recorded from the real server (identical in live/mock); the live
    # connection is opened lazily on first call so startup is instant and robust.
    schemas = [t for t in _fixture("tool_schemas.json") if t["name"] in ALLOWED_TOOLS]
    state = {}

    def get_mcp():
        if "mcp" not in state:
            inner = HttpMCP(os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn"), os.environ["MCD_MCP_TOKEN"]) \
                if mode == "live" else MockMCP()
            state["mcp"] = SafeMCP(inner)
        return state["mcp"]

    class _L:
        def list_tools(self):
            return schemas
    mcp_l = _L()
    tools = [{"name": t["name"], "description": (t.get("description") or "")[:900],
              "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}},
              "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}
             for t in mcp_l.list_tools()]
    sf = SUBMIT_TOOL["function"]
    tools.append({"name": sf["name"], "description": sf["description"], "inputSchema": sf["parameters"],
                  "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}})
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
            continue  # notification
        if method == "initialize":
            pv = (req.get("params") or {}).get("protocolVersion", "2025-03-26")
            result = {"protocolVersion": pv, "capabilities": {"tools": {}},
                      "serverInfo": {"name": "mcbench-guarded-mcd", "version": "0.2"}}
        elif method == "tools/list":
            result = {"tools": tools}
        elif method == "tools/call":
            p = req.get("params") or {}
            name, args = p.get("name"), p.get("arguments") or {}
            log({"type": "tool_call", "name": name, "args": args})
            if name == "submit_order":
                out = {"ok": True, "note": "dry-run: 已记录方案，未下单"}
            else:
                try:
                    from .safety import check_tool
                    check_tool(name)  # enforce block before any network I/O
                    out = mcd.compact(name, get_mcp().call_tool(name, args))
                except BlockedToolError as e:
                    out = {"blocked": True, "error": str(e)}
                except Exception as e:  # noqa
                    out = {"error": str(e)[:300]}
            log({"type": "tool_result", "name": name, "result": out})
            result = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                      "isError": bool(out.get("blocked") or out.get("error"))}
        elif method == "ping":
            result = {}
        elif method in ("resources/list", "resources/templates/list", "prompts/list"):
            result = {"resources/list": {"resources": []}, "resources/templates/list": {"resourceTemplates": []},
                      "prompts/list": {"prompts": []}}[method]
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}}) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
