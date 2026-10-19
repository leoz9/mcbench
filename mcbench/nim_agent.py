"""NVIDIA NIM (build.nvidia.com, OpenAI-compatible) function-calling adapter for McBench.

Uses the standard chat-loop harness (mcbench/harness.py) against McBenchEnv: the same offline frozen
snapshot + SafeMCP allowlist as every other adapter (write tools blocked and counted as safety
violations, submit_order is dry-run only, unsafe distractor tools are blocked) — the model only ever
sees McBench's tool schemas, never a shell or filesystem.

Free-tier etiquette: ONE process-wide adaptive rate limiter shared by every worker thread/model
(default 30 req/min total for the key). On 429 the limiter lowers its rate (x0.7, floor 6/min) and
imposes a global pause with exponential backoff + jitter; after a long run of successes it slowly
creeps back up (never above the configured ceiling). Provider/transport failures that survive the
retries raise NimInfraError: the episode is discarded (no trace written) and re-queued, never scored.
"""
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request

from .env import McBenchEnv
from .harness import run_episode

NIM_BASE = os.environ.get("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")


class NimInfraError(RuntimeError):
    """Transient provider/transport error after retries (429 storm, 5xx, timeout) — not a model result."""
    infra = True


class NimModelUnavailable(RuntimeError):
    """404 / deprecated / model does not accept tools — drop the model (not scored)."""
    infra = True


class RateLimiter:
    def __init__(self, rpm=30.0, min_rpm=6.0, max_rpm=None):
        self.rpm, self.min_rpm, self.max_rpm = float(rpm), float(min_rpm), float(max_rpm or rpm)
        self.lock = threading.Lock()
        self.next_slot = 0.0      # earliest time the next request may start
        self.pause_until = 0.0    # global pause after a 429
        self.strikes, self.ok_streak = 0, 0
        self.n_req = self.n_429 = 0

    def acquire(self):
        with self.lock:
            now = time.time()
            start = max(now, self.next_slot, self.pause_until)
            self.next_slot = start + 60.0 / self.rpm
            self.n_req += 1
        if start > now:
            time.sleep(start - now)

    def on_success(self):
        with self.lock:
            self.strikes = 0
            self.ok_streak += 1
            if self.ok_streak >= 40 and self.rpm < self.max_rpm:
                self.rpm, self.ok_streak = min(self.max_rpm, self.rpm + 1), 0

    def on_429(self, retry_after=None):
        with self.lock:
            self.n_429 += 1
            self.strikes += 1
            self.ok_streak = 0
            self.rpm = max(self.min_rpm, self.rpm * 0.7)
            back = min(300.0, 10.0 * 2 ** (self.strikes - 1)) * random.uniform(0.8, 1.3)
            if retry_after:
                back = max(back, float(retry_after))
            self.pause_until = max(self.pause_until, time.time() + back)
            return back

    def status(self):
        return f"rpm={self.rpm:.1f} req={self.n_req} 429s={self.n_429}"


LIMITER = RateLimiter(float(os.environ.get("NIM_RPM", "30")), max_rpm=float(os.environ.get("NIM_RPM_MAX", os.environ.get("NIM_RPM", "30"))))
_DEAD = re.compile(r"deprecat|end.of.life|no longer (available|supported)|not found|does not exist|unknown model", re.I)
_NOTOOLS = re.compile(r"tool[_ ]?(choice|call|s)?[^.]{0,60}(not supported|unsupported|not enabled)|does not support tool", re.I)


def _api_key():
    k = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not re.fullmatch(r"[\x21-\x7e]{20,300}", k):
        raise NimModelUnavailable("NVIDIA_API_KEY is missing or not a valid API key string (expected nvapi-…)")
    return k


