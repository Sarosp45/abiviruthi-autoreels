"""Turn one script file (queue/*.json) into a 1080x1920 MP4 reel.

    python -m reelmaker.render queue/2026-11-02-1230.json out/2026-11-02-1230.mp4

Steps: Tamil voice per scene (free Microsoft Edge voices) -> scene timing ->
music + whoosh sounds -> frames from template.html in headless Chromium -> ffmpeg.
If the voice service is unreachable the reel is still made, with music only.
"""
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from reelmaker import images

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FPS = 30
SR = 48000
W, H = 1080, 1920


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


# ---------- voice ----------

async def _tts(text, voice, rate, out):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate).save(str(out))


def make_voice(text, voice, rate, out):
    """Returns the path to an mp3, or None if the voice service failed."""
    if not text:
        return None
    for _ in range(3):
        try:
            asyncio.run(_tts(text, voice, rate, out))
            if out.exists() and out.stat().st_size > 1000:
                return out
        except Exception as e:  # network hiccups are common; retry, then give up quietly
            print(f"  voice failed: {e}", file=sys.stderr)
    return None


def read_audio(path):
    """Decode any audio file to mono float32 at SR."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


# ---------- timing ----------

def est_speech_seconds(text):
    return len(text or "") / 15 + 0.3


MIN_LEN = {"hook": 2.2, "point": 2.6, "stat": 2.6, "list": 3.5, "myth": 4.0, "cta": 2.4}


def plan_scenes(script, voices):
    """Give every scene a start/end so the voice fits, keeping things snappy."""
    t = 0.0
    out = []
    for s, v in zip(script["scenes"], voices):
        s = dict(s)
        talk = len(v["main"]) / SR if v["main"] is not None else est_speech_seconds(s.get("say"))
        s["talk"] = round(talk, 2)
        if s["type"] == "quiz":
            after = len(v["after"]) / SR if v["after"] is not None else est_speech_seconds(s.get("say_after"))
            cd = s.get("countdown", 3)
            s["reveal"] = round(max(talk + 0.4, 1.8) + cd, 2)   # 3-2-1 countdown after the question is read
            length = s["reveal"] + after + 0.6
        else:
            length = max(MIN_LEN[s["type"]], talk + 0.45)
        s["start"], s["end"] = round(t, 3), round(t + length, 3)
        t += length
        out.append(s)
    return out, t


# ---------- sound ----------

def synth_music(seconds, seed):
    """Soft, upbeat placeholder track so reels are never silent. Add real royalty-free
    mp3s to reelmaker/music/ and they will be used instead."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    bpm = 104
    beat = 60 / bpm
    roots = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]  # Am F C G
    rng.shuffle(roots)
    out = np.zeros(n, dtype=np.float32)
    bar = beat * 4
    for i in range(int(seconds / bar) + 1):
        a, b = int(i * bar * SR), min(n, int((i + 1) * bar * SR))
        if a >= n:
            break
        tt = t[a:b] - i * bar
        env = np.minimum(1, tt / 0.4) * np.exp(-tt / 3.5)
        for m in roots[i % 4]:
            f = 440 * 2 ** ((m - 69) / 12)
            out[a:b] += (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt)) * env * 0.05
        f = 440 * 2 ** ((roots[i % 4][0] - 12 - 69) / 12)
        out[a:b] += np.sin(2 * np.pi * f * tt) * env * 0.12
    for k in range(int(seconds / beat)):          # soft kick + hat
        a = int(k * beat * SR)
        L = min(int(0.25 * SR), n - a)
        tt = np.arange(L) / SR
        out[a:a + L] += np.sin(2 * np.pi * (50 + 90 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 14) * 0.35
        h = a + int(beat / 2 * SR)
        if h < n:
            L = min(int(0.05 * SR), n - h)
            out[h:h + L] += rng.standard_normal(L).astype(np.float32) * np.exp(-np.arange(L) / SR * 90) * 0.04
    return out


def whoosh():
    L = int(0.45 * SR)
    tt = np.arange(L) / SR
    noise = np.random.default_rng(1).standard_normal(L).astype(np.float32)
    k = np.exp(-((tt - 0.18) ** 2) / 0.006)
    sm = np.convolve(noise, np.ones(18) / 18, mode="same")    # crude low-pass
    return (sm * k * 0.5).astype(np.float32)


def tone(freq, secs, decay, vol):
    tt = np.arange(int(secs * SR)) / SR
    return (np.sin(2 * np.pi * freq * tt) * np.exp(-tt * decay) * vol).astype(np.float32)


def build_audio(scenes, total, voices, music_files, music_vol, seed):
    n = int((total + 0.3) * SR)
    mix = np.zeros(n, dtype=np.float32)
    if music_files:
        m = read_audio(music_files[seed % len(music_files)])
        m = np.tile(m, int(n / len(m)) + 1)[:n]
    else:
        m = synth_music(n / SR, seed)
    fade = np.minimum(1, np.arange(n) / (0.5 * SR)) * np.minimum(1, (n - np.arange(n)) / (1.2 * SR))
    has_voice = any(v["main"] is not None for v in voices)
    mix += m * fade * (music_vol if has_voice else min(1.0, music_vol * 3))
    w = whoosh()
    tick = tone(1800, 0.06, 60, 0.25)
    ding = np.concatenate([tone(1318, 0.5, 6, 0.3)]) + np.pad(tone(1760, 0.45, 6, 0.25), (int(0.05 * SR), 0))[:int(0.5 * SR)]

    def put(clip, at):
        a = int(at * SR)
        if 0 <= a < n:
            mix[a:a + len(clip)] += clip[: n - a]

    for s, v in zip(scenes, voices):
        put(w, max(0, s["start"] - 0.2))
        if s["type"] == "quiz":
            r = s["start"] + s["reveal"]
            for k in range(1, s.get("countdown", 3) + 1):
                put(tick, r - k)
            put(ding, r)
        for key, at in (("main", s["start"] + 0.25), ("after", s.get("reveal", 0) + s["start"] + 0.15)):
            clip = v[key]
            if clip is not None:
                a = int(at * SR)
                mix[a:a + len(clip)] += clip[: max(0, n - a)]
    peak = np.abs(mix).max() or 1
    return mix * min(1.0, 0.95 / peak)


# ---------- video ----------

def chromium_path():
    p = os.environ.get("CHROMIUM_PATH")
    return p if p and Path(p).exists() else None


def render_frames(reel, total, wav, out_mp4):
    from playwright.sync_api import sync_playwright
    html = (HERE / "template.html").read_text(encoding="utf-8")
    data = json.dumps(reel, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("<script>", f"<script>window.REEL={data};</script>\n<script>", 1)
    with tempfile.NamedTemporaryFile("w", suffix=".html", dir=HERE, delete=False, encoding="utf-8") as f:
        f.write(html)
        page_file = Path(f.name)
    frames = int(total * FPS)
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                           "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                           "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-shortest",
                           "-movflags", "+faststart", str(out_mp4)], stdin=subprocess.PIPE)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium_path())
            page = browser.new_page(viewport={"width": W, "height": H})
            page.goto(page_file.as_uri())
            page.evaluate("window.READY")
            for i in range(frames):
                page.evaluate(f"seek({i / FPS})")
                ff.stdin.write(page.screenshot(type="jpeg", quality=92))
                if i % 150 == 0:
                    print(f"  frame {i}/{frames}")
            browser.close()
    finally:
        ff.stdin.close()
        ff.wait()
        page_file.unlink(missing_ok=True)
    if ff.returncode:
        raise RuntimeError("ffmpeg failed")


def render(script_path, out_mp4, use_voice=True):
    cfg = load_config()
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    series = cfg["series"].get(script.get("series"), {})
    voice = script.get("voice") or series.get("voice") or cfg["voice"]
    rate = cfg.get("voice_rate", "+8%")
    seed = int(hashlib.md5(Path(script_path).name.encode()).hexdigest(), 16) % 10_000
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        limit = cfg.get("max_seconds", 39.5)
        for rate in [rate, "+18%", "+26%"]:     # talk a little faster if the reel runs long
            voices = []
            for i, s in enumerate(script["scenes"]):
                v = {}
                for key, field in (("main", "say"), ("after", "say_after")):
                    mp3 = make_voice(s.get(field), voice, rate, tmp / f"{i}{key}.mp3") if use_voice else None
                    v[key] = read_audio(mp3) if mp3 else None
                voices.append(v)
            scenes, total = plan_scenes(script, voices)
            if total <= limit or not any(v["main"] is not None for v in voices):
                break
        if total > limit + 0.5:
            raise ValueError(f"reel is {total:.0f}s, over the {limit:.0f}s limit; shorten the script")
        music = sorted((HERE / "music").glob("*.mp3"))
        wav = tmp / "mix.wav"
        mix = build_audio(scenes, total, voices, music, cfg.get("music_volume", 0.14), seed)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                        "-ac", "2", str(wav)], input=mix.astype(np.float32).tobytes(), check=True)
        credits = []
        for i, sc in enumerate(script["scenes"]):
            if sc.get("image"):
                path, credit = images.find(sc["image"], tmp / f"img{i}.jpg", sc.get("image_source"))
                if path:
                    sc["img"], sc["credit"] = Path(path).resolve().as_uri(), credit
                    if credit and credit not in credits:
                        credits.append(credit)
        scenes = [{**p, **{k: sc[k] for k in ("img", "credit") if k in sc}} for p, sc in zip(scenes, script["scenes"])]
        styles = cfg.get("styles", ["bold"])
        style = script.get("style") or styles[seed % len(styles)]
        reel = {
            "style": style,
            "brand": cfg["brand"], "logo": cfg.get("logo_letter"), "handle": cfg["handle"],
            "series": script.get("series_label") or series.get("label") or script.get("series", ""),
            "theme": {**cfg.get("theme", {}), **series.get("theme", {}), **script.get("theme", {})},
            "scenes": scenes,
        }
        print(f"rendering {Path(script_path).name}: {style} style, {len(scenes)} scenes, {total:.1f}s")
        render_frames(reel, total, wav, out_mp4)
    return out_mp4, credits


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    render(args[0], args[1], use_voice="--no-voice" not in sys.argv)
