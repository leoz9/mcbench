"""Run McBench Hard test + Core test for many opencode models, one task per subprocess, keeping at most
MAX_PROCS concurrent opencode workers (box RAM: ~0.55 GB per opencode process). Resume-safe: a task is done
when its trace exists. A model is dropped after FAIL_LIMIT consecutive provider failures (exit code 3).
A task subprocess running longer than TASK_DEADLINE s (monotonic) is killed with its whole process group and
counts as a failure (re-queued). Queue is model-major so models complete (and auto-publish) one after another."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mcbench.tasks import get_tasks  # noqa: E402

MAX_PROCS = int(os.environ.get("MAX_PROCS", "6"))
FAIL_LIMIT = int(os.environ.get("FAIL_LIMIT", "4"))
# adapter: 3 attempts x 1200s + retry sleeps; anything beyond this is a hung run
TASK_DEADLINE = int(os.environ.get("TASK_DEADLINE", "4200"))
models = [json.loads(Path(p).read_text())["models"][0] | {"cfg": p} for p in sys.argv[1:]]
stages = [("hard-v1.1", ROOT / "runs/hard-v1.1", [t["id"] for t in get_tasks("hard-v1.1", "test")]),
          ("v1.0", ROOT / "runs/core-test-v1.1", [t["id"] for t in get_tasks("v1.0", "test")])]
queue = [(m, ts, out, tid) for m in models for ts, out, ids in stages for tid in ids]
running, fails, dropped = {}, {}, set()
logdir = Path("/workspace/oc-run/logs")


def descendants(pid):
    kids = {}
    for st in Path("/proc").glob("[0-9]*/stat"):
        try:
            f = st.read_text().rsplit(")", 1)[1].split()
            kids.setdefault(int(f[1]), []).append(int(st.parent.name))
        except (OSError, IndexError, ValueError):
            pass
    out, stack = [], [pid]
    while stack:
        for c in kids.get(stack.pop(), []):
            out.append(c)
            stack.append(c)
    return out


logdir.mkdir(exist_ok=True)
while True:
    for key, (proc, item, t0) in list(running.items()):
        rc = proc.poll()
        if rc is None and time.monotonic() - t0 > TASK_DEADLINE:
            print(f"[sup] {key[0]} {key[1]} exceeded {TASK_DEADLINE}s - killing process group", flush=True)
            for pid in [proc.pid] + descendants(proc.pid):  # opencode runs in its own session under the task
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            rc = proc.wait()
        if rc is None:
            continue
        del running[key]
        m = item[0]["name"]
        if rc == 0 or (item[2] / "traces" / f"{m}__{item[3]}.json").exists():  # board rebuild race is harmless
            fails[m] = 0
            tp = item[2] / "traces" / f"{m}__{item[3]}.json"
            try:
                tr = json.loads(tp.read_text("utf-8"))
                res = f"{'PASS' if tr['verdict'].get('passed') else 'FAIL'} score={tr.get('score')}"
            except Exception:  # noqa
                res = "rc=0, no trace"
            print(f"[sup] {time.strftime('%H:%M:%S')} done {m} {item[3]} {res}", flush=True)
        else:
            fails[m] = fails.get(m, 0) + 1
            print(f"[sup] {m} {item[3]} rc={rc} (consecutive fails {fails[m]})", flush=True)
            if fails[m] >= FAIL_LIMIT:
                dropped.add(m)
                print(f"[sup] DROP {m}", flush=True)
    pending = [q for q in queue if q[0]["name"] not in dropped
               and not (q[2] / "traces" / f"{q[0]['name']}__{q[3]}.json").exists()]
    if not pending and not running:
        break
    for q in pending:
        if len(running) >= MAX_PROCS:
            break
        key = (q[0]["name"], q[3])
        if key in running:
            continue
        # spread across models: at most 2 concurrent tasks per model (free-tier per-model rate limits)
        if sum(1 for k in running if k[0] == key[0]) >= 2:
            continue
        log = open(logdir / f"{key[0]}__{key[1]}.log", "a")
        p = subprocess.Popen([sys.executable, "-u", "-m", "mcbench", "run", "--config", q[0]["cfg"], "--task-set", q[1],
                              "--split", "test", "--tasks", q[3], "--max-steps", "150", "--jobs", "2", "--resume",
                              "--out", str(q[2])], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True)
        log.close()
        running[key] = (p, q, time.monotonic())
        print(f"[sup] {time.strftime('%H:%M:%S')} start {key[0]} {q[3]} (running {len(running)})", flush=True)
    time.sleep(10)
print("[sup] ALL DONE; dropped:", sorted(dropped), flush=True)
