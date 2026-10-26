"""Upload a finished reel to Instagram, Facebook Page and YouTube using only the
free official APIs. Each function returns the new post id or raises on failure.

Secrets come from environment variables (GitHub > Settings > Secrets):
  META_PAGE_TOKEN   long-lived Facebook Page access token (never expires)
  FB_PAGE_ID        Facebook Page id
  IG_USER_ID        Instagram Business account id linked to that Page
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN   from Google OAuth Playground
"""
import json
import os
import time
from pathlib import Path

import requests

GRAPH = "https://graph.facebook.com/" + os.environ.get("GRAPH_VERSION", "v23.0")
RUPLOAD = "https://rupload.facebook.com"


def _check(r):
    if r.status_code >= 400:
        raise RuntimeError(f"{r.request.method} {r.url.split('?')[0]} -> {r.status_code}: {r.text[:400]}")
    return r.json() if r.content else {}


def instagram(video: Path, caption: str) -> str:
    token, ig = os.environ["META_PAGE_TOKEN"], os.environ["IG_USER_ID"]
    c = _check(requests.post(f"{GRAPH}/{ig}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption,
        "share_to_feed": "true", "access_token": token}))
    cid = c["id"]
    data = video.read_bytes()
    _check(requests.post(f"{RUPLOAD}/ig-api-upload/{GRAPH.rsplit('/', 1)[1]}/{cid}", data=data, headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))}, timeout=600))
    for _ in range(60):  # Instagram processes the video before it can be published
        st = _check(requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": token}))
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram could not process the video: {st}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram processing timed out")
    return _check(requests.post(f"{GRAPH}/{ig}/media_publish", data={"creation_id": cid, "access_token": token}))["id"]


def facebook(video: Path, caption: str) -> str:
    token, page = os.environ["META_PAGE_TOKEN"], os.environ["FB_PAGE_ID"]
    s = _check(requests.post(f"{GRAPH}/{page}/video_reels", data={"upload_phase": "start", "access_token": token}))
    vid = s["video_id"]
    data = video.read_bytes()
    _check(requests.post(s.get("upload_url") or f"{RUPLOAD}/video-upload/{GRAPH.rsplit('/', 1)[1]}/{vid}", data=data,
                         headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))},
                         timeout=600))
    _check(requests.post(f"{GRAPH}/{page}/video_reels", data={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "description": caption, "access_token": token}))
    return vid


def youtube(video: Path, title: str, description: str, tags) -> str:
    tok = _check(requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}))["access_token"]
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:30],
                    "categoryId": "27", "defaultLanguage": "ta", "defaultAudioLanguage": "ta"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                      headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Type": "video/mp4"}, data=json.dumps(meta))
    _check(r)
    up = requests.put(r.headers["Location"], data=video.read_bytes(),
                      headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4"}, timeout=900)
    return _check(up)["id"]


def configured(name):
    need = {"instagram": ["META_PAGE_TOKEN", "IG_USER_ID"], "facebook": ["META_PAGE_TOKEN", "FB_PAGE_ID"],
            "youtube": ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]}[name]
    return all(os.environ.get(k) for k in need)
