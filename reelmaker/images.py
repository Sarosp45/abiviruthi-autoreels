"""Find a real photo for a scene from free sources, no paid plan needed.

Sources:
  - Pixabay (free API key in PIXABAY_API_KEY) or Pexels (PEXELS_API_KEY); no credit needed; for general topics
  - Wikimedia Commons, then Openverse (no key; a credit line is added) for named places:
    the scene says "image_source": "wiki"
If nothing suitable is found the scene simply uses the animated background.
Returns (local_path, credit) or (None, None). credit is "" when none is required.
"""
import os
import re
from pathlib import Path

import requests

UA = {"User-Agent": "AbiviruthiAutoReels/1.0 (https://github.com/Sarosp45/abiviruthi-autoreels)"}
OK_LICENSES = re.compile(r"^(cc0|public domain|pd|cc by(-sa)?( \d\.\d)?)", re.I)


def _download(url, out, headers=None):
    r = requests.get(url, headers={**UA, **(headers or {})}, timeout=60)
    r.raise_for_status()
    if len(r.content) < 20_000:          # too small to look good full screen
        raise ValueError("image too small")
    out.write_bytes(r.content)
    return out


def pexels(query, out):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return None, None
    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key},
                     params={"query": query, "orientation": "portrait", "per_page": 5}, timeout=30)
    r.raise_for_status()
    for p in r.json().get("photos", []):
        try:
            return _download(p["src"].get("portrait") or p["src"]["large2x"], out), ""
        except Exception:
            continue
    return None, None


def pixabay(query, out):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return None, None
    r = requests.get("https://pixabay.com/api/", timeout=30, params={
        "key": key, "q": query[:100], "image_type": "photo", "orientation": "vertical",
        "safesearch": "true", "per_page": 5, "order": "popular"})
    r.raise_for_status()
    for p in r.json().get("hits", []):
        try:
            return _download(p["largeImageURL"], out), ""
        except Exception:
            continue
    return None, None


def _strip(html):
    return re.sub(r"<[^>]+>", "", html or "").strip()


def wikimedia(query, out):
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": 6, "gsrlimit": 8, "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1400})
    r.raise_for_status()
    pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = _strip(meta.get("LicenseShortName", {}).get("value"))
        if info.get("width", 0) < 900 or not OK_LICENSES.match(lic):
            continue
        try:
            _download(info.get("thumburl") or info["url"], out)
        except Exception:
            continue
        artist = _strip(meta.get("Artist", {}).get("value"))[:60] or "Unknown"
        return out, f"{artist} / Wikimedia Commons ({lic})"
    return None, None


def openverse(query, out):
    r = requests.get("https://api.openverse.org/v1/images/", headers=UA, timeout=30, params={
        "q": query, "license_type": "commercial", "page_size": 8, "size": "large"})
    r.raise_for_status()
    for p in r.json().get("results", []):
        try:
            _download(p["url"], out)
        except Exception:
            continue
        lic = f"CC {p.get('license', '').upper()} {p.get('license_version', '')}".strip()
        if p.get("license") in ("cc0", "pdm"):
            lic = "Public domain"
        return out, f"{(p.get('creator') or 'Unknown')[:60]} / {p.get('source', 'Openverse')} ({lic})"
    return None, None


def find(query, out: Path, prefer=None):
    test_dir = os.environ.get("REEL_TEST_IMAGES")      # offline testing: use local pictures
    if test_dir:
        pics = sorted(Path(test_dir).glob("*.jpg"))
        if pics:
            return pics[hash(query) % len(pics)], "Test photo"
    # Named places (Adiyogi, Marudhamalai...) come from Wikimedia/Openverse. General topics use Pexels only:
    # the free-licence archives return random foreign photos for generic words (a Dutch "for sale" sign for "land plot").
    order = [wikimedia, openverse, pixabay, pexels] if prefer == "wiki" else [pixabay, pexels]
    for source in order:
        try:
            path, credit = source(query, out)
            if path:
                print(f"  photo for '{query}' from {source.__name__}")
                return path, credit
        except Exception as e:
            print(f"  {source.__name__} failed for '{query}': {e}")
    return None, None
