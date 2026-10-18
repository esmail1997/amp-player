"""عميل Yifysubtitles (yifysubtitles.ch).

تدفق العمل المُتحقَّق منه:
  1. /ajax/search/?mov=<query>            -> JSON: [{"movie":..,"imdb":"tt..."}]
  2. /movie-imdb/<imdb_id>                -> قائمة مسارات الترجمة
  3. /subtitles/<slug>                    -> صفحة السطر
  4. /subtitle/<slug>.zip                 -> ملف مضغوط
"""

from __future__ import annotations

import re
from typing import List, Optional

from .http_client import get, make_session
from .models import LANG_BY_CODE, SITE_LANG_NAMES, SubtitleResult

SITE = "yifysubtitles"
SITE_NAME = "YifySubtitles"
HOME = "https://yifysubtitles.ch"

_SLUG_LANG_RE = re.compile(
    r"/subtitles/.*?-(" + "|".join(
        sorted({n for names in SITE_LANG_NAMES.values() for n in names if len(n) > 2},
               key=len, reverse=True)
    ) + r")-[a-z0-9]+-(\d+)$",
    re.IGNORECASE,
)

_CODE_BY_NAME: dict[str, str] = {}
for _code, _names in SITE_LANG_NAMES.items():
    for _n in _names:
        _CODE_BY_NAME.setdefault(_n.lower(), _code)


def search_url(query: str, lang: str = "") -> str:
    """رابط البحث اليدوي في المتصفح."""
    return f"{HOME}/search?q={query.strip()}"


def _match_lang(token: str, prefer: str) -> str:
    token = (token or "").lower()
    code = _CODE_BY_NAME.get(token, "")
    if not code:
        return ""
    if prefer and code == prefer:
        return code
    return code


def _filter_by_lang(results: List[SubtitleResult], lang: str) -> List[SubtitleResult]:
    if not lang:
        return results
    exact = [r for r in results if r.language_code == lang]
    if exact:
        return exact
    return results


def search(query: str, lang: str = "", season: str = "", episode: str = "", timeout: int = 20):
    """يبحث في YifySubtitles. يعيد SearchOutcome."""
    from .models import SearchOutcome

    out = SearchOutcome(site=SITE, site_name=SITE_NAME)
    query = (query or "").strip()
    if not query:
        out.error = "empty_query"
        return out

    s = make_session()
    s.headers["Referer"] = f"{HOME}/"

    # 1) بحث سريع بالاسم -> IMDb ID
    try:
        r = get(s, f"{HOME}/ajax/search/", params={"mov": query}, timeout=timeout,
                headers={"X-Requested-With": "XMLHttpRequest"})
        import json

        items = json.loads(r.text or "[]")
    except Exception as exc:
        out.error = f"search_failed: {exc}"
        out.needs_manual = True
        out.manual_url = search_url(query)
        return out

    if not items:
        out.needs_manual = True
        out.manual_url = search_url(query)
        return out

    # نختار أقرب نتيجة بالاسم
    def score(item: dict) -> int:
        name = str(item.get("movie", "")).lower()
        q = query.lower()
        if name.startswith(q):
            return 100
        if q in name:
            return 50
        return 0

    items.sort(key=score, reverse=True)

    all_results: List[SubtitleResult] = []
    errors: List[str] = []

    for item in items[:5]:
        imdb = str(item.get("imdb", ""))
        title = str(item.get("movie", ""))
        if not imdb:
            continue
        try:
            page = get(s, f"{HOME}/movie-imdb/{imdb}", timeout=timeout)
            if page.status_code != 200:
                errors.append(f"{imdb}:{page.status_code}")
                continue
            found = _parse_movie_page(page.text, title, lang)
            all_results.extend(found)
        except Exception as exc:
            errors.append(f"{imdb}:{exc}")
        if len(all_results) > 200:
            break

    out.results = _filter_by_lang(all_results, lang)
    if not out.results and errors:
        out.error = "; ".join(errors[:3])
    if not out.results:
        out.needs_manual = True
        out.manual_url = search_url(query)
    return out


def _parse_movie_page(html: str, title: str, lang: str) -> List[SubtitleResult]:
    """يستخرج روابط الترجمة من صفحة الفيلم."""
    results: List[SubtitleResult] = []
    seen: set[str] = set()

    # روابط /subtitles/<slug>
    for m in re.finditer(r'href="(/subtitles/([^"]+))"', html):
        path, slug = m.group(1), m.group(2)
        if path in seen:
            continue
        seen.add(path)
        sm = _SLUG_LANG_RE.match(path)
        code = ""
        if sm:
            code = _match_lang(sm.group(1), lang)
        else:
            code = _code_from_slug(slug)
        results.append(
            SubtitleResult(
                site=SITE,
                site_name=SITE_NAME,
                title=title,
                release=title,
                language_code=code,
                language=LANG_BY_CODE.get(code, ""),
                kind="page",
                url=f"{HOME}{path}",
                source_id=slug,
            )
        )

    # نربط اللغة من روابط صفحات الترجمة المجاورة إن وُجدت
    return results


def _code_from_slug(slug: str) -> str:
    low = slug.lower()
    for names in SITE_LANG_NAMES.values():
        pass
    for code, names in SITE_LANG_NAMES.items():
        for n in names:
            if len(n) > 2 and f"-{n}-" in low:
                return code
    return ""


def get_download_url(page_url: str, timeout: int = 20) -> Optional[str]:
    """يستخرج رابط التحميل المباشر من صفحة الترجمة."""
    s = make_session()
    s.headers["Referer"] = f"{HOME}/"
    try:
        r = get(s, page_url, timeout=timeout)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    # زر تحميل: /subtitle/<slug>.zip
    m = re.search(r'href="(/subtitle/[^"]+\.zip)"', r.text)
    if m:
        return f"{HOME}{m.group(1)}"
    m = re.search(r'href="(https?://[^"]+\.(?:zip|srt))"', r.text)
    if m:
        return m.group(1)
    return None


def resolve(result: SubtitleResult) -> Optional[str]:
    """يحوّل نتيجة من نوع page إلى رابط تحميل مباشر."""
    if result.download_url:
        return result.download_url
    if not result.url:
        return None
    dl = get_download_url(result.url)
    if dl:
        result.download_url = dl
    return dl