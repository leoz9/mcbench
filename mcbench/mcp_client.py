"""Minimal MCP client (Streamable HTTP, JSON-RPC 2.0) — stdlib only.

Live:  HttpMCP("https://mcp.mcd.cn", token=os.environ["MCD_MCP_TOKEN"])
Demo:  MockMCP()  (in-process fixture backend, clearly labelled MOCK)
Both are wrapped in SafeMCP which enforces the dry-run allowlist.
"""
import json
import time
import urllib.error
import urllib.request

from .safety import check_tool


class HttpMCP:
    def __init__(self, url, token=None, timeout=30, min_interval=0.15):
        self.url, self.token, self.timeout = url, token, timeout
        self.session = None
        self._id = 0
        self.min_interval = min_interval  # official limit: 600 req/min per token
        self._last = 0.0
        self.mode = "live"
        self._initialize()

    def _post(self, payload, expect_response=True):
        last = None
        for attempt in range(4):
            try:
                return self._post_once(payload, expect_response)
            except urllib.error.HTTPError as e:
                last = e
                if e.code not in (429, 500, 502, 503, 504):
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
            time.sleep(2 * (attempt + 1))
        raise last

    def _post_once(self, payload, expect_response=True):
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            self.session = r.headers.get("Mcp-Session-Id") or self.session
            if not expect_response:
                return None
            body = r.read().decode("utf-8")
            if "text/event-stream" in (r.headers.get("Content-Type") or ""):
                msg = None
                for line in body.splitlines():
                    if line.startswith("data:"):
                        d = json.loads(line[5:].strip())
                        if d.get("id") == payload.get("id"):
                            msg = d
                body_obj = msg
            else:
                body_obj = json.loads(body)
        if body_obj is None:
            raise RuntimeError("no JSON-RPC response")
        if "error" in body_obj:
            raise RuntimeError(f"MCP error: {body_obj['error']}")
        return body_obj["result"]

    def _rpc(self, method, params=None):
        self._id += 1
        return self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})

    def _initialize(self):
        self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                 "clientInfo": {"name": "mcbench", "version": "0.1.0"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_response=False)

    def list_tools(self):
        return self._rpc("tools/list").get("tools", [])

    def call_tool(self, name, args):
        res = self._rpc("tools/call", {"name": name, "arguments": args})
        texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
        joined = "\n".join(texts)
        try:
            return json.loads(joined)
        except Exception:
            return {"text": joined, "isError": res.get("isError", False)}


class MockMCP:
    def __init__(self, version=None):
        from .mock_server import MockBackend
        self.backend = MockBackend(version)
        self.mode = "mock"

    def list_tools(self):
        return self.backend.list_tools()

    def call_tool(self, name, args):
        return self.backend.call(name, args)


class SafeMCP:
    """Allowlist wrapper. create-order & friends never reach the server."""

    def __init__(self, inner):
        self.inner, self.mode = inner, inner.mode

    def list_tools(self):
        from .safety import ALLOWED_TOOLS
        return [t for t in self.inner.list_tools() if t["name"] in ALLOWED_TOOLS]

    def call_tool(self, name, args):
        check_tool(name)
        return self.inner.call_tool(name, args)
