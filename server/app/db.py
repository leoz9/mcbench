import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions(
 id TEXT PRIMARY KEY, name TEXT UNIQUE, provider TEXT, model TEXT, base_url TEXT, contact TEXT,
 key_enc BLOB, status TEXT, error TEXT, ip_hash TEXT, created REAL, started REAL, finished REAL,
 row_json TEXT, hidden INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS votes(
 id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, model_a TEXT, model_b TEXT, winner TEXT,
 ip_hash TEXT, ua_hash TEXT, created REAL);
CREATE INDEX IF NOT EXISTS votes_dedupe ON votes(ip_hash, task, model_a, model_b);
"""


def init():
    with conn() as c:
        c.executescript(SCHEMA)


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()
