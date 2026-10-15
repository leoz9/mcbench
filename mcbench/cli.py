"""McBench CLI."""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import leaderboard as lb
from .demo_agents import DEMO_AGENTS, ScriptedAgent
from .env import McBenchEnv, make_mcp
from .harness import run_episode
from .tasks import get_tasks

ROOT = Path(__file__).resolve().parent.parent


def save_trace(out_dir, tr):
    Path(out_dir, "traces").mkdir(parents=True, exist_ok=True)
    safe = tr["model"].replace("/", "_").replace(" ", "_")
    seed = tr.get("seed")
    name = f"{safe}__{tr['task']}" + (f"__r{seed}" if seed is not None else "") + ".json"
    Path(out_dir, "traces", name).write_text(json.dumps(tr, ensure_ascii=False, indent=1), "utf-8")
    return name


def cmd_demo(a):
    print("🍔 McBench DEMO —— 冻结快照（OFFLINE）+ 脚本基线，无需 Token / API Key，绝不下单\n")
    env = McBenchEnv(mode="offline", max_steps=150)
    out = Path(a.out)
    for name, pol in DEMO_AGENTS.items():
        for t in get_tasks(split="dev" if a.dev else "all", ids=a.tasks):
            dst = out / "traces" / f"{name}__{t['id']}.json"
            if a.resume and dst.exists():
                print(f"  {name:<16} {t['id']:<18} (skip)")
                continue
            tr = run_episode(ScriptedAgent(pol), name, t, env)
            save_trace(out, tr)
            v = tr["verdict"]
            print(f"  {name:<16} {t['id']:<18} {'PASS' if v.get('passed') else 'FAIL'}  ¥{v.get('payable', '-')}  score={tr['score']}")
    board = lb.build(out, note="OFFLINE demo · 脚本基线（非大模型）")
    lb.print_board(board)
    lb.export_web(out, ROOT / "web", "data-demo")
    if not a.no_video:
        try:
            from .video import render_battle
            rows = board["rows"]
            a_m, b_m = rows[0]["model"], rows[-1]["model"]
            task = next(iter(rows[0]["by_task"]))
            v = render_battle(out / f"traces/{a_m}__{task}.json", out / f"traces/{b_m}__{task}.json",
                              out / f"battle_{task}.mp4", mock=True)
            print(f"🎬 {v}")
        except Exception as e:  # noqa
            print(f"(跳过视频：{e})")
    print(f"📊 python -m http.server -d {ROOT / 'web'} 8000 → http://localhost:8000/?demo")


def _agent_jobs(a):
    jobs = []
    if a.demo_agents:
        for n, p in DEMO_AGENTS.items():
            jobs.append({"kind": "scripted", "name": n, "policy": p})
    if a.config:
        cfg = json.load(open(a.config, encoding="utf-8"))
        for m in cfg["models"]:
            if m.get("provider") == "codex":
                jobs.append({"kind": "codex", "name": m["name"], "model": m["model"]})
            elif m.get("provider") == "anthropic":
                from .llm import AnthropicCompatChat
                jobs.append({"kind": "openai", "name": m["name"],
                             "factory": (lambda m=m: AnthropicCompatChat(m["model"], m["base_url"],
                                                                         m.get("api_key_env", "ANTHROPIC_API_KEY"),
                                                                         m.get("temperature", 0.0), extra=m.get("extra")))})
            else:
                from .llm import OpenAICompatChat
                jobs.append({"kind": "openai", "name": m["name"],
                             "factory": (lambda m=m: OpenAICompatChat(m["model"], m["base_url"],
                                                                      m.get("api_key_env", "OPENAI_API_KEY"),
                                                                      m.get("temperature", 0.0), extra=m.get("extra")))})
    return jobs


