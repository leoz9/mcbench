"""Run McBench Hard test (22) + Core test (18) for NVIDIA NIM free models in ONE process so a single
global adaptive rate limiter (mcbench.nim_agent.LIMITER, NIM_RPM req/min total, default 30) covers
every worker. WORKERS threads total (default 10), at most PER_MODEL (default 2) concurrent episodes
per model; models are queued in order so they finish one after another (incremental publishing).
Resume-safe: a task is done when its trace exists. Infra failures (NimInfraError) are re-queued up to
MAX_TRIES times and never scored; NimModelUnavailable drops the model. On each model completing both
splits, ON_COMPLETE (default scripts/nim_publish.sh) is run with the model name.

  python3 -u scripts/nim_supervisor.py models.nim.json
"""
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mcbench.cli import save_trace  # noqa: E402
from mcbench.env import McBenchEnv, make_mcp  # noqa: E402
from mcbench.nim_agent import LIMITER, NimModelUnavailable, _api_key, run_nim_episode  # noqa: E402

_api_key()  # abort early (no model dropped) if NVIDIA_API_KEY is not a usable key
from mcbench.tasks import get_tasks  # noqa: E402

WORKERS = int(os.environ.get("WORKERS", "10"))
PER_MODEL = int(os.environ.get("PER_MODEL", "2"))
MAX_TRIES = int(os.environ.get("MAX_TRIES", "3"))
ON_COMPLETE = os.environ.get("ON_COMPLETE", str(ROOT / "scripts/nim_publish.sh"))
models = json.loads(Path(sys.argv[1]).read_text())["models"]
only = set(sys.argv[2:])
if only:
    models = [m for m in models if m["name"] in only]
stages = [("hard-v1.1", ROOT / "runs/hard-v1.1", get_tasks("hard-v1.1", "test")),
          ("v1.0", ROOT / "runs/core-test-v1.1", get_tasks("v1.0", "test"))]


def done(m, out, t):
    return (out / "traces" / f"{m['name']}__{t['id']}.json").exists()


def one(m, ts, out, t):
    env = McBenchEnv(mode="offline", task_set=ts, mcp=make_mcp("offline"), max_steps=150)
    tr = run_nim_episode(m["model"], m["name"], t, env, extra=m.get("extra"))
    save_trace(out, tr)
    v = tr["verdict"]
    print(f"  {m['name']:<28} {t['id']:<22} {'PASS' if v.get('passed') else 'FAIL'} score={tr['score']} "
          f"calls={tr['tool_calls']} sv={tr['safety_violations']} [{LIMITER.status()}]", flush=True)


def complete(m):
    return all(done(m, out, t) for _, out, ts in stages for t in ts)


queue = [(m, ts, out, t) for m in models for ts, out, tasks in stages for t in tasks if not done(m, out, t)]
tries, dropped, published, lock = {}, {}, {m["name"] for m in models if complete(m)}, threading.Lock()
print(f"[nim] {len(models)} models, {len(queue)} episodes pending, workers={WORKERS} per_model={PER_MODEL} "
      f"[{LIMITER.status()}]", flush=True)
running = {}
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    while True:
        for f in [f for f in running if f.done()]:
            item = running.pop(f)
            m, key = item[0], (item[0]["name"], item[3]["id"])
            e = f.exception()
            if e is None:
                if complete(m) and m["name"] not in published:
                    published.add(m["name"])
                    print(f"[nim] COMPLETE {m['name']} -> {ON_COMPLETE}", flush=True)
                    subprocess.run(["bash", ON_COMPLETE, m["name"]], cwd=ROOT)
                continue
            if isinstance(e, NimModelUnavailable):
                dropped[m["name"]] = str(e)[:300]
                print(f"[nim] DROP {m['name']}: {str(e)[:300]}", flush=True)
                continue
            tries[key] = tries.get(key, 0) + 1
            print(f"[nim] infra fail {key} try {tries[key]}/{MAX_TRIES}: {type(e).__name__}: {str(e)[:250]}", flush=True)
            if not getattr(e, "infra", False):
                traceback.print_exception(e)
            if tries[key] < MAX_TRIES:
                queue.append(item)
        queue = [q for q in queue if q[0]["name"] not in dropped]
        if not queue and not running:
            break
        busy = {}
        for it in running.values():
            busy[it[0]["name"]] = busy.get(it[0]["name"], 0) + 1
        for q in list(queue):
            if len(running) >= WORKERS:
                break
            if busy.get(q[0]["name"], 0) >= PER_MODEL:
                continue
            queue.remove(q)
            busy[q[0]["name"]] = busy.get(q[0]["name"], 0) + 1
            running[ex.submit(one, *q)] = q
        if running:
            wait(list(running), timeout=15, return_when=FIRST_COMPLETED)
        else:
            time.sleep(5)
left = [m["name"] for m in models if m["name"] not in dropped and not complete(m)]
print(f"[nim] ALL DONE [{LIMITER.status()}] complete={sorted(published)} dropped={dropped} incomplete={left}", flush=True)
