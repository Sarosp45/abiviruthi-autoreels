# Abiviruthi Auto-Reels

Makes Tamil motion-graphic reels under 40 seconds (no shooting) and posts them every day to
**Instagram, Facebook and YouTube Shorts**. Costs ₹0.

## How it works (the whole thing in 4 lines)

1. **Every week, Claude** researches trending Kovai facts, quizzes and land tips and writes next week's scripts into the `queue/` folder.
2. **GitHub** (free) turns each script into a video with animated Tamil text, a Tamil AI voice and music.
3. **Your phone** gets every video on Telegram with two buttons: **✅ Approve** or **❌ Skip**.
4. **At 12:30 pm and 7:30 pm** GitHub posts the day's reels to all three platforms and messages you "✅ Posted".

If you forget to tap, the reel still posts (you can switch this off: `"auto_approve": false` in `config.json`).

## Your weekly job (2 minutes)

- Open Telegram, watch the new reels, tap ✅ or ❌. That's it.
- Want to know what's coming? Send any message to your bot and it replies with the schedule.

## One-time setup (about 1 hour, Claude guides you step by step)

You will collect a few "keys" and paste them into GitHub:
**GitHub repo > Settings > Secrets and variables > Actions > New repository secret**.

| Secret name | What it is | Where you get it |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Your approval bot | Telegram > search **@BotFather** > `/newbot` > copy the token. Then open your new bot and send "hi". |
| `META_PAGE_TOKEN` | Lets the system post on your Facebook Page and Instagram | Facebook Graph API Explorer (Claude walks you through it) |
| `FB_PAGE_ID` | Your Facebook Page number | Same place |
| `IG_USER_ID` | Your Instagram Business account number | Same place |
| `PIXABAY_API_KEY` (recommended) | Real photos for general topics (land, homes, food, people) | pixabay.com > sign up free > open pixabay.com/api/docs and copy the key shown under "Parameters". Without it, only named places (like Adiyogi) get photos, from Wikimedia Commons. (`PEXELS_API_KEY` also works if you ever get one.) |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | Lets the system upload to YouTube | Google Cloud Console + OAuth Playground (Claude walks you through it) |

### Before Meta setup
- Instagram must be a **Professional account** (Business or Creator) and **linked to the Facebook Page**.

### Meta (Instagram + Facebook) steps
1. Go to developers.facebook.com, log in, **Create App** (choose the options for managing a Page and publishing to Instagram).
2. Open **Tools > Graph API Explorer**, pick your app, and add these permissions:
   `pages_show_list, pages_read_engagement, pages_manage_posts, instagram_basic, instagram_content_publish, business_management`.
3. Click **Generate Access Token** and allow everything.
4. Open **Access Token Debugger**, paste the token, click **Extend Access Token**, copy the long one.
5. Back in Graph API Explorer, paste the long token and run `me/accounts`. Copy the Page's `access_token` (this is `META_PAGE_TOKEN`, it never expires) and its `id` (`FB_PAGE_ID`).
6. Run `<FB_PAGE_ID>?fields=instagram_business_account`. The number shown is `IG_USER_ID`.

### YouTube steps
1. console.cloud.google.com > new project > **Enable "YouTube Data API v3"**.
2. **OAuth consent screen**: External, fill your name and email, then click **Publish app** (otherwise the key stops working after 7 days).
3. **Credentials > Create OAuth client ID > Web application**. Add redirect URI `https://developers.google.com/oauthplayground`. Copy the Client ID and Secret.
4. Open developers.google.com/oauthplayground > gear icon > tick **Use your own OAuth credentials** > paste them.
5. In scope box type `https://www.googleapis.com/auth/youtube.upload` > **Authorize** > log in with the channel's Google account > **Exchange authorization code for tokens** > copy the **Refresh token**.
6. **Important:** YouTube keeps videos from new apps *private* until you submit the free **YouTube API Services audit form**. Instagram and Facebook work immediately; YouTube goes public once the audit is approved (usually a few weeks).

## Daily limits (free)
- Instagram: up to 50 API posts a day. Facebook: no practical limit. YouTube: about 6 uploads a day. We post 2.
- GitHub (private repo): 2,000 free minutes a month. Making 14 reels takes about 80 minutes, posting about 2 minutes each run.

## Folders
- `queue/` one file per reel (script, caption, hashtags, post time). Claude writes these.
- `reelmaker/` the video maker (`template.html` is the design, `render.py` builds the video). Put royalty-free `.mp3` songs in `reelmaker/music/` to replace the built-in beat.
- `poster/` posting to Instagram, Facebook, YouTube and Telegram.
- `config.json` brand name, handle, colours per series, voice, post platforms.
- `state.json` what has been made, approved and posted (updated automatically, don't edit).

## Make a reel on your own computer (optional)
```
pip install -r requirements.txt && python -m playwright install chromium
python -m reelmaker.render queue/2026-11-02-1230.json out/test.mp4
```

## Script format (for Claude)
```json
{
  "series": "kovai-facts | did-you-know | land-tips | myth-fact | quiz | office-games",
  "post_at": "YYYY-MM-DD HH:MM (India time)",
  "scenes": [
    {"type": "hook",  "emoji": "🤯", "kicker": "small label", "title": "big line, *stars* = highlighted", "say": "voice line"},
    {"type": "point", "n": "1", "emoji": "🧵", "big": "112 அடி (optional, counts up)", "text": "...", "say": "..."},
    {"type": "stat",  "emoji": "🙏", "big": "112 அடி", "text": "...", "say": "..."},
    {"type": "list",  "title": "...", "icon": "✅", "items": ["...", "..."], "say": "..."},
    {"type": "myth",  "myth": "...", "fact": "...", "say": "..."},
    {"type": "quiz",  "kicker": "QUIZ", "question": "...", "options": ["A", "B", "C"], "answer": 1, "say": "...", "say_after": "answer line"},
    {"type": "cta",   "icons": ["❤️", "💾", "📤"], "title": "...", "text": "optional", "button": "FOLLOW 👉", "say": "..."}
  ],
  "caption": "post caption", "hashtags": "#a #b", "youtube_title": "title #Shorts"
}
```
Optional on any scene: `"image": "search words"` adds a real photo (full screen with a slow zoom, or a polaroid in paper style),
and `"image_source": "wiki"` looks on Wikimedia Commons first (best for named places). Photo credits are added to the caption automatically.
A quiz without `options` becomes a riddle: give `answer_text` and it is revealed after the countdown.
Optional at the top: `"style": "bold | paper | neon | clean"`. Leave it out and a style is picked at random for each reel.
Each week Claude picks a random mix of the reel types in REEL-TYPES.md, so the feed never looks the same two days running.

Rules: every reel must be **under 40 seconds** (the maker speeds up the voice a little if needed, and refuses scripts that are still too long).
Aim for 20 to 35 seconds: a hook in the first 2 seconds, 2 to 4 scenes, one call to action. Keep each "say" line to one or two short sentences.
Only use facts you can verify; wrong facts hurt the brand more than a missed day.
