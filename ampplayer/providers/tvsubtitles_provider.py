"""عميل TVSubtitles (tvsubtitles.net).

ملاحظة: موقع TVSubtitles أوقف نقطة البحث الداخلية،
لذلك يوفّر هذا العميل:
  - قراءة صفحة الترجمة وتحليلها (/subtitle-XXXXX.html)
  - تحميل الملف من /download-XXXXX.html
  - فتح الموقع في المتصفح للبحث اليدوي
"""

from __future__ import annotations

import re
from typing import Optional

from .http_client import get, make_session
from .models import LANG_BY_CODE, SITE_LANG_NAMES, SearchOutcome, SubtitleResult

SITE = "tvsubtitles"
SITE_NAME = "TVSubtitles"
HOME = "https://www.tvsubtitles.net"


def search_url(query: str, lang: str = "") -> str:
    return f"{HOME}/"


def _strip_html(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def parse_subtitle_page(page_url: str, timeout: int = 20) -> Optional[SubtitleResult]:
    """
    يحلّل صفحة ترجمة مفردية في TVSubtitles.
    أمثلة روابط: https://www.tvsubtitles.net/subtitle-326040.html
    """
    s = make_session()
    s.headers["Referer"] = f"{HOME}/"
    try:
        r = get(s, page_url, timeout=timeout)
    except Exception:
        return None
    if r.status_code != 200:
        return None

    text = _strip_html(r.text)
    m = re.search(r"Download\s+(?:latest\s+)?(.+?)\s+subtitles", text, re.I)
    title = m.group(1).strip() if m else ""

    lang = ""
    lm = re.search(r"Download\s+([A-Za-z]+)\s+subtitles", text, re.I)
    if lm:
        name = lm.group(1).lower()
        for code, names in SITE_LANG_NAMES.items():
            if name in names:
                lang = code
                break

    season = episode = ""
    sm = re.search(r"(\d+)x(\d+)", title)
    if sm:
        season, episode = sm.group(1), sm.group(2)

    season_m = re.search(r"season\s+(\d+)\s+episode\s+(\d+)", text, re.I)
    if season_m:
        season, episode = season_m.group(1), season_m.group(2)

    ep_title = ""
    em = re.search(r"episode title:\s*(.+?)\s+episode number", text, re.I)
    if em:
        ep_title = em.group(1).strip()

    filename = ""
    fm = re.search(r"filename:\s*(\S+)", text, re.I)
    if fm:
        filename = fm.group(1).strip()

    release = ""
    rm = re.search(r"release:\s*(.+?)\s+filename", text, re.I)
    if rm:
        release = rm.group(1).strip()

    dl_count = 0
    dm = re.search(r"(\d[\d,]*)\s*downloads", text, re.I)
    if dm:
        try:
            dl_count = int(dm.group(1).replace(",", ""))
        except ValueError:
            dl_count = 0

    # رابط التحميل
    dl_url = ""
    dm2 = re.search(r'href="(download-[\d-]+\.html)"', r.text)
    if dm2:
        dl_url = f"{HOME}/{dm2.group(1)}"

    res = SubtitleResult(
        site=SITE,
        site_name=SITE_NAME,
        title=title or filename or "TVSubtitles",
        release=release,
        language_code=lang,
        language=LANG_BY_CODE.get(lang, ""),
        season=season,
        episode=episode,
        downloads=dl_count,
        kind="page",
        url=page_url,
        download_url=dl_url,
        note=ep_title,
    )
    return res


def search(
    query: str,
    lang: str = "",
    season: str = "",
    episode: str = "",
    timeout: int = 20,
) -> SearchOutcome:
    """
    البحث في TVSubtitles غير متاح عبر API؛
    نرجع رسالة توجّه المستخدم للمتصفح.
    """
    out = SearchOutcome(site=SITE, site_name=SITE_NAME)
    query = (query or "").strip()
    if not query:
        out.error = "empty_query"
        return out
    out.needs_manual = True
    out.manual_url = f"{HOME}/"
    return out


def resolve(result: SubtitleResult, timeout: int = 20) -> Optional[str]:
    """
    يحوّل نتيجة إلى رابط تحميل مباشر.
    صفحة TVSubtitles تتطلب نقراً (cookie) للحصول على رابط .zip.
    """
    if result.download_url:
        return result.download_url
    if not result.url:
        return None
    parsed = parse_subtitle_page(result.url, timeout=timeout)
    if parsed and parsed.download_url:
        result.download_url = parsed.download_url
        return parsed.download_url
    return None