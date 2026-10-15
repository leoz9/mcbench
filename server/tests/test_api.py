import os
import sys
import time
from pathlib import Path

os.environ.update(DATA_DIR=str(Path(__file__).parent / "_tmp"), ALLOW_SCRIPTED="1", ADMIN_TOKEN="t0k", EVAL_LIMIT="1",
                  RUN_WORKER="0", ALLOW_PRIVATE_URLS="0", SUBMIT_PER_HOUR="100", ALLOWED_ORIGINS="http://ok.test")
sys.path[:0] = [str(Path(__file__).parents[1]), str(Path(__file__).parents[2])]
from fastapi.testclient import TestClient  # noqa: E402

from app import main, worker  # noqa: E402

c = TestClient(main.app)
UA = {"user-agent": "Mozilla/5.0 pytest"}


def test_flow():
    with c:
        assert c.get("/api/health").json()["ok"]
        r = c.post("/api/submissions", json={"name": f"t-{int(time.time())}", "provider": "scripted", "model": "demo-planner"})
        assert r.status_code == 202
        s = worker.claim()
        worker.run_one(s)
        assert c.get(f"/api/submissions/{r.json()['id']}").json()["status"] == "done"
        assert any(x.get("community") for x in c.get("/api/leaderboard").json()["rows"])


def test_validation_and_security():
    with c:
        r = c.post("/api/submissions", json={"name": "x y", "provider": "openai", "model": "m", "api_key": "sk-SECRET1"})
        assert r.status_code == 422 and "sk-SECRET1" not in r.text
        r = c.post("/api/submissions", json={"name": "ok-name", "provider": "openai", "model": "m", "base_url": "https://10.0.0.1/v1", "api_key": "k"})
        assert r.status_code == 400
        assert c.get("/api/admin/submissions").status_code == 401
        assert c.get("/api/admin/submissions", headers={"authorization": "Bearer t0k"}).status_code == 200
        pre = c.options("/api/votes", headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in pre.headers


def test_vote_dedupe():
    with c:
        v = {"task": "core/budget-03", "model_a": "demo-greedy", "model_b": "demo-hasty", "winner": "a"}
        first = c.post("/api/votes", json=v, headers=UA).status_code
        assert first in (200, 409)
        assert c.post("/api/votes", json=v | {"model_a": "demo-hasty", "model_b": "demo-greedy", "winner": "b"}, headers=UA).status_code == 409
        assert c.post("/api/votes", json=v | {"model_a": "nope"}, headers=UA).status_code == 400
        assert c.get("/api/votes/ratings").json()["total_votes"] >= 1
