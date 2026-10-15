import hashlib
import ipaddress
import socket
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from cryptography.fernet import Fernet

from .config import ALLOW_PRIVATE_URLS, SECRET_KEY, TRUST_PROXY

_fernet = Fernet(SECRET_KEY.encode()) if SECRET_KEY else Fernet(Fernet.generate_key())  # ephemeral if unset


def enc(s: str) -> bytes:
    return _fernet.encrypt(s.encode()) if s else b""


def dec(b: bytes) -> str:
    return _fernet.decrypt(b).decode() if b else ""


def client_ip(req) -> str:
    if TRUST_PROXY:
        ip = req.headers.get("cf-connecting-ip") or (req.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if ip:
            return ip
    return req.client.host if req.client else "?"


def h(s: str) -> str:
    return hashlib.sha256(("mcbench:" + s).encode()).hexdigest()[:24]


class RateLimiter:
    def __init__(self):
        self.ev, self.lock = defaultdict(deque), threading.Lock()

    def hit(self, key, limit, window):
        now = time.time()
        with self.lock:
            q = self.ev[key]
            while q and q[0] < now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


limiter = RateLimiter()


def check_url(url: str) -> str | None:
    """Return an error string, or None if the endpoint URL is acceptable (SSRF guard)."""
    u = urlparse(url)
    if u.scheme not in ("https",) and not (ALLOW_PRIVATE_URLS and u.scheme == "http"):
        return "base_url must be https"
    if not u.hostname or u.username or u.password:
        return "invalid host"
    if ALLOW_PRIVATE_URLS:
        return None
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(u.hostname, u.port or 443)}
    except OSError:
        return "host does not resolve"
    for a in addrs:
        ip = ipaddress.ip_address(a)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "private/internal addresses are not allowed"
    return None
