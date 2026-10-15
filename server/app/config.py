import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "server" / "var"))
DB_PATH = DATA_DIR / "mcbench.db"
RESULTS_DIR = DATA_DIR / "results"
STATIC_DATA = Path(os.environ.get("STATIC_DATA", ROOT / "web" / "data"))
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "https://cv.leozto.sbs").split(",") if o.strip()]
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")          # Fernet key for transient API-key encryption
ALLOW_SCRIPTED = os.environ.get("ALLOW_SCRIPTED", "0") == "1"   # dev/testing: allow scripted dummy submissions
ALLOW_PRIVATE_URLS = os.environ.get("ALLOW_PRIVATE_URLS", "0") == "1"
TRUST_PROXY = os.environ.get("TRUST_PROXY", "1") == "1"  # behind Cloudflare Tunnel: use CF-Connecting-IP
MAX_QUEUE = int(os.environ.get("MAX_QUEUE", 20))
SUBMIT_PER_HOUR = int(os.environ.get("SUBMIT_PER_HOUR", 3))
VOTE_PER_MIN = int(os.environ.get("VOTE_PER_MIN", 10))
VOTE_PER_DAY = int(os.environ.get("VOTE_PER_DAY", 300))
JOB_TIMEOUT = int(os.environ.get("JOB_TIMEOUT", 7200))
for d in (DATA_DIR, RESULTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