class NimChat:
    def __init__(self, model, base_url=NIM_BASE, temperature=0.0, timeout=None, max_tokens=8192, extra=None,
                 limiter=None, retries=8, max_hangs=None):
        self.model, self.base_url = model, base_url.rstrip("/")
        # timeout = per-socket-op read timeout; max_hangs = consecutive read timeouts on one call before giving up
        # (a model whose queue hangs every request otherwise pins a worker for ~30 min per call: 8 x 180 s + backoff)
        self.timeout = timeout or float(os.environ.get("NIM_TIMEOUT", "150"))
        self.max_hangs = max_hangs or int(os.environ.get("NIM_MAX_HANGS", "3"))
        self.temperature, self.max_tokens = temperature, max_tokens
        self.extra, self.limiter, self.retries = extra or {}, limiter or LIMITER, retries
        self.runtime = f"NVIDIA NIM free ({model})"
        self.key = _api_key()

    def chat(self, messages, tools):
        body = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto",
                "temperature": self.temperature, "max_tokens": self.max_tokens, **self.extra}
        data, last, n400, hangs, n5xx = json.dumps(body).encode(), "", 0, 0, 0
        for attempt in range(self.retries):
            self.limiter.acquire()
            req = urllib.request.Request(self.base_url + "/chat/completions", data=data, method="POST",
                                         headers={"Content-Type": "application/json", "Accept": "application/json",
                                                  "Authorization": f"Bearer {self.key}"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    out = json.loads(r.read())
                self.limiter.on_success()
                ch = (out.get("choices") or [{}])[0]
                msg = ch.get("message") or {}
                calls = [c for c in (msg.get("tool_calls") or []) if (c.get("function") or {}).get("name")]
                for i, c in enumerate(calls):
                    c.setdefault("id", f"call_{attempt}_{i}")
                    c.setdefault("type", "function")
                    if not isinstance(c["function"].get("arguments"), str):
                        c["function"]["arguments"] = json.dumps(c["function"].get("arguments") or {}, ensure_ascii=False)
                return {"role": "assistant", "content": msg.get("content"), "tool_calls": calls}, out.get("usage")
            except urllib.error.HTTPError as e:
                txt = e.read().decode("utf-8", "replace")[:400]
                last = f"HTTP {e.code}: {txt}"
                if e.code == 429:
                    back = self.limiter.on_429(e.headers.get("Retry-After"))
                    print(f"  .. NIM 429 on {self.model}; backing off {back:.0f}s ({self.limiter.status()})", flush=True)
                    continue
                if e.code in (404, 410) or (e.code in (400, 422) and _DEAD.search(txt)):
                    raise NimModelUnavailable(f"{self.model}: {last}") from None
                if e.code in (400, 422) and _NOTOOLS.search(txt):
                    raise NimModelUnavailable(f"{self.model}: no tool support: {last}") from None
                if e.code in (401, 403):
                    raise NimModelUnavailable(f"{self.model}: auth/permission: HTTP {e.code}") from None
                if e.code == 400 and "context" in txt.lower() and "length" in txt.lower():
                    raise RuntimeError(last)  # genuine model-side failure (context overflow): episode ends, scored
                if e.code == 400:
                    n400 += 1
                    if n400 > 2:
                        raise NimInfraError(last) from None
                elif e.code not in (500, 502, 503, 504):
                    raise NimInfraError(last) from None
                else:
                    n5xx += 1
                    if n5xx >= 5:
                        raise NimInfraError(f"{self.model}: persistent {last}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, OSError) as e:
                last = f"{type(e).__name__}: {e}"
                if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
                    hangs += 1
                    if hangs >= self.max_hangs:
                        raise NimInfraError(f"{self.model}: {hangs} consecutive read timeouts ({self.timeout:.0f}s): {last}") from None
            time.sleep(min(120, 5 * 2 ** attempt) * random.uniform(0.7, 1.3))
        raise NimInfraError(f"{self.model}: retries exhausted: {last}")


def run_nim_episode(model, label, task, env: McBenchEnv, max_turns=60, extra=None):
    """One McBench episode; raises NimInfraError/NimModelUnavailable (no trace) on provider problems."""
    tr = run_episode(NimChat(model, extra=extra), label, task, env, max_turns=max_turns)
    return tr
