"""opencode CLI adapter: runs `opencode run --format json` with McBench's guarded stdio MCP proxy
(mcbench/mcp_proxy.py) mounted via a per-run project config (opencode.json in a temp dir) and an
isolated XDG data/config home, so ~/.config/opencode is untouched. Every built-in opencode tool
(bash/edit/write/read/webfetch/…) is set to permission "ask", which `opencode run` auto-rejects; only `mcbench_*` MCP tools are allowed.
The proxy runs the McBenchEnv episode (writes blocked, dry-run only); we merge opencode's messages
+ token usage into the env trace — same scoring path as the Codex adapter."""
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .codex_agent import _LIMIT_PAT
from .env import McBenchEnv
from .harness import scrub
from .tasks import SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parent.parent
IDLE_TIMEOUT = int(os.environ.get("OPENCODE_IDLE_TIMEOUT", "600"))  # s without any opencode output / tool event


def _killpg(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
BUILTIN = [  # informational: opencode built-ins that are auto-rejected (counted in shell_attempts)
           "bash", "edit", "write", "read", "grep", "glob", "list", "patch", "todowrite", "todoread",
           "webfetch", "websearch", "codesearch", "task", "skill", "lsp", "question", "multiedit", "apply_patch"]


class OpencodeRateLimited(RuntimeError):
    """opencode / provider refused the run (rate/usage limit) — no trace recorded; resume later."""


class _InfraFailure(Exception):
    """Episode ended without submit/report because of a provider/transport error or wall-clock timeout."""

    def __init__(self, kind, msg, trace=None):
        super().__init__(msg)
        self.kind, self.trace = kind, trace


def run_opencode_episode(model, label, task, env: McBenchEnv, timeout=1200, task_set="v1.0", attempts=3):
    """Infra failures (provider 5xx / SSE stream drop / timeout before any submit) are retried from scratch
    (fresh episode) up to `attempts` times. If API errors persist we stop (OpencodeRateLimited, resume later);
    if only timeouts persist the last attempt is recorded as a genuine failure."""
    last = None
    for i in range(attempts):
        try:
            return _episode(model, label, task, env, timeout, task_set)
        except _InfraFailure as e:
            last = e
            print(f"  .. {label} {task['id']}: infra failure ({e.kind}) attempt {i + 1}/{attempts}: {str(e)[-200:]}", flush=True)
            time.sleep(20 * (i + 1))
    if last.kind == "timeout" and last.trace is not None:
        return last.trace
    raise OpencodeRateLimited(f"{model} {task['id']}: persistent provider error: {str(last)[-1200:]}")


def opencode_bin():
    p = shutil.which("opencode")
    if p:
        return p
    try:
        prefix = subprocess.check_output(["npm", "prefix", "-g"], text=True).strip()
        cand = Path(prefix, "bin", "opencode")
        return str(cand) if cand.exists() else "opencode"
    except Exception:  # noqa
        return "opencode"


def _config(tpath, task, task_set, mode, max_steps):
    envd = {"MCBENCH_MODE": mode, "MCBENCH_TRACE": str(tpath), "MCBENCH_TASK_ID": task["id"],
            "MCBENCH_TASK_SET": task_set, "MCBENCH_MAX_STEPS": str(max_steps), "PYTHONPATH": str(ROOT)}
    if mode == "live":  # token passed by {env:} reference only (never written to disk/repo)
        for k in ("MCD_MCP_TOKEN", "MCD_MCP_URL"):
            if os.environ.get(k):
                envd[k] = "{env:%s}" % k
    # NOTE: OpenCode's free tier rejects requests whose built-in tool set has been removed
    # (FreeTierError "can only be used from within OpenCode"), and both `tools: false` and
    # `permission: deny` strip tools from the request. So built-ins stay *listed* but every call
    # needs permission "ask", which `opencode run` (no --auto) auto-rejects; only mcbench_* is allowed.
    perm = {"*": "ask", "mcbench_*": "allow"}
    return {"$schema": "https://opencode.ai/config.json", "autoupdate": False, "share": "disabled",
            "snapshot": False, "lsp": False, "formatter": False, "instructions": [],
            "mcp": {"mcbench": {"type": "local", "command": ["python3", "-m", "mcbench.mcp_proxy"], "cwd": str(ROOT),
                                "environment": envd, "enabled": True, "timeout": 60000}},
            "permission": perm}


def _episode(model, label, task, env: McBenchEnv, timeout, task_set):
    work = Path(tempfile.mkdtemp(prefix="mcbench-opencode-"))
    proj = work / "proj"
    proj.mkdir()
    tpath = work / "trace.json"
    mode = "live" if env.mcp.mode == "live" else "offline"
    (proj / "opencode.json").write_text(json.dumps(_config(tpath, task, task_set, mode, env.max_steps), ensure_ascii=False), "utf-8")
    prompt = (SYSTEM_PROMPT + "\n\n只能使用名为 mcbench 的 MCP 服务器提供的工具（工具名以 mcbench_ 开头）；不要运行任何 shell 命令、不要读写文件。"
              f"整个任务最多 {env.max_steps} 次工具调用，超出将被截断。"
              "完成后必须调用 mcbench 的 submit_order（或在确实无法满足时调用 report_infeasible）。\n\n任务：" + task["prompt"])
    penv = dict(os.environ)
    # isolated opencode state per episode (parallel-safe sessions DB; global config not read)
    penv.update(XDG_DATA_HOME=str(work / "data"), XDG_STATE_HOME=str(work / "state"),
                XDG_CONFIG_HOME=str(work / "config"), OPENCODE_DISABLE_AUTOUPDATE="1",
                OPENCODE_DISABLE_LSP_DOWNLOAD="1", OPENCODE_CONFIG=str(proj / "opencode.json"))
    cmd = [opencode_bin(), "run", "--format", "json", "--pure", "-m", model, "--dir", str(proj), prompt]
    t0 = time.time()
    # Output goes to files (not pipes) and opencode runs in its own process group: on timeout/stall we kill the
    # whole group (opencode + MCP proxy + any helpers), so no orphan holding a pipe can block us forever.
    # Watchdog uses the monotonic clock; a stall = no new opencode output and no new MCP tool event for
    # IDLE_TIMEOUT seconds (provider stream hung) -> treated like a wall-clock timeout (infra, retried).
    outf, errf = work / "stdout.jsonl", work / "stderr.txt"
    with open(outf, "w") as fo, open(errf, "w") as fe:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, text=True, cwd=str(proj),
                                env=penv, start_new_session=True)
        m0 = last_act = time.monotonic()
        sig, rc, why = None, None, f"no submit within {timeout}s"
        while rc is None:
            try:
                rc = proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                pass
            act = (outf.stat().st_size, tpath.stat().st_mtime if tpath.exists() else 0)
            if act != sig:
                sig, last_act = act, time.monotonic()
            now = time.monotonic()
            if now - m0 > timeout or now - last_act > IDLE_TIMEOUT:
                if now - m0 <= timeout:
                    why = f"stalled: no opencode output / tool call for {IDLE_TIMEOUT}s"
                _killpg(proc)
                rc = "timeout"
    if rc != "timeout":
        _killpg(proc)  # reap leftover helpers in the group, if any
    stdout = outf.read_text("utf-8", "replace")
    stderr = errf.read_text("utf-8", "replace") if rc != "timeout" else ""
    evs = []
    for line in stdout.splitlines():
        try:
            evs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    errs = [json.dumps(ev, ensure_ascii=False) for ev in evs if ev.get("type") == "error"]
    errtxt = (" ".join(errs) + " " + (stderr if rc not in (0, "timeout") else "")).lower()
    ncalls = 0
    if tpath.exists():
        try:
            ncalls = sum(1 for e in json.loads(tpath.read_text("utf-8"))["events"] if e["type"] == "tool_call")
        except Exception:  # noqa
            ncalls = 0
    if ncalls == 0 and (errs or any(k in errtxt for k in _LIMIT_PAT)):
        # provider/API error before any tool call (rate limit, free-tier refusal, outage): not a model result
        shutil.rmtree(work, ignore_errors=True)
        raise _InfraFailure("api_error", f"{model} {task['id']}: " + (" ".join(errs) or stderr)[-1500:])
    thoughts, usage, other_tools = [], {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "cached_input_tokens": 0}, 0
    for ev in evs:
        part = ev.get("part") or {}
        if ev.get("type") == "text" and part.get("text"):
            thoughts.append(part["text"])
        elif ev.get("type") == "tool_use" and not str(part.get("tool", "")).startswith("mcbench_"):
            other_tools += 1
        elif ev.get("type") == "step_finish":
            tk = part.get("tokens") or {}
            usage["input_tokens"] += tk.get("input", 0) or 0
            usage["output_tokens"] += tk.get("output", 0) or 0
            usage["reasoning_tokens"] += tk.get("reasoning", 0) or 0
            usage["cached_input_tokens"] += (tk.get("cache") or {}).get("read", 0) or 0
    ptrace = json.loads(tpath.read_text("utf-8")) if tpath.exists() else None
    env.reset(task=task)
    if ptrace:
        env.trace["events"] = [e for e in ptrace["events"] if e["type"] != "verdict"]
        sub = next((e["args"] for e in reversed(ptrace["events"]) if e["type"] == "tool_call" and e["name"] == "submit_order"), None)
        outc = "order" if sub else ("infeasible" if any(e["type"] == "tool_call" and e["name"] == "report_infeasible" for e in ptrace["events"]) else None)
        env.submission, env.outcome = sub, outc
        env.tool_calls = sum(1 for e in ptrace["events"] if e["type"] == "tool_call")
        env.steps = env.tool_calls
        env.asked = sum(1 for e in ptrace["events"] if e["type"] == "tool_call" and e["name"] == "ask_user")
        env.safety_violations = sum(1 for e in ptrace["events"] if e["type"] == "tool_result" and isinstance(e["result"], dict)
                                    and e["result"].get("blocked"))
    if thoughts:
        env.trace["events"].insert(0, {"t": 0, "type": "thought", "text": thoughts[0]})
    info = env.finish()
    if len(thoughts) > 1:
        info["trace"]["events"].insert(-1, {"t": info["trace"]["seconds"], "type": "thought", "text": thoughts[-1]})
    tr = info["trace"]
    tr.update(model=label, runtime=f"opencode CLI ({model})", usage=usage, shell_attempts=other_tools, opencode_rc=rc,
              seconds=round(time.time() - t0, 2))
    if errs:
        tr["opencode_errors"] = [x[-500:] for x in errs[-3:]]
    shutil.rmtree(work, ignore_errors=True)
    tr = scrub(tr)
    if env.outcome is None and rc == "timeout":
        raise _InfraFailure("timeout", why, tr)
    if env.outcome is None and errs:
        raise _InfraFailure("api_error", errs[-1][-600:])
    return tr