def cmd_run(a):
    mode = "live" if a.live else "offline"
    tasks = get_tasks(a.task_set, a.split, a.categories, a.difficulty, a.tasks)
    jobs = _agent_jobs(a)
    if not jobs:
        sys.exit("指定 --demo-agents 和/或 --config")
    out = Path(a.out)
    seeds = [int(x) for x in a.seeds.split(",")] if a.seeds else (list(range(a.k)) if a.k > 1 else [None])
    work = []
    for j in jobs:
        for t in tasks:
            for seed in seeds:
                safe = j["name"].replace("/", "_").replace(" ", "_")
                stamp = f"{safe}__{t['id']}" + (f"__r{seed}" if seed is not None else "")
                if a.resume and (out / "traces" / f"{stamp}.json").exists():
                    print(f"  {j['name']:<20} {t['id']:<18} (skip)")
                    continue
                work.append((j, t, seed))

    def one(item):
        j, t, seed = item
        env = McBenchEnv(mode=mode, task_set=a.task_set, mcp=make_mcp(mode), max_steps=a.max_steps)
        if j["kind"] == "scripted":
            tr = run_episode(ScriptedAgent(j["policy"]), j["name"], t, env)
        elif j["kind"] == "codex":
            from .codex_agent import run_codex_episode
            tr = run_codex_episode(j["model"], j["name"], t, env, task_set=a.task_set)
        else:
            tr = run_episode(j["factory"](), j["name"], t, env)
        if seed is not None:
            tr["seed"] = seed
        return tr

    if a.jobs > 1:
        with ThreadPoolExecutor(max_workers=a.jobs) as ex:
            futs = [ex.submit(one, w) for w in work]
            for f in as_completed(futs):
                tr = f.result()
                save_trace(out, tr)
                v = tr["verdict"]
                print(f"  {tr['model']:<20} {tr['task']:<18} {'PASS' if v.get('passed') else 'FAIL'}  ¥{v.get('payable', '-')}  score={tr['score']}")
    else:
        for w in work:
            tr = one(w)
            save_trace(out, tr)
            v = tr["verdict"]
            print(f"  {tr['model']:<20} {tr['task']:<18} {'PASS' if v.get('passed') else 'FAIL'}  ¥{v.get('payable', '-')}  score={tr['score']}")
    board = lb.build(out)
    lb.print_board(board)
    if a.export:
        lb.export_web(out, ROOT / "web", "data")


def cmd_tasks(a):
    if a.sub == "list":
        for t in get_tasks(a.task_set, a.split or "all", a.categories, a.difficulty):
            print(f"{t['id']:<22} {t['difficulty']:<7} {t['category']:<18} {t['split']:<5} {t['title']}")
    elif a.sub == "new":
        from .community import new_task
        print(new_task(a.id, a.category, a.difficulty))
    elif a.sub == "validate":
        from .community import validate_path
        ok, msgs = validate_path(a.path or "tasks/community")
        print("\n".join(msgs))
        sys.exit(0 if ok else 1)


def cmd_leaderboard(a):
    lb.print_board(lb.build(a.run_dir, a.note))


def cmd_export(a):
    print(lb.export_web(a.run_dir, ROOT / "web", a.sub))


def cmd_cut(a):
    from .video import render_battle
    board = json.load(open(Path(a.trace_a).parent.parent / "leaderboard.json", encoding="utf-8"))
    ta = json.load(open(a.trace_a, encoding="utf-8"))
    scores = {r["model"]: r["by_task"].get(ta["task"], {}).get("score", 0) for r in board["rows"]}
    print(render_battle(a.trace_a, a.trace_b, a.out, scores, mock=board.get("is_mock", False)))


def cmd_video(a):
    from .video import render_explainer
    print(render_explainer(a.run_dir, a.out, tts=a.tts))


