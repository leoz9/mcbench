"""McCut + explainer video generation (vertical 9:16)."""
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from .mccut import FPS, H, W, font  # reuse palette helpers via re-export

# re-export render_battle named for CLI
from .mccut import render as render_battle  # noqa: F401

RED, YEL, BG, PANEL, WHITE, GREY = (219, 0, 7), (255, 199, 44), (24, 24, 24), (38, 38, 38), (245, 245, 245), (160, 160, 160)


def render_explainer(run_dir, out, tts=False):
    """Auto shareable vertical explainer: intro → top-2 battle → rank reveal → outro."""
    board = json.loads(Path(run_dir, "leaderboard.json").read_text("utf-8"))
    rows = board["rows"]
    if len(rows) < 2:
        raise RuntimeError("need ≥2 agents")
    # pick a task both have
    llm = [r for r in rows if not r["model"].startswith("demo-")]
    ra, rb = (llm[:2] if len(llm) >= 2 else rows[:2])
    # most telling task: both ran it, scores differ the most
    common = set(ra["by_task"]) & set(rb["by_task"])
    task = max(sorted(common), key=lambda t: abs(ra["by_task"][t]["score"] - rb["by_task"][t]["score"]))
    a = Path(run_dir, "traces", f"{ra['model']}__{task}.json")
    b = Path(run_dir, "traces", f"{rb['model']}__{task}.json")
    battle = Path(out).with_suffix(".battle.mp4")
    scores = {r["model"]: r["by_task"].get(task, {}).get("score", 0) for r in rows}
    foot = None if board.get("is_mock") else ("真实模型 · 离线冻结快照（录制自麦当劳官方 MCP）· dry-run"
                                              if board.get("mcp_mode") in ("mock", "offline") else None)
    render_battle(a, b, battle, scores, mock=board.get("is_mock", False), foot=foot)
    # stitch intro + battle + outro
    frames_dir = Path(out).with_suffix(".frames")
    frames_dir.mkdir(exist_ok=True)
    f = {"t": font(40, True), "h": font(34, True), "b": font(24), "s": font(20), "big": font(56, True)}
    def frame(name, draw_fn, n=FPS * 3):
        for i in range(n):
            img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img); draw_fn(d, i / max(1, n - 1))
            img.save(frames_dir / f"{name}_{i:04d}.png")
    def intro(d, p):
        d.rectangle([0, 0, W, 220], fill=RED)
        d.text((40, 40), "McBench", font=f["big"], fill=YEL)
        d.text((40, 120), "鹈鹕骑车 is out，麦当劳点餐 is in", font=f["h"], fill=WHITE)
        d.text((40, 300), "多维度 · 社区共建 · dry-run", font=f["b"], fill=GREY)
        d.text((40, 360), f"任务集 {board.get('task_set') or 'v1.0'} · {len(rows)} agents", font=f["b"], fill=WHITE)
    def outro(d, p):
        d.rectangle([0, 0, W, 180], fill=RED)
        d.text((40, 40), "Star · 共建 Join us", font=f["t"], fill=YEL)
        d.text((40, 250), "https://github.com/leoz9/mcbench", font=f["h"], fill=WHITE)
        d.text((40, 320), "cv.leozto.sbs/mcbench", font=f["b"], fill=GREY)
        y = 420
        for i, r in enumerate(rows[:5], 1):
            d.text((40, y), f"#{i}  {r['model']}  {r['avg_score']}", font=f["b"], fill=YEL if i == 1 else WHITE)
            y += 42
    frame("intro", intro, FPS * 3); frame("outro", outro, FPS * 4)
    # convert battle frames? just concat via ffmpeg
    listf = Path(out).with_suffix(".txt")
    intro_mp4 = Path(out).with_suffix(".intro.mp4"); outro_mp4 = Path(out).with_suffix(".outro.mp4")
    for name, dest, n in (("intro", intro_mp4, FPS * 3), ("outro", outro_mp4, FPS * 4)):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                        "-i", str(frames_dir / f"{name}_%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)], check=True)
    listf.write_text("".join(f"file '{Path(x).resolve()}'\n" for x in (intro_mp4, battle, outro_mp4)))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listf),
                    "-vf", f"scale={W}:{H},fps={FPS}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out)], check=True)
    if tts:
        try:
            import edge_tts
            import asyncio
            text = f"McBench 排行榜。第一名 {rows[0]['model']}，均分 {rows[0]['avg_score']}。欢迎共建。"
            asyncio.run(edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural").save(str(Path(out).with_suffix(".mp3"))))
            dubbed = Path(out).with_suffix(".dubbed.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-i", str(Path(out).with_suffix(".mp3")),
                            "-c:v", "copy", "-c:a", "aac", "-shortest", str(dubbed)], check=True)
            shutil.move(dubbed, out)
        except Exception as e:  # noqa
            print(f"(TTS 不可用，仅字幕：{e})")
    shutil.rmtree(frames_dir, ignore_errors=True)
    for p in (intro_mp4, outro_mp4, battle, listf):
        Path(p).unlink(missing_ok=True)
    return out
