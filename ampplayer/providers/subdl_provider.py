"""عميل SubDL (subdl.com).

البنية المُتحقَّق منها:
  1. /search/<query>            -> بطاقات على مستوى الفيلم:
       <a href="/subtitle/sdXXXXXX/<slug>">
         <h3>The Matrix (1999)</h3>
         ... <div ...>11 subtitles</div>
  2. /subtitle/sdXXXXXX/<slug>  -> مجموعات اللغات:
       <div ... data-language="english" data-language-name="English">
         <a href="/subtitle/sdXXXXXX/<slug>/english"> <span>EN</span> <h2>English</h2>
  3. ملفات التحميل داخل المجموعة:
       <li data-n-id="..." data-downloads="5108" data-id="560923" ...>
         <a data-subtitle-title href="/s/info/..."><h4>The Matrix (1999) RM (1080p ...)</h4>
       وروابط https://dl.subdl.com/subtitle/<id>.zip

ملاحظة: نتائج البحث على مستوى الفيلم، لذا نستخدم expand()
لعرض ملفات الترجمة الفعلية بلغاتها وإصداراتها.
"""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import quote, urljoin

from .http_client import get, make_session
from .models import SITE_LANG_NAMES, SearchOutcome, SubtitleResult

SITE = "subdl"
SITE_NAME = "SubDL"
HOME = "https://subdl.com"
DOWNLOAD_RE = re.compile(
    r'href="(https://dl\.subdl\.com/subtitle/[A-Za-z0-9._-]+\.zip)"', re.IGNORECASE
)
_CARD_RE = re.compile(
    r'<a[^>]+href="(?P<path>/subtitle/(?P<id>sd\d+)/(?P<slug>[^"?#"]+))"[^>]*>\s*'
    r'(?P<inner>[\s\S]{0,2000}?)</a>',
    re.IGNORECASE,
)
_H3_RE = re.compile(r"<h3[^>]*>([^<]+)</h3>", re.IGNORECASE)
_SUBCOUNT_RE = re.compile(r"([\d,]+)\s*subtitles?", re.IGNORECASE)
_LANG_GROUP_RE = re.compile(
    r'data-language="(?P<code>[^"]+)"[^>]*data-language-name="(?P<name>[^"]+)"'
    r'[\s\S]*?<span[^>]*>\s*(?P<abbr>[A-Z]{2,4})\s*</span>\s*<h2[^>]*>(?P<h2>[^<]+)</h2>',
    re.IGNORECASE,
)
_ITEM_RE = re.compile(
    r'<li[^>]*data-n-id="(?P<nid>[^"]+)"[^>]*data-downloads="(?P<dls>[^"]*)"(?P<attrs>[^>]*)>(?P<inner>[\s\S]{0,1600}?)</li>',
    re.IGNORECASE,
)
_H4_RE = re.compile(r"<h4[^>]*>([^<]+)</h4>", re.IGNORECASE)
_QUALITY_RE = re.compile(r'data-quality="(?P<q>[^"]+)"', re.IGNORECASE)
_EP_RE = re.compile(r"S(\d{1,2})E(\d{1,3})", re.IGNORECASE)

_CODE_BY_NAME: dict[str, str] = {}
for _c, _names in SITE_LANG_NAMES.items():
    for _n in _names:
        _CODE_BY_NAME.setdefault(_n.lower(), _c)


def search_url(query: str, lang: str = "") -> str:
    return f"{HOME}/search/{quote((query or '').strip())}"


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _norm_lang(name: str) -> str:
    n = (name or "").strip().lower()
    if n in _CODE_BY_NAME:
        return _CODE_BY_NAME[n]
    n2 = re.sub(r"[^a-z]", "", n)
    for code, names in SITE_LANG_NAMES.items():
        for alias in names:
            if re.sub(r"[^a-z]", "", alias.lower()) == n2:
                return code
    # مطابقة جزئية على حدود الكلمات (تفادياً لمشكلة "vie" داخل "movie")
    for code, names in SITE_LANG_NAMES.items():
        for alias in names:
            if len(alias) >= 4 and re.search(rf"\b{re.escape(alias)}\b", n):
                return code
    return ""


def search(query: str, lang: str = "", season: str = "", episode: str = "",
           timeout: int = 20) -> SearchOutcome:
    out = SearchOutcome(site=SITE, site_name=SITE_NAME)
    query = (query or "").strip()
    if not query:
        out.error = "empty_query"
        return out

    s = make_session()
    s.headers["Referer"] = f"{HOME}/"
    try:
        r = get(s, f"{HOME}/search/{quote(query)}", timeout=timeout)
    except Exception as exc:
        out.error = f"search_failed: {exc}"
        out.needs_manual = True
        out.manual_url = search_url(query)
        return out

    if r.status_code != 200:
        out.error = f"http_{r.status_code}"
        out.needs_manual = True
        out.manual_url = search_url(query)
        return out

    results = _parse_search_page(r.text)
    if not results:
        out.needs_manual = True
        out.manual_url = search_url(query)
        return out
    out.results = results
    return out


