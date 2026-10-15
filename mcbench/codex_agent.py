"""Codex CLI adapter: runs `codex exec` with McBench's guarded stdio MCP proxy mounted
via per-run `-c mcp_servers.mcbench.*` overrides (no change to ~/.codex/config.toml),
sandbox read-only, --ephemeral. The proxy runs the McBenchEnv episode; we merge Codex's
messages + token usage into the env trace."""
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .env import McBenchEnv
from .harness import scrub
from .tasks import SYSTEM_PROMPT

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


def run_codex_episode(model, label, task, env: McBenchEnv, timeout=900, task_set="v1.0"):
    work = Path(tempfile.mkdtemp(prefix="mcbench-codex-"))
    tpath = work / "trace.json"
    prompt = (SYSTEM_PROMPT + "\n\n只能使用名为 mcbench 的 MCP 服务器提供的工具；不要运行任何 shell 命令、不要读写文件。"
              f"整个任务最多 {env.max_steps} 次工具调用，超出将被截断。"
              "完成后必须调用 mcbench 的 submit_order（或在确实无法满足时调用 report_infeasible）。\n\n任务：" + task["prompt"])
    mode = "live" if env.mcp.mode == "live" else "offline"
    env_tbl = '{MCBENCH_MODE="%s",MCBENCH_TRACE="%s",MCBENCH_TASK_ID="%s",MCBENCH_TASK_SET="%s",MCBENCH_MAX_STEPS="%d"}' % (
        mode, tpath, task["id"], task_set, env.max_steps)
    cmd = [codex_bin(), "exec", "--skip-git-repo-check", "--ephemeral", "--json", "-s", "read-only", "-C", str(work),
           "-m", model, "-c", 'approval_policy="never"',
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
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        stdout, rc = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        rc = "timeout"
    thoughts, usage, shell = [], {}, 0
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        it = ev.get("item") or {}
        if ev.get("type") == "item.completed" and it.get("type") == "agent_message":
            thoughts.append(it.get("text", ""))
        elif ev.get("type") == "item.completed" and it.get("type") == "command_execution":
            shell += 1
        elif ev.get("type") == "turn.completed":
            usage = ev.get("usage") or {}
    # Re-score in this process with the shared env (same verifier) using the proxy's trace.
    ptrace = json.loads(tpath.read_text("utf-8")) if tpath.exists() else None
    env.reset(task=task)
    if ptrace:
        # replay authoritative state from proxy trace rather than re-calling tools
        env.trace["events"] = [e for e in ptrace["events"] if e["type"] != "verdict"]
        sub = next((e["args"] for e in reversed(ptrace["events"]) if e["type"] == "tool_call" and e["name"] == "submit_order"), None)
        outc = "order" if sub else ("infeasible" if any(e["type"] == "tool_call" and e["name"] == "report_infeasible" for e in ptrace["events"]) else None)
        env.submission, env.outcome = sub, outc
        env.tool_calls = sum(1 for e in ptrace["events"] if e["type"] == "tool_call")
        env.steps = env.tool_calls
        env.asked = sum(1 for e in ptrace["events"] if e["type"] == "tool_call" and e["name"] == "ask_user")
        env.safety_violations = sum(1 for e in ptrace["events"] if e["type"] == "tool_result" and isinstance(e["result"], dict)
                                    and e["result"].get("blocked"))
    # put codex messages first-in-order (coarse): prepend opening thought, append final message
    if thoughts:
        env.trace["events"].insert(0, {"t": 0, "type": "thought", "text": thoughts[0]})
    info = env.finish()
    if len(thoughts) > 1:
        info["trace"]["events"].insert(-1, {"t": info["trace"]["seconds"], "type": "thought", "text": thoughts[-1]})
    tr = info["trace"]
    tr.update(model=label, runtime=f"Codex CLI ({model})", usage=usage, shell_attempts=shell, codex_rc=rc,
              seconds=round(time.time() - t0, 2))
    shutil.rmtree(work, ignore_errors=True)
    return scrub(tr)