def cmd_vision(a):
    from .vision import run_models, run_vision_track
    if a.codex_models:
        for r in run_models(a.codex_models.split(","), out=a.out):
            print(f"{r['model']:<16} F1={r['f1']}  exact={r['exact']}  price MAE=¥{r['price_mae']}")
    else:
        run_vision_track(a)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "task":  # alias: mcbench task new/validate
        sys.argv[1] = "tasks"
    p = argparse.ArgumentParser(prog="mcbench", description="McBench：多维度大模型点麦当劳基准（社区共建）")
    s = p.add_subparsers(dest="cmd", required=True)
    d = s.add_parser("demo"); d.add_argument("--out", default="runs/demo"); d.add_argument("--no-video", action="store_true")
    d.add_argument("--dev", action="store_true"); d.add_argument("--tasks"); d.add_argument("--resume", action="store_true")
    r = s.add_parser("run"); r.add_argument("--config"); r.add_argument("--live", action="store_true")
    r.add_argument("--demo-agents", action="store_true"); r.add_argument("--task-set", default="v1.0")
    r.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    r.add_argument("--categories"); r.add_argument("--difficulty"); r.add_argument("--tasks")
    r.add_argument("--k", type=int, default=1, help="pass^k 重复次数")
    r.add_argument("--seeds", help="显式 run 编号，如 1,2（与已有 k=1 结果合并计算 pass^k）"); r.add_argument("--jobs", type=int, default=1)
    r.add_argument("--max-steps", type=int, default=30); r.add_argument("--out", default="runs/latest")
    r.add_argument("--export", action="store_true"); r.add_argument("--resume", action="store_true")
    t = s.add_parser("tasks"); ts = t.add_subparsers(dest="sub", required=True)
    tl = ts.add_parser("list"); tl.add_argument("--task-set", default="v1.0"); tl.add_argument("--split")
    tl.add_argument("--categories"); tl.add_argument("--difficulty")
    tn = ts.add_parser("new"); tn.add_argument("--id", required=True); tn.add_argument("--category", default="budget")
    tn.add_argument("--difficulty", default="medium")
    tv = ts.add_parser("validate"); tv.add_argument("path", nargs="?")
    b = s.add_parser("leaderboard"); b.add_argument("run_dir"); b.add_argument("--note", default="")
    cb = s.add_parser("combine", help="headline board: Hard + Core → web/data")
    cb.add_argument("hard_dir"); cb.add_argument("core_dir"); cb.add_argument("--note", default="")
    e = s.add_parser("export-web"); e.add_argument("run_dir"); e.add_argument("--sub", default="data")
    rp = s.add_parser("replay"); rp.add_argument("trace"); rp.add_argument("--speed", type=float, default=0.0)
    c = s.add_parser("cut"); c.add_argument("trace_a"); c.add_argument("trace_b"); c.add_argument("-o", "--out", default="battle.mp4")
    v = s.add_parser("video"); v.add_argument("run_dir"); v.add_argument("-o", "--out", default="docs/media/explainer.mp4")
    v.add_argument("--tts", action="store_true")
    vi = s.add_parser("vision"); vi.add_argument("--out", default="runs/vision"); vi.add_argument("--demo", action="store_true")
    vi.add_argument("--codex-models", help="逗号分隔，如 gpt-6-luna,gpt-5.6-luna（经 codex exec -i 传图）")
    s.add_parser("mock-server").add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    if a.cmd == "demo":
        cmd_demo(a)
    elif a.cmd == "run":
        cmd_run(a)
    elif a.cmd == "tasks":
        cmd_tasks(a)
    elif a.cmd == "leaderboard":
        cmd_leaderboard(a)
    elif a.cmd == "combine":
        b = lb.combine(a.hard_dir, a.core_dir, ROOT / "web", note=a.note)
        print(f"{'#':<3}{'Agent':<20}{'Overall':>8}{'Hard':>7}{'H-pass':>8}{'Core':>7}{'C-pass':>8}")
        for i, r in enumerate(b["rows"], 1):
            c = r["core"] or {}
            print(f"{i:<3}{r['model']:<20}{str(r['overall']):>8}{str(r['avg_score']):>7}{(r['pass_at_1'] or 0):>8.3f}"
                  f"{str(c.get('avg_score', '-')):>7}{(c.get('pass_at_1') if c else 0):>8.3f}")
    elif a.cmd == "export-web":
        cmd_export(a)
    elif a.cmd == "replay":
        from .replay import replay; replay(a.trace, a.speed)
    elif a.cmd == "cut":
        cmd_cut(a)
    elif a.cmd == "video":
        cmd_video(a)
    elif a.cmd == "vision":
        cmd_vision(a)
    elif a.cmd == "mock-server":
        from .mock_server import serve; serve(a.port)


if __name__ == "__main__":
    main()
