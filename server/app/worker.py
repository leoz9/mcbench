"""Job queue worker: picks queued submissions, runs the offline evaluation in a subprocess."""
import json
import logging
import os
import subprocess
import sys
import threading
import time

from . import db
from .config import JOB_TIMEOUT, RESULTS_DIR, ROOT
from .security import dec

log = logging.getLogger("mcbench.worker")
SERVER_DIR = ROOT / "server"


def claim():
    with db.conn() as c:
        r = c.execute("SELECT * FROM submissions WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
        if not r:
            return None
        n = c.execute("UPDATE submissions SET status='running', started=? WHERE id=? AND status='queued'", (time.time(), r["id"])).rowcount
        return dict(r) if n else None


def finish(sid, status, error=None, row=None):
    with db.conn() as c:  # key is wiped as soon as the job ends, success or not
        c.execute("UPDATE submissions SET status=?, error=?, row_json=?, finished=?, key_enc=NULL WHERE id=?",
                  (status, error, json.dumps(row, ensure_ascii=False) if row else None, time.time(), sid))


def run_one(s):
    out = RESULTS_DIR / s["id"]
    out.mkdir(parents=True, exist_ok=True)
    spec = {k: s[k] for k in ("name", "provider", "model", "base_url")}
    (out / "spec.json").write_text(json.dumps(spec), "utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("ADMIN_TOKEN", "SECRET_KEY")}
    env["MCBENCH_SUBMIT_KEY"] = dec(s["key_enc"]) if s["key_enc"] else ""
    env["PYTHONPATH"] = f"{ROOT}:{SERVER_DIR}"
    log.info("job %s start (%s)", s["id"], s["name"])
    try:
        p = subprocess.run([sys.executable, "-m", "app.evalrun", str(out / "spec.json"), str(out)], cwd=SERVER_DIR, env=env,
                           capture_output=True, text=True, timeout=JOB_TIMEOUT)
        key = env["MCBENCH_SUBMIT_KEY"]
        logtxt = (p.stdout + p.stderr).replace(key, "***") if key else p.stdout + p.stderr  # never persist the key
        (out / "eval.log").write_text(logtxt[-20000:], "utf-8")
        if p.returncode != 0 or not (out / "row.json").exists():
            return finish(s["id"], "failed", (logtxt.strip().splitlines() or ["error"])[-1][:300])
        finish(s["id"], "done", row=json.loads((out / "row.json").read_text("utf-8")))
        log.info("job %s done", s["id"])
    except subprocess.TimeoutExpired:
        finish(s["id"], "failed", "timeout")


def loop(stop: threading.Event | None = None, poll=2.0):
    db.init()
    with db.conn() as c:  # crash recovery
        c.execute("UPDATE submissions SET status='queued' WHERE status='running'")
    while not (stop and stop.is_set()):
        s = claim()
        if s:
            run_one(s)
        else:
            time.sleep(poll)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loop()
