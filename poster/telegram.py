"""Tiny Telegram bot helper: sends reel previews with Approve / Skip buttons and
reads the taps. Free, and works on any phone.

  TELEGRAM_BOT_TOKEN  from @BotFather
  The chat is found automatically: just send "hi" to your bot once.
"""
import json
import os

import requests


def _api(method, **kw):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not tok:
        return None
    files = kw.pop("files", None)
    r = requests.post(f"https://api.telegram.org/bot{tok}/{method}", data=kw, files=files, timeout=300)
    out = r.json()
    if not out.get("ok"):
        print(f"telegram {method} failed: {out}")
        return None
    return out["result"]


def enabled():
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


def buttons(item_id):
    return json.dumps({"inline_keyboard": [[
        {"text": "✅ Approve", "callback_data": f"ok:{item_id}"},
        {"text": "❌ Skip", "callback_data": f"no:{item_id}"}]]})


def send_preview(chat, video_path, text, item_id):
    with open(video_path, "rb") as f:
        res = _api("sendVideo", chat_id=chat, caption=text[:1000], reply_markup=buttons(item_id),
                   supports_streaming="true", files={"video": f})
    return res and res["message_id"]


def say(chat, text):
    if chat:
        _api("sendMessage", chat_id=chat, text=text[:4000])


def mark(chat, message_id, text):
    """Replace the buttons under a preview with a status line."""
    if chat and message_id:
        _api("editMessageReplyMarkup", chat_id=chat, message_id=message_id,
             reply_markup=json.dumps({"inline_keyboard": [[{"text": text, "callback_data": "noop"}]]}))


def updates(offset):
    """Returns (list of updates, next offset). Telegram keeps taps for 24 hours,
    and the system checks at least twice a day."""
    res = _api("getUpdates", offset=offset, timeout=0, allowed_updates=json.dumps(["message", "callback_query"])) or []
    nxt = max([u["update_id"] for u in res], default=offset - 1) + 1
    return res, nxt


def answer(callback_id, text):
    _api("answerCallbackQuery", callback_query_id=callback_id, text=text)
