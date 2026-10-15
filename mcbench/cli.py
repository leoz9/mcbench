import argparse
import json
import os
import sys
from pathlib import Path

from . import leaderboard as lb
from .harness import run_episode
from .mcp_client import HttpMCP, MockMCP, SafeMCP
from .tasks import TASKS, TASK_BY_ID

ROOT = Path(__file__).resolve().parent.parent


def make_mcp(live):
    if live:
        tok = os.environ.get("MCD_MCP_TOKEN")
        if not tok:
            sys.exit("缺少 MCD_MCP_TOKEN 环境变量（在 open.mcd.cn/mcp 申请）。不想用 Token？用 `mcbench demo`。")
        return SafeMCP(HttpMCP(os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn"), tok))
    return SafeMCP(MockMCP())


def run_all(agents, tasks, mcp, out_dir, max_steps=12, codex=None):
    (Path(out_dir) / "traces").mkdir(parents=True, exist_ok=True)
    cache = {}
    jobs = [(n, f, None) for n, f in agents.items()] + [(m["name"], None, m) for m in (codex or [])]
    for name, factory, cm in jobs:
        for t in tasks:
            dst = Path(out_dir, "traces", f"{name}__{t['id']}.json")
            if dst.exists():
                print(f"  {name:<16} {t['id']:<14} (已有轨迹，跳过)")
                continue
            if cm:
                from .codex_agent import run_codex_episode
                tr = run_codex_episode(cm["model"], name, t, mcp, live=mcp.mode == "live", catalog_cache=cache)
            else:
                tr = run_episode(factory(), name, t, mcp, max_steps=max_steps, catalog_cache=cache)
            Path(out_dir, "traces", f"{name}__{t['id']}.json").write_text(json.dumps(tr, ensure_ascii=False, indent=1), "utf-8")
            v = tr["verdict"]
            print(f"  {name:<16} {t['id']:<14} {'PASS' if v.get('passed') else 'FAIL'}  ¥{v.get('payable', '-')}  calls={tr['tool_calls']}")
    board = lb.build(out_dir)
    lb.print_board(board)
    return board


def cmd_demo(a):
    from .demo_agents import DEMO_AGENTS, ScriptedAgent
    print("🍔 McBench DEMO —— 模拟 MCP（MOCK 数据）+ 脚本示例 Agent，无需 Token / API Key，绝不下单\n")
    agents = {n: (lambda p=p: ScriptedAgent(p)) for n, p in DEMO_AGENTS.items()}
    out = Path(a.out)
    board = run_all(agents, TASKS, make_mcp(False), out)
    web = ROOT / "web" if (ROOT / "web" / "index.html").exists() else None
    if web:
        lb.export_web(out, web, "data-demo")
    from .replay import replay
    replay(out / "traces" / "demo-hasty__best-coupon.json")
    replay(out / "traces" / "demo-planner__best-coupon.json")
    if not a.no_video:
        try:
            from .mccut import render
            scores = {r["model"]: r["score"] for r in board["runs"] if r["task"] == "best-coupon"}
            v = render(out / "traces/demo-planner__best-coupon.json", out / "traces/demo-hasty__best-coupon.json",
                       out / "battle_best-coupon.mp4", scores, mock=True)
            print(f"🎬 对决视频：{v}")
        except Exception as e:  # noqa
            print(f"(跳过视频渲染：{e})")
    if web:
        print(f"📊 网页版：python -m http.server -d {web} 8000 → http://localhost:8000/?demo （真实榜单：去掉 ?demo）")


def cmd_run(a):
    from .llm import OpenAICompatChat
    agents = {}
    if a.demo_agents:
        from .demo_agents import DEMO_AGENTS, ScriptedAgent
        agents = {n: (lambda p=p: ScriptedAgent(p)) for n, p in DEMO_AGENTS.items()}
    cfg = json.load(open(a.config, encoding="utf-8")) if a.config else {"models": []}
    codex = [m for m in cfg["models"] if m.get("provider") == "codex"]
    for m in [m for m in cfg["models"] if m.get("provider") != "codex"]:
        agents[m["name"]] = (lambda m=m: OpenAICompatChat(m["model"], m["base_url"], m.get("api_key_env", "OPENAI_API_KEY"),
                                                         m.get("temperature", 0.0), extra=m.get("extra")))
    tasks = [TASK_BY_ID[t] for t in a.tasks.split(",")] if a.tasks else TASKS
    run_all(agents, tasks, make_mcp(a.live), a.out, a.max_steps, codex)
    lb.export_web(a.out, ROOT / "web") if a.export else None


def cmd_cut(a):
    from .mccut import render
    board = json.load(open(Path(a.trace_a).parent.parent / "leaderboard.json", encoding="utf-8"))
    ta = json.load(open(a.trace_a, encoding="utf-8"))
    scores = {r["model"]: r["score"] for r in board["runs"] if r["task"] == ta["task"]}
    print(render(a.trace_a, a.trace_b, a.out, scores, mock=board["is_mock"]))


def main():
    p = argparse.ArgumentParser(prog="mcbench", description="McBench：大模型点麦当劳擂台")
    s = p.add_subparsers(dest="cmd", required=True)
    d = s.add_parser("demo", help="一键演示（MOCK，无需 Token/Key）"); d.add_argument("--out", default="runs/demo"); d.add_argument("--no-video", action="store_true")
    r = s.add_parser("run", help="用真实大模型跑分"); r.add_argument("--config")
    r.add_argument("--live", action="store_true", help="连接真实 https://mcp.mcd.cn（需 MCD_MCP_TOKEN）")
    r.add_argument("--tasks"); r.add_argument("--out", default="runs/latest"); r.add_argument("--export", action="store_true")
    r.add_argument("--demo-agents", action="store_true", help="用脚本示例 Agent 代替大模型（测试 live 链路）")
    r.add_argument("--max-steps", type=int, default=12)
    b = s.add_parser("leaderboard"); b.add_argument("run_dir")
    rp = s.add_parser("replay"); rp.add_argument("trace"); rp.add_argument("--speed", type=float, default=0.0)
    c = s.add_parser("cut", help="McCut：渲染竖屏对决视频"); c.add_argument("trace_a"); c.add_argument("trace_b"); c.add_argument("-o", "--out", default="battle.mp4")
    e = s.add_parser("export-web"); e.add_argument("run_dir")
    s.add_parser("tasks")
    m = s.add_parser("mock-server"); m.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    if a.cmd == "demo": cmd_demo(a)
    elif a.cmd == "run": cmd_run(a)
    elif a.cmd == "leaderboard": lb.print_board(lb.build(a.run_dir))
    elif a.cmd == "replay":
        from .replay import replay; replay(a.trace, a.speed)
    elif a.cmd == "cut": cmd_cut(a)
    elif a.cmd == "export-web": print(lb.export_web(a.run_dir, ROOT / "web"))
    elif a.cmd == "tasks":
        for t in TASKS: print(f"{t['id']:<14} {t['title']}：{t['prompt']}")
    elif a.cmd == "mock-server":
        from .mock_server import serve; serve(a.port)