def _parse_search_page(html: str) -> List[SubtitleResult]:
    results: List[SubtitleResult] = []
    seen: set[str] = set()
    for m in _CARD_RE.finditer(html):
        path = m.group("path")
        if path in seen:
            continue
        seen.add(path)
        inner = m.group("inner")
        h3 = _H3_RE.search(inner)
        title = _clean(h3.group(1)) if h3 else m.group("slug").replace("-", " ")
        year = ""
        ym = re.search(r"\((19\d{2}|20\d{2})\)", title)
        if ym:
            year = ym.group(1)
            title = title.replace(ym.group(0), "").strip()
        count = 0
        cm = _SUBCOUNT_RE.search(_clean(inner))
        if cm:
            try:
                count = int(cm.group(1).replace(",", ""))
            except ValueError:
                count = 0
        results.append(
            SubtitleResult(
                site=SITE,
                site_name=SITE_NAME,
                title=title,
                release=title,
                year=year,
                kind="group",
                url=urljoin(HOME, path),
                source_id=m.group("id"),
                downloads=count,
                note=str(count),
            )
        )
    return results


# ------------------------------------------------------------------ التوسيع
def expand(result: SubtitleResult, timeout: int = 25) -> List[SubtitleResult]:
    """
    يفتح صفحة الفيلم ويستخرج ملفات الترجمة بلغاتها وإصداراتها.
    """
    if not result.url:
        return []
    s = make_session()
    s.headers["Referer"] = f"{HOME}/"
    try:
        r = get(s, result.url, timeout=timeout)
    except Exception:
        return []
    if r.status_code != 200:
        return []

    html = r.text

    # خرائطLanguage boundaries: نحدّد مواضع بداية كل مجموعة لغة
    groups: list[tuple[int, str, str]] = []  # (position, code, name)
    for gm in re.finditer(
        r'data-language="(?P<code>[^"]+)"[^>]*data-language-name="(?P<name>[^"]+)"', html, re.I
    ):
        name = gm.group("name")
        groups.append((gm.start(), _norm_lang(name), name))

    # خرائط الملفات: نمر على كل <li data-n-id> ومعه رابط zip الخاص به
    files: list[tuple[int, str, dict]] = []
    zip_by_id: dict[str, str] = {}
    for zm in DOWNLOAD_RE.finditer(html):
        # مثال: .../subtitle/560923-1837981.zip  -> معرّف الملف قبل الشرطة
        tail = zm.group(1).rsplit("/", 1)[-1]
        head = tail.split("-")[0]
        if head:
            zip_by_id.setdefault(head, zm.group(1))

    for im in _ITEM_RE.finditer(html):
        attrs = im.group("attrs") or ""
        nid = im.group("nid")
        dls = 0
        try:
            dls = int((im.group("dls") or "0").replace(",", ""))
        except ValueError:
            dls = 0
        idm = re.search(r'data-id="([^"]+)"', attrs)
        sid = idm.group(1) if idm else ""
        h4 = _H4_RE.search(im.group("inner"))
        title = _clean(h4.group(1)) if h4 else ""
        # الجودة: أقرب data-quality قبل هذا الملف
        quality = ""
        qpos = html.rfind('data-quality="', 0, im.start())
        if qpos != -1:
            qm = _QUALITY_RE.search(html[qpos:qpos + 120])
            if qm:
                quality = qm.group("q")
        season = episode = ""
        em = _EP_RE.search(title)
        if em:
            season, episode = em.group(1), em.group(2)
        else:
            sm = re.search(r"[Ss]eason[\s._-]*(\d{1,2})", title)
            if sm:
                season = sm.group(1)
            em2 = re.search(r"[Ee]pisode[\s._-]*(\d{1,3})", title)
            if em2:
                episode = em2.group(1)
        url = zip_by_id.get(sid) or zip_by_id.get(nid) or ""
        files.append((im.start(), url, {
            "source_id": sid or nid,
            "title": title,
            "downloads": dls,
            "quality": quality,
            "season": season,
            "episode": episode,
        }))

    out: List[SubtitleResult] = []
    for pos, url, info in files:
        code, name = "", ""
        for gpos, gcode, gname in groups:
            if gpos <= pos:
                code, name = gcode, gname
            else:
                break
        out.append(
            SubtitleResult(
                site=SITE,
                site_name=SITE_NAME,
                title=result.title,
                release=info["title"] or result.title,
                year=result.year,
                language=name,
                language_code=code,
                season=info["season"] or result.season,
                episode=info["episode"] or result.episode,
                downloads=info["downloads"],
                kind="download" if url else "page",
                url=result.url,
                download_url=url,
                source_id=info["source_id"],
                note=info["quality"],
            )
        )
    return out


def resolve(result: SubtitleResult, timeout: int = 20) -> Optional[str]:
    """يضمن وجود رابط مباشر (يستدعي expand إن لزم)."""
    if result.download_url:
        return result.download_url
    if result.kind == "group" or not result.download_url:
        expanded = expand(result, timeout=timeout)
        for e in expanded:
            if e.download_url:
                result.download_url = e.download_url
                result.language = e.language or result.language
                result.language_code = e.language_code or result.language_code
                result.release = e.release
                result.downloads = e.downloads
                return e.download_url
    return None


def list_downloads(page_url: str, timeout: int = 20) -> List[str]:
    s = make_session()
    s.headers["Referer"] = f"{HOME}/"
    try:
        r = get(s, page_url, timeout=timeout)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    seen: set[str] = set()
    urls: List[str] = []
    for m in DOWNLOAD_RE.finditer(r.text):
        u = m.group(1)
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls