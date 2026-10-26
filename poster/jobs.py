"""The two jobs GitHub runs for you.

  python -m poster.jobs make   render new scripts in queue/, store the videos, send previews to Telegram
  python -m poster.jobs post   read Approve/Skip taps, post everything that is due, report back on Telegram

All progress is kept in state.json so nothing is posted twice.
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from poster import platforms, telegram

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state.json"
OUT = ROOT / "out"
RELEASE = "reels"          # one GitHub release holds every rendered video
MAX_TRIES = 3


def load(p, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save_state(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def cfg():
    return load(ROOT / "config.json", {})


def now_local():
    return datetime.now(ZoneInfo(cfg().get("timezone", "Asia/Kolkata"))).replace(tzinfo=None)


def due_at(script):
    return datetime.strptime(script["post_at"], "%Y-%m-%d %H:%M")


def gh(*args, check=True):
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


def chat_id(st):
    """Remember the first person who messages the bot; they are the owner."""
    return st.get("telegram_chat")


def full_caption(s, credits=()):
    text = s.get("caption", "") + "\n\n" + s.get("hashtags", "")
    if credits:   # Creative Commons photos must be credited
        text += "\n\n📷 " + "; ".join(credits)
    return text.strip()


# ---------- make ----------

def make():
    from reelmaker.render import render
    st = load(STATE, {"items": {}})
    read_taps(st)
    if gh("release", "view", RELEASE, check=False).returncode:
        gh("release", "create", RELEASE, "--title", "Rendered reels", "--notes", "Videos made by the reel maker.")
    for path in sorted((ROOT / "queue").glob("*.json")):
        iid = path.stem
        item = st["items"].get(iid)
        if item and item["status"] != "render_failed":
            continue
        s = load(path, {})
        mp4 = OUT / f"{iid}.mp4"
        try:
            _, credits = render(path, mp4)
            gh("release", "upload", RELEASE, str(mp4), "--clobber")
        except Exception as e:
            print(f"render failed for {iid}: {e}")
            st["items"][iid] = {"status": "render_failed", "error": str(e)[:300]}
            telegram.say(chat_id(st), f"⚠️ Could not make reel {iid}: {str(e)[:200]}")
            save_state(st)
            continue
        item = st["items"][iid] = {"status": "waiting", "post_at": s["post_at"], "done": {}, "tries": 0,
                                   "credits": credits}
        if chat_id(st):
            when = due_at(s).strftime("%a %d %b, %I:%M %p")
            item["tg_msg"] = telegram.send_preview(
                chat_id(st), mp4, f"🎬 {s.get('youtube_title', iid)}\n🗓 Posts on {when}\n\n"
                f"Tap ✅ to approve or ❌ to skip." + ("\n(If you don't tap, it posts anyway.)" if cfg().get("auto_approve") else ""),
                iid)
        save_state(st)
    save_state(st)


# ---------- post ----------

def read_taps(st):
    if not telegram.enabled():
        return
    ups, st["tg_offset"] = telegram.updates(st.get("tg_offset", 0))
    for u in ups:
        if "message" in u:
            chat = u["message"]["chat"]["id"]
            if not st.get("telegram_chat"):
                st["telegram_chat"] = chat
                telegram.say(chat, "👋 Connected! Your reels will come here for approval, and I'll tell you when each one is posted.")
            elif chat == st["telegram_chat"]:
                telegram.say(chat, status_text(st))
        cb = u.get("callback_query")
        if cb and ":" in cb.get("data", "") and cb["message"]["chat"]["id"] == st.get("telegram_chat"):
            act, iid = cb["data"].split(":", 1)
            item = st["items"].get(iid)
            if not item or item["status"] in ("posted", "partly_posted"):
                telegram.answer(cb["id"], "Already posted")
                continue
            item["status"] = "approved" if act == "ok" else "skipped"
            telegram.answer(cb["id"], "Approved ✅" if act == "ok" else "Skipped ❌")
            telegram.mark(st["telegram_chat"], cb["message"]["message_id"],
                          "✅ Approved" if act == "ok" else "❌ Skipped, will not post")


def status_text(st):
    upcoming = sorted((v["post_at"], k, v["status"]) for k, v in st["items"].items()
                      if v["status"] in ("waiting", "approved"))
    if not upcoming:
        return "📭 No reels waiting. Ask Claude for next week's batch!"
    lines = [f"• {p}  {k}  ({'approved' if s == 'approved' else 'not tapped yet'})" for p, k, s in upcoming[:14]]
    return "📅 Coming up:\n" + "\n".join(lines)


def post():
    st = load(STATE, {"items": {}})
    read_taps(st)
    save_state(st)
    c = cfg()
    wanted = [n for n, on in c.get("platforms", {}).items() if on and platforms.configured(n)]
    if not wanted:
        print("No platform is connected yet, so nothing can be posted.")
    ok_states = {"approved", "partly_posted"} | ({"waiting"} if c.get("auto_approve") else set())
    for iid, item in sorted(st["items"].items(), key=lambda kv: kv[1].get("post_at", "")):
        if not wanted or item["status"] not in ok_states or item.get("tries", 0) >= MAX_TRIES:
            continue
        if datetime.strptime(item["post_at"], "%Y-%m-%d %H:%M") > now_local():
            continue
        s = load(ROOT / "queue" / f"{iid}.json", {})
        mp4 = OUT / f"{iid}.mp4"
        if not mp4.exists():
            OUT.mkdir(exist_ok=True)
            gh("release", "download", RELEASE, "-p", mp4.name, "-D", str(OUT), "--clobber")
        item["tries"] = item.get("tries", 0) + 1
        errors = []
        tags = [h.lstrip("#") for h in s.get("hashtags", "").split() if h.startswith("#")]
        for name in wanted:
            if name in item["done"]:
                continue
            try:
                if name == "youtube":
                    pid = platforms.youtube(mp4, s.get("youtube_title", iid), full_caption(s, item.get("credits", [])), tags)
                else:
                    pid = getattr(platforms, name)(mp4, full_caption(s, item.get("credits", [])))
                item["done"][name] = pid
                print(f"{iid}: posted to {name} ({pid})")
            except Exception as e:
                errors.append(f"{name}: {str(e)[:250]}")
                print(f"{iid}: {name} failed: {e}")
        item["errors"] = errors
        item["status"] = "posted" if all(n in item["done"] for n in wanted) else "partly_posted"
        save_state(st)
        done = ", ".join(item["done"]) or "nowhere yet"
        msg = f"✅ Posted '{s.get('youtube_title', iid)}' to {done}."
        if errors:
            msg += "\n⚠️ Problems (I'll retry next run):\n" + "\n".join(errors)
        telegram.say(chat_id(st), msg)
        telegram.mark(chat_id(st), item.get("tg_msg"), "🚀 Posted" if not errors else "⚠️ Partly posted")
    left = [k for k, v in st["items"].items() if v["status"] in ("waiting", "approved")]
    if not left and st.get("warned_empty") != now_local().date().isoformat():
        st["warned_empty"] = now_local().date().isoformat()
        telegram.say(chat_id(st), "📭 All scheduled reels are posted. Ask Claude for next week's batch!")
    save_state(st)


if __name__ == "__main__":
    {"make": make, "post": post}[sys.argv[1]]()
