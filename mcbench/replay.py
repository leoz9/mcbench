"""Terminal trace replay."""
import json
import sys
import time


def short(obj, n=160):
    s = json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def replay(path, speed=0.0):
    t = json.load(open(path, encoding="utf-8"))
    print(f"\n▶ 回放  {t['model']}  ×  {t['task_title']}   [MCP: {t['mcp_mode']}]")
    print(f"  任务：{t['prompt']}\n")
    for e in t["events"]:
        if e["type"] == "thought":
            print(f"  💭 {e['text']}")
        elif e["type"] == "tool_call":
            print(f"  🔧 {e['name']}({short(e['args'], 120)})")
        elif e["type"] == "tool_result":
            r = e["result"]
            tag = "⛔" if isinstance(r, dict) and r.get("blocked") else "↩"
            print(f"     {tag} {short(r)}")
        elif e["type"] == "verdict":
            v = e["verdict"]
            if v.get("valid"):
                print(f"\n  🧾 裁判复算：应付 ¥{v['payable']}（Agent 声称 ¥{v['claimed']}，{'✅一致' if v['honest'] else '❌不一致'}）"
                      f" · {v['kcal']} kcal · 蛋白质 {v['protein']}g")
                print("     约束：" + "  ".join(f"{k}{'✅' if ok else '❌'}" for k, ok in v["checks"].items()))
            else:
                print(f"\n  🧾 裁判：无效方案 {v['errors']}")
        sys.stdout.flush()
        if speed:
            time.sleep(speed)
