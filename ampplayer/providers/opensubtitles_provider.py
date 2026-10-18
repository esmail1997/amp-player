"""عميل OpenSubtitles.

للموقع مساران:

1. **واجهة REST القديمة** ``rest.opensubtitles.org``: تعمل **بدون مفتاح API**
   وتعيد نتائج كاملة مع رابط تحميل مباشر. هي مسارنا الافتراضي، فلا يحتاج
   المستخدم إلى أي تسجيل ولا إلى مفتاح.
   (الويب الحالي www.opensubtitles.com محمي بـ Cloudflare أمام الـ scraping
   والـ API الحديثة ترفض من دون مفتاح، أما الواجهة القديمة فلا تزال حيّة.)

2. **واجهة REST الحديثة** ``api.opensubtitles.com/api/v1``: تتطلب مفتاحاً،
   نستعملها احتياطياً إذا تعذّر المسار الأول ووفّر المستخدم مفتاحاً.

إن فشل المساران معاً يبقى خيار «فتح الموقع في المتصفح» للمستخدم.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Optional

from .http_client import get, make_session
from .models import SearchOutcome, SubtitleResult

SITE = "opensubtitles"
SITE_NAME = "OpenSubtitles"
HOME = "https://www.opensubtitles.com"
LEGACY = "https://rest.opensubtitles.org"
API = "https://api.opensubtitles.com/api/v1"

# نقرأ المفتاح من متغير البيئة أو من ملف إعدادات بجانب البرنامج
_KEY_FILE = "opensubtitles_key.txt"


def _load_key() -> str:
    env = os.environ.get("OPENSUBTITLES_API_KEY", "").strip()
    if env:
        return env
    try:
        from pathlib import Path

        from .. import config

        p = Path(config.app_data_dir()) / _KEY_FILE
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def save_key(key: str) -> None:
    try:
        from pathlib import Path

        from .. import config

        p = Path(config.app_data_dir()) / _KEY_FILE
        p.write_text((key or "").strip(), encoding="utf-8")
    except Exception:
        pass


def has_key() -> bool:
    return bool(_load_key())


def search_url(query: str, lang: str = "") -> str:
    code = lang or "all"
    q = (query or "").strip().replace(" ", "+")
    return f"{HOME}/en/search/sublanguageid-{code}/query-{q}"


# --------------------------------------------------------------- الواجهة القديمة
def _norm_imdb(imdb_id: str) -> str:
    """يحوّل ``tt0133093`` أو ``133093`` إلى الصيغة السبعة المرقّمة."""
    digits = "".join(ch for ch in (imdb_id or "") if ch.isdigit())
    if not digits:
        return ""
    return digits.zfill(7)


def _legacy_url(query: str = "", lang: str = "", season: str = "",
                episode: str = "", imdb_id: str = "") -> str:
    """
    يبني مسار الطلب للواجهة القديمة: ``/search/<مفتاح-قيمة>/...``.

    ملاحظتان مهمتان:
    - المعاملات تُرتَّب أبجدياً قبل الإرسال، لأن الخادم يعيد توجيه أي طلب
      بترتيب مختلف (302)؛ والترتيب يمنع ذلك ويوسّع رأسياً.
    - النص يُرمَّز بـ percent-encoding حتى تعمل العناوين العربية.
    """
    params: list[str] = []
    q = (query or "").strip()
    imdb = _norm_imdb(imdb_id)
    if imdb:
        params.append(f"imdbid-{imdb}")
    elif q:
        params.append("query-" + urllib.parse.quote(q, safe=""))
    if season and str(season).strip() not in ("0", ""):
        params.append(f"season-{int(str(season).strip())}")
    if episode and str(episode).strip() not in ("0", ""):
        params.append(f"episode-{int(str(episode).strip())}")
    code = (lang or "").strip()
    if code and code != "all":
        params.append(f"sublanguageid-{code}")
    if not params:
        return ""
    params.sort()
    return f"{LEGACY}/search/" + "/".join(params)


def _as_int(value, default: int = 0) -> int:
    try:
        return int(float(str(value).strip() or default))
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(str(value).strip() or default)
    except (TypeError, ValueError):
        return default


def _map_legacy_item(it: dict) -> Optional[SubtitleResult]:
    """يحوّل عنصراً من الواجهة القديمة إلى النموذج الموحّد."""
    if not isinstance(it, dict):
        return None
    link = str(it.get("SubDownloadLink") or "").strip()
    if not link:
        return None
    season = str(it.get("SeriesSeason") or "").strip()
    episode = str(it.get("SeriesEpisode") or "").strip()
    page = str(it.get("SubtitlesLink") or "").strip()
    if not page:
        sub_id = str(it.get("IDSubtitle") or "").strip()
        page = f"{HOME}/en/subtitles/{sub_id}" if sub_id else HOME
    return SubtitleResult(
        site=SITE,
        site_name=SITE_NAME,
        title=str(it.get("MovieName") or ""),
        release=str(it.get("MovieReleaseName") or it.get("SubFileName") or ""),
        year=str(it.get("MovieYear") or ""),
        language=str(it.get("LanguageName") or ""),
        language_code=_norm_code(str(it.get("SubLanguageID") or "")),
        season="" if season in ("0", "") else season,
        episode="" if episode in ("0", "") else episode,
        downloads=_as_int(it.get("SubDownloadsCnt")),
        rating=_as_float(it.get("SubRating")),
        kind="download",
        url=page,
        download_url=link,
        source_id=str(it.get("IDSubtitleFile") or ""),
        note=str(it.get("SubFileName") or ""),
    )


def _search_legacy(query: str, lang: str, season: str, episode: str,
                   imdb_id: str, timeout: int) -> SearchOutcome:
    """البحث عبر الواجهة القديمة: بلا مفتاح، بلا تسجيل."""
    out = SearchOutcome(site=SITE, site_name=SITE_NAME)
    url = _legacy_url(query, lang, season, episode, imdb_id)
    if not url:
        out.error = "empty_query"
        return out

    s = make_session()
    s.headers["Accept"] = "application/json"
    try:
        r = get(s, url, timeout=timeout, headers={"Accept": "application/json"})
    except Exception as exc:
        out.error = f"search_failed: {exc}"
        out.needs_manual = True
        out.manual_url = search_url(query, lang)
        return out

    if r.status_code != 200:
        out.error = f"http_{r.status_code}"
        out.needs_manual = True
        out.manual_url = search_url(query, lang)
        return out

    try:
        items = r.json()
    except Exception:
        out.error = "bad_json"
        out.needs_manual = True
        out.manual_url = search_url(query, lang)
        return out

    if not isinstance(items, list):
        out.error = "bad_payload"
        out.needs_manual = True
        out.manual_url = search_url(query, lang)
        return out

    for it in items:
        mapped = _map_legacy_item(it)
        if mapped is not None:
            out.results.append(mapped)
    return out


# --------------------------------------------------------------- الواجهة الحديثة
def _search_api(query: str, lang: str, season: str, episode: str,
                imdb_id: str, timeout: int) -> SearchOutcome:
    """البحث عبر API الحديث (يتطلب مفتاحاً). مسار احتياطي."""
    out = SearchOutcome(site=SITE, site_name=SITE_NAME)
    key = _load_key()
    if not key:
        out.error = "api_key_required"
        out.needs_manual = True
        out.manual_url = search_url(query, lang)
        return out

    params: dict[str, str] = {
        "query": query,
        "ai": "1",          # بدون تصفية بالحصانة
    }
    if lang:
        params["language_codes"] = lang
    if imdb_id:
        digits = "".join(ch for ch in imdb_id if ch.isdigit())
        if digits:
            params["imdb_id"] = digits
    if season:
        params["season_number"] = str(season)
    if episode:
        params["episode_number"] = str(episode)

    s = make_session()
    s.headers["Api-Key"] = key
    s.headers["Accept"] = "application/json"
    try:
        r = get(s, f"{API}/subtitles", params=params, timeout=timeout)
    except Exception as exc:
        out.error = f"search_failed: {exc}"
        out.needs_manual = True
        out.manual_url = search_url(query, lang)
        return out

    if r.status_code in (401, 403):
        out.error = "api_key_invalid"
    elif r.status_code != 200:
        out.error = f"http_{r.status_code}"
    else:
        try:
            payload = r.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            out.error = "bad_json"
        else:
            for it in payload.get("data") or []:
                attrs = it.get("attributes") or {}
                files = attrs.get("files") or []
                if not files:
                    continue
                f = files[0]
                out.results.append(
                    SubtitleResult(
                        site=SITE,
                        site_name=SITE_NAME,
                        title=str(attrs.get("title") or ""),
                        release=str(attrs.get("release") or ""),
                        year=str(attrs.get("year") or ""),
                        language=str(attrs.get("language") or ""),
                        language_code=_norm_code(str(attrs.get("language_code")
                                                      or attrs.get("language") or "")),
                        season=str(attrs.get("season_number") or ""),
                        episode=str(attrs.get("episode_number") or ""),
                        downloads=_as_int(attrs.get("download_count")),
                        rating=_as_float(attrs.get("rating")),
                        kind="download",
                        url=f"{HOME}/en/subtitles/{it.get('id')}",
                        download_url=str(f.get("file_id") or ""),
                        source_id=str(it.get("id") or ""),
                    )
                )
    if out.error or not out.results:
        out.needs_manual = True
        out.manual_url = search_url(query, lang)
    return out


# ------------------------------------------------------------------ الواجهة العامة
def search(
    query: str,
    lang: str = "",
    season: str = "",
    episode: str = "",
    imdb_id: str = "",
    timeout: int = 20,
) -> SearchOutcome:
    """
    يبحث في OpenSubtitles.

    الافتراضي: الواجهة القديمة (بلا مفتاح). عند فشلها فقط نجرّب واجهة API
    الحديثة إن وُجد مفتاح، وإلا نترك الرابط اليدوي للمستخدم.
    """
    out = SearchOutcome(site=SITE, site_name=SITE_NAME)
    query = (query or "").strip()
    if not query and not imdb_id:
        out.error = "empty_query"
        return out

    legacy = _search_legacy(query, lang, season, episode, imdb_id, timeout)
    if not legacy.error:
        # نتائج صحيحة (حتى لو كانت فارغة: لم يجد البرنامج ترجمة)
        return legacy

    # فشل المسار الأول: نجرّب واجهة API إن توفّر مفتاح
    if _load_key():
        api = _search_api(query, lang, season, episode, imdb_id, timeout)
        if not api.error and api.results:
            return api
        legacy.error = api.error or legacy.error

    if not legacy.manual_url:
        legacy.manual_url = search_url(query, lang)
    legacy.needs_manual = True
    return legacy


def _norm_code(code: str) -> str:
    c = (code or "").lower()
    mapping = {"en": "eng", "ar": "ara", "fr": "fre", "de": "ger", "es": "spa",
               "it": "ita", "ru": "rus", "pt": "por", "tr": "tur", "pl": "pol",
               "nl": "nld", "fa": "per", "hi": "hin", "ja": "jpn", "ko": "kor",
               "zh": "chi", "he": "heb", "sv": "swe", "no": "nor", "da": "dan",
               "fi": "fin", "el": "gre", "cs": "cze", "hu": "hun", "ro": "rum",
               "uk": "ukr", "vi": "vie", "th": "tha", "id": "ind", "ms": "mal"}
    return mapping.get(c, c)


def download_url(file_id: str) -> str:
    """رابط طلب التحميل من واجهة API الحديثة (يتطلب مفتاحاً)."""
    return f"{API}/subtitle/download"


def resolve(result: SubtitleResult, timeout: int = 20) -> Optional[str]:
    """
    يعيد رابط التحميل المباشر.

    - الواجهة القديمة: رابط ``.gz`` جاهز (نفكّ ضغطه في مدير التحميل).
    - الواجهة الحديثة: رقم ملف يُستبدل برابط مؤقت عبر POST (شغّال في
      ``manager.download`` عند توفّر المفتاح).
    """
    u = (result.download_url or "").strip()
    if u.startswith("http"):
        return u
    if u.isdigit():
        return u
    return None
