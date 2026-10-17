"""Smoke-test NVIDIA NIM candidates with one tool-calling request each (through the shared rate limiter)
and write the usable ones to models.nim.json. Never prints the API key.
  python3 scripts/nim_smoke.py runs/nim-candidates.json models.nim.json"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mcbench.nim_agent import NimChat, _api_key  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "get_weather", "description": "Get the weather for a city",
          "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
src, dst = sys.argv[1], sys.argv[2]
try:
    _api_key()
except Exception as e:  # noqa
    sys.exit(f"abort: {e}")
ok, skipped = [], {}
for m in json.loads(Path(src).read_text())["models"]:
    try:
        msg, _ = NimChat(m["model"], max_tokens=2048, retries=4).chat(
            [{"role": "user", "content": "What's the weather in Paris right now? Use the tool."}], TOOLS)
        if msg["tool_calls"]:
            ok.append(m)
            res = "TOOL_OK " + json.dumps([c["function"] for c in msg["tool_calls"]])[:100]
        else:
            skipped[m["model"]] = "no tool call returned: " + repr((msg.get("content") or "")[:100])
            res = "NO_TOOLCALL"
    except Exception as e:  # noqa
        skipped[m["model"]] = f"{type(e).__name__}: {str(e)[:200]}"
        res = skipped[m["model"]]
    print(f"{m['model']:<48} {res}", flush=True)
Path(dst).write_text(json.dumps({"models": ok}, indent=1) + "\n")
Path(dst).with_suffix(".skipped.json").write_text(json.dumps(skipped, indent=1, ensure_ascii=False) + "\n")
print(f"usable {len(ok)} -> {dst}; skipped {len(skipped)}")
