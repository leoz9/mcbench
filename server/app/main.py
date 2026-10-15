"""McBench API: leaderboard, model submissions (queued offline evals), arena-style pairwise voting."""
import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import db, worker
from .config import (ADMIN_TOKEN, ALLOW_SCRIPTED, ALLOWED_ORIGINS, MAX_QUEUE, RESULTS_DIR, STATIC_DATA, SUBMIT_PER_HOUR,
                     VOTE_PER_DAY, VOTE_PER_MIN)
from .security import check_url, client_ip, enc, h, limiter

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="McBench API", version="1.1", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["content-type", "authorization"], max_age=600)
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,47}$")


@app.exception_handler(RequestValidationError)
async def _val(_, exc):  # never echo request bodies (they may contain API keys)
    return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]}, status_code=422)


@app.middleware("http")
async def _sec_headers(req, call_next):
    if int(req.headers.get("content-length") or 0) > 16_000:
        return JSONResponse({"detail": "payload too large"}, status_code=413)
    r = await call_next(req)
    r.headers.update({"x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "cache-control": r.headers.get("cache-control", "no-store")})
    return r


@app.on_event("startup")
def _start():
    db.init()
    if os.environ.get("RUN_WORKER", "1") == "1":
        threading.Thread(target=worker.loop, daemon=True, name="worker").start()


def static_board():
    return json.loads((STATIC_DATA / "leaderboard.json").read_text("utf-8"))


def community_rows():
    with db.conn() as c:
        rs = c.execute("SELECT id,row_json FROM submissions WHERE status='done' AND hidden=0").fetchall()
    out = []
    for r in rs:
        row = json.loads(r["row_json"])
        row.update(community=True, verified=False, submission_id=r["id"])
        out.append(row)
    return out


def all_models():
    return {r["model"] for r in static_board()["rows"]} | {r["model"] for r in community_rows()}


@app.get("/api/health")
def health():
    with db.conn() as c:
        q = c.execute("SELECT COUNT(*) FROM submissions WHERE status IN ('queued','running')").fetchone()[0]
    return {"ok": True, "queue": q, "submissions": True, "voting": True}


@app.get("/api/leaderboard")
def leaderboard():
    b = static_board()
    names = {r["model"] for r in b["rows"]}
    b["rows"] += [r for r in community_rows() if r["model"] not in names]
    b["rows"].sort(key=lambda r: (r.get("overall") is None, -(r.get("overall") or 0)))
    b["source"] = "api"
    return b


@app.get("/api/traces/{which}/{model}/{task}")
def trace(which: Literal["hard", "core"], model: str, task: str):
    if not NAME_RE.match(model) or not re.match(r"^[a-z0-9-]{3,64}$", task):
        raise HTTPException(400, "bad id")
    with db.conn() as c:
        r = c.execute("SELECT id FROM submissions WHERE name=? AND status='done' AND hidden=0", (model,)).fetchone()
    if not r:
        raise HTTPException(404)
    p = RESULTS_DIR / r["id"] / which / "traces" / f"{model}__{task}.json"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/json")


class Submission(BaseModel):
    name: str = Field(min_length=2, max_length=48)
    provider: Literal["openai", "anthropic", "scripted"]
    model: str = Field(min_length=1, max_length=128)
    base_url: str = Field(default="", max_length=300)
    api_key: str = Field(default="", max_length=400, repr=False)
    contact: str = Field(default="", max_length=120)
    website: str = Field(default="", max_length=0)  # honeypot: must stay empty

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        if not NAME_RE.match(v):
            raise ValueError("name: letters, digits, . _ - only")
        return v

    @field_validator("model")
    @classmethod
    def _m(cls, v):
        if not re.match(r"^[\w./:@-]+$", v):
            raise ValueError("invalid model id")
        return v


@app.post("/api/submissions", status_code=202)
def submit(s: Submission, request: Request):
    ip = h(client_ip(request))
    if not limiter.hit("sub:" + ip, SUBMIT_PER_HOUR, 3600):
        raise HTTPException(429, "rate limited")
    if s.provider == "scripted":
        from mcbench.demo_agents import DEMO_AGENTS
        if not ALLOW_SCRIPTED or s.model not in DEMO_AGENTS:
            raise HTTPException(400, "scripted submissions disabled")
    else:
        err = check_url(s.base_url)
        if err:
            raise HTTPException(400, err)
        if not s.api_key:
            raise HTTPException(400, "api_key required")
    if s.name in {r["model"] for r in static_board()["rows"]}:
        raise HTTPException(409, "name taken")
    with db.conn() as c:
        if c.execute("SELECT COUNT(*) FROM submissions WHERE status IN ('queued','running')").fetchone()[0] >= MAX_QUEUE:
            raise HTTPException(503, "queue full")
        if c.execute("SELECT 1 FROM submissions WHERE name=?", (s.name,)).fetchone():
            raise HTTPException(409, "name taken")
        sid = uuid.uuid4().hex[:12]
        c.execute("INSERT INTO submissions(id,name,provider,model,base_url,contact,key_enc,status,ip_hash,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (sid, s.name, s.provider, s.model, s.base_url, s.contact, enc(s.api_key), "queued", ip, time.time()))
    return {"id": sid, "status": "queued"}


@app.get("/api/submissions/{sid}")
def submission(sid: str):
    with db.conn() as c:
        r = c.execute("SELECT id,name,provider,model,status,error,created,started,finished FROM submissions WHERE id=?", (sid,)).fetchone()
        if not r:
            raise HTTPException(404)
        pos = c.execute("SELECT COUNT(*) FROM submissions WHERE status='queued' AND created<?", (r["created"],)).fetchone()[0]
    return dict(r) | {"queue_position": pos if r["status"] == "queued" else None}


class Vote(BaseModel):
    task: str = Field(pattern=r"^(core/)?[a-z0-9-]{3,64}$")
    model_a: str = Field(max_length=48)
    model_b: str = Field(max_length=48)
    winner: Literal["a", "b", "tie", "both_bad"]


@app.post("/api/votes")
def vote(v: Vote, request: Request, user_agent: str = Header(default="")):
    ip = h(client_ip(request))
    if not (limiter.hit("vm:" + ip, VOTE_PER_MIN, 60) and limiter.hit("vd:" + ip, VOTE_PER_DAY, 86400)):
        raise HTTPException(429, "rate limited")
    if v.model_a == v.model_b or not {v.model_a, v.model_b} <= all_models():
        raise HTTPException(400, "unknown models")
    if not user_agent or len(user_agent) < 8:
        raise HTTPException(400, "bad client")
    a, b, w = v.model_a, v.model_b, v.winner
    if a > b:  # canonical order so A/B swap can't double-vote
        a, b, w = b, a, {"a": "b", "b": "a"}.get(w, w)
    with db.conn() as c:
        if c.execute("SELECT 1 FROM votes WHERE ip_hash=? AND task=? AND model_a=? AND model_b=? AND created>?",
                     (ip, v.task, a, b, time.time() - 86400)).fetchone():
            raise HTTPException(409, "already voted on this pair today")
        c.execute("INSERT INTO votes(task,model_a,model_b,winner,ip_hash,ua_hash,created) VALUES(?,?,?,?,?,?,?)",
                  (v.task, a, b, w, ip, h(user_agent), time.time()))
    return {"ok": True}


@app.get("/api/votes/ratings")
def ratings():
    with db.conn() as c:
        vs = c.execute("SELECT model_a,model_b,winner FROM votes ORDER BY created").fetchall()
    elo, n = {}, {}
    for r in vs:
        a, b = r["model_a"], r["model_b"]
        ra, rb = elo.get(a, 1000.0), elo.get(b, 1000.0)
        ea = 1 / (1 + 10 ** ((rb - ra) / 400))
        sa = {"a": 1, "b": 0, "tie": .5, "both_bad": .5}[r["winner"]]
        elo[a], elo[b] = ra + 16 * (sa - ea), rb - 16 * (sa - ea)
        n[a], n[b] = n.get(a, 0) + 1, n.get(b, 0) + 1
    return {"total_votes": len(vs), "ratings": sorted([{"model": m, "elo": round(e), "votes": n[m]} for m, e in elo.items()], key=lambda x: -x["elo"])}


def _admin(auth: str):
    if not ADMIN_TOKEN or not secrets.compare_digest(auth, f"Bearer {ADMIN_TOKEN}"):
        raise HTTPException(401)


@app.get("/api/admin/submissions")
def admin_list(authorization: str = Header(default="")):
    _admin(authorization)
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT id,name,provider,model,base_url,contact,status,error,created,finished,hidden FROM submissions ORDER BY created DESC")]


@app.post("/api/admin/submissions/{sid}/{action}")
def admin_act(sid: str, action: Literal["hide", "show", "requeue"], authorization: str = Header(default="")):
    _admin(authorization)
    sql = {"hide": "UPDATE submissions SET hidden=1 WHERE id=?", "show": "UPDATE submissions SET hidden=0 WHERE id=?",
           "requeue": "UPDATE submissions SET status='queued' WHERE id=? AND (key_enc IS NOT NULL OR provider='scripted')"}[action]
    with db.conn() as c:
        c.execute(sql, (sid,))
    return {"ok": True}
