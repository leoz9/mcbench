"""McCut: render a vertical (9:16) split-screen 'model battle' video from two traces.
Pillow draws frames -> piped to ffmpeg (libx264). Keep it simple."""
import json
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 720, 1280, 15
RED, YEL, BG, PANEL, WHITE, GREY = (219, 0, 7), (255, 199, 44), (24, 24, 24), (38, 38, 38), (245, 245, 245), (160, 160, 160)
FONT_PATHS = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
              "/System/Library/Fonts/PingFang.ttc", "C:/Windows/Fonts/msyh.ttc"]


def font(size, bold=False):
    paths = FONT_PATHS[1:2] + FONT_PATHS if bold else FONT_PATHS
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def lines_for(trace):
    out = []
    for e in trace["events"]:
        if e["type"] == "thought":
            out.append(("💭", e["text"], WHITE))
        elif e["type"] == "tool_call" and e["name"] != "submit_order":
            out.append(("🔧", e["name"], YEL))
        elif e["type"] == "tool_result" and isinstance(e["result"], dict) and e["result"].get("blocked"):
            out.append(("⛔", "create-order 已被 McBench 拦截（dry-run）", RED))
        elif e["type"] == "tool_call":
            out.append(("🧾", "提交方案 · 声称 ¥%s" % e["args"].get("claimedPayable"), YEL))
    return out


def panel(img, d, y0, h, trace, n_show, score, final, f):
    d.rounded_rectangle([20, y0, W - 20, y0 + h], 24, fill=PANEL)
    d.text((44, y0 + 18), trace["model"], font=f["h"], fill=YEL)
    lines, y = lines_for(trace)[:n_show], y0 + 80
    wrapped = []
    for icon, text, col in lines:
        for i, seg in enumerate(textwrap.wrap(text, 24) or [""]):
            wrapped.append(((icon + " " if i == 0 else "   ") + seg, col))
    max_rows = (h - 190) // 34
    for txt, col in wrapped[-max_rows:]:
        d.text((44, y), txt.replace("💭", "·").replace("🔧", "▶").replace("⛔", "×").replace("🧾", "√"), font=f["b"], fill=col)
        y += 34
    if final:
        v = trace["verdict"]
        if v.get("valid"):
            s1 = f"裁判复算 ¥{v['payable']} · {v['kcal']:.0f} kcal · {'价格一致' if v['honest'] else '价格不符'}"
            s2 = "约束 " + ("全部通过" if v["passed"] else "未全部通过")
        else:
            s1, s2 = "无效方案", "; ".join(v["errors"])[:24]
        d.text((44, y0 + h - 100), s1, font=f["b"], fill=WHITE)
        d.text((44, y0 + h - 62), s2, font=f["b"], fill=(120, 220, 120) if v.get("passed") else RED)
        d.text((W - 200, y0 + 14), f"{score:.0f}分", font=f["big"], fill=YEL)


def render(trace_a, trace_b, out, scores=None, mock=True):
    ta, tb = (json.load(open(p, encoding="utf-8")) for p in (trace_a, trace_b))
    scores = scores or {}
    sa, sb = scores.get(ta["model"], 0), scores.get(tb["model"], 0)
    f = {"h": font(34, True), "b": font(24), "big": font(56, True), "t": font(40, True), "s": font(20)}
    la, lb = len(lines_for(ta)), len(lines_for(tb))
    per = int(FPS * 0.8)
    n_steps = max(la, lb)
    total = per * (n_steps + 1) + FPS * 4
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    ph = (H - 340) // 2
    for i in range(total):
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, 150], fill=RED)
        d.text((30, 22), "McBench · AI 点餐对决", font=f["t"], fill=YEL)
        d.text((30, 90), textwrap.shorten(ta["task_title"] + "：" + ta["prompt"], 40, placeholder="…"), font=f["s"], fill=WHITE)
        k = i // per
        final = k > n_steps
        panel(img, d, 170, ph, ta, k, sa, final, f)
        panel(img, d, 190 + ph, ph, tb, k, sb, final, f)
        foot = "MOCK 演示数据 · 脚本示例 Agent，非真实模型成绩" if mock else "数据来自麦当劳官方 MCP · dry-run 不下单"
        d.text((30, H - 45), foot, font=f["s"], fill=GREY)
        if final:
            win = ta["model"] if sa >= sb else tb["model"]
            d.rounded_rectangle([120, 200 + 2 * ph, W - 120, 270 + 2 * ph], 20, fill=YEL)
            d.text((150, 210 + 2 * ph), f"🏆 胜者：{win}".replace("🏆", "★"), font=f["h"], fill=BG)
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out
