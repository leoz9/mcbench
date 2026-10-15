"""Run a McBench task through Codex CLI (`codex exec`) as the agent runtime.

Codex sees McBench's guarded stdio MCP server (mcbench.mcp_proxy) registered via
per-run `-c mcp_servers.mcbench.*` overrides (nothing is written to ~/.codex).
Write tools are not exposed and are rejected inside the proxy. The proxy logs
every tool call to JSONL; we rebuild a standard McBench trace from it and score it
with the same verifier as every other agent.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .harness import scrub
from .tasks import SYSTEM_PROMPT
from .verifier import verify

ROOT = Path(__file__).resolve().parent.parent


def codex_bin():
    p = shutil.which("codex")
    if p:
        return p
    try:
        prefix = subprocess.check_output(["npm", "prefix", "-g"], text=True).strip()
        cand = Path(prefix, "bin", "codex")
        return str(cand) if cand.exists() else "codex"
    except Exception:  # noqa
        return "codex"


def run_codex_episode(model, label, task, mcp, live=True, timeout=900, catalog_cache=None):
    work = Path(tempfile.mkdtemp(prefix="mcbench-codex-"))
    tlog = work / "tools.jsonl"
    prompt = (SYSTEM_PROMPT + "\n\n只能使用名为 mcbench 的 MCP 服务器提供的工具；不要运行任何 shell 命令、不要读写文件。"
              "完成后必须调用 mcbench 的 submit_order。\n\n任务：" + task["prompt"])
    env_tbl = '{MCBENCH_MODE="%s",MCBENCH_TRACE="%s"}' % ("live" if live else "mock", tlog)
    cmd = [codex_bin(), "exec", "--skip-git-repo-check", "--ephemeral", "--json", "-s", "read-only", "-C", str(work),
           "-m", model,
           "-c", 'approval_policy="never"',
           "-c", 'mcp_servers.mcbench.command="python3"',
           "-c", 'mcp_servers.mcbench.args=["-m","mcbench.mcp_proxy"]',
           "-c", f'mcp_servers.mcbench.cwd="{ROOT}"',
           "-c", f"mcp_servers.mcbench.env={env_tbl}",
           "-c", 'mcp_servers.mcbench.env_vars=["MCD_MCP_TOKEN","MCD_MCP_URL"]',
           "-c", 'mcp_servers.mcbench.default_tools_approval_mode="approve"',
           "-c", "mcp_servers.mcbench.tool_timeout_sec=120",
           "-c", "mcp_servers.mcbench.startup_timeout_sec=60",
           prompt]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ})
        stdout, rc = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as e:
        stdout, rc = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout"
    events, usage, shell_cmds = [], {}, 0
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        it = ev.get("item") or {}
        if ev.get("type") == "item.completed" and it.get("type") == "agent_message":
            events.append({"t": None, "type": "thought", "text": it.get("text", "")})
        elif ev.get("type") == "item.completed" and it.get("type") == "command_execution":
            shell_cmds += 1
            events.append({"t": None, "type": "thought", "text": f"[codex shell attempt, sandbox read-only] {it.get('command')}"})
        elif ev.get("type") == "item.completed" and it.get("type") == "mcp_tool_call":
            events.append({"t": None, "type": "_mcp", "tool": it.get("tool")})
        elif ev.get("type") == "turn.completed":
            usage = ev.get("usage") or {}
    proxy = [json.loads(l) for l in tlog.read_text("utf-8").splitlines()] if tlog.exists() else []
    # interleave: thoughts in codex order; tool call/result pairs from the proxy (authoritative)
    merged, pi = [], 0
    for e in events:
        if e["type"] == "_mcp":
            while pi < len(proxy):
                merged.append(proxy[pi]); pi += 1
                if merged[-1]["type"] == "tool_result":
                    break
        else:
            merged.append(e)
    merged += proxy[pi:]
    submission, n_calls = None, 0
    for e in merged:
        if e["type"] == "tool_call":
            n_calls += 1
            if e["name"] == "submit_order":
                submission = e["args"]
    secs = round(time.time() - t0, 2)
    verdict = verify(task, submission, mcp, catalog_cache)
    for e in merged:
        if e.get("t") is None:
            e["t"] = 0
    merged.append({"t": secs, "type": "verdict", "verdict": verdict})
    trace = {"model": label, "runtime": f"Codex CLI ({model})", "task": task["id"], "task_title": task["title"],
             "prompt": task["prompt"], "mcp_mode": mcp.mode, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
             "events": merged, "submission": submission, "verdict": verdict, "tool_calls": n_calls,
             "shell_attempts": shell_cmds, "steps": None, "seconds": secs, "usage": usage, "codex_rc": rc}
    shutil.rmtree(work, ignore_errors=True)
    return scrub(trace)
