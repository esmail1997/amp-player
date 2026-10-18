"""مدير موحّد للبحث في مواقع الترجمة وتحميل الملفات."""

from __future__ import annotations

import concurrent.futures
import gzip
import io
import re
import zipfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .. import config
from . import (
    opensubtitles_provider,
    subdl_provider,
    tvsubtitles_provider,
    yify_provider,
)
from .http_client import get, make_session
from .models import SearchOutcome, SubtitleResult

PROVIDERS = {
    opensubtitles_provider.SITE: opensubtitles_provider,
    subdl_provider.SITE: subdl_provider,
    yify_provider.SITE: yify_provider,
    tvsubtitles_provider.SITE: tvsubtitles_provider,
}

SITE_ORDER = [
    subdl_provider.SITE,
    yify_provider.SITE,
    opensubtitles_provider.SITE,
    tvsubtitles_provider.SITE,
]


def enabled_sites(cfg: Optional[config.Config] = None) -> List[str]:
    """قائمة المواقع المفعّلة حسب الإعدادات."""
    cfg = cfg or config.Config()
    allowed = set(cfg.get("sites_enabled_list") or SITE_ORDER)
    return [s for s in SITE_ORDER if s in allowed]


def site_display_name(site: str) -> str:
    return PROVIDERS[site].SITE_NAME if site in PROVIDERS else site


def site_home(site: str) -> str:
    return PROVIDERS[site].HOME if site in PROVIDERS else ""


def manual_search_url(site: str, query: str, lang: str = "") -> str:
    mod = PROVIDERS.get(site)
    if mod is None:
        return ""
    try:
        return mod.search_url(query, lang)
    except Exception:
        return ""


def search_all(
    query: str,
    lang: str = "",
    season: str = "",
    episode: str = "",
    imdb_id: str = "",
    sites: Optional[List[str]] = None,
    timeout: int = 20,
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> dict[str, SearchOutcome]:
    """
    يبحث في كل المواقع بالتوازي.
    يعيد قاموس {site: SearchOutcome}.
    """
    use = sites if sites is not None else enabled_sites()
    outcomes: dict[str, SearchOutcome] = {}
    if not use:
        return outcomes

    total = len(use)
    done = 0

    def run_one(site: str) -> tuple[str, SearchOutcome]:
        mod = PROVIDERS.get(site)
        if mod is None:
            return site, SearchOutcome(site=site, error="unknown_site")
        kwargs: dict = {"query": query, "lang": lang, "season": season,
                        "episode": episode, "timeout": timeout}
        if site == opensubtitles_provider.SITE:
            kwargs["imdb_id"] = imdb_id
        try:
            res = mod.search(**kwargs)
        except Exception as exc:
            res = SearchOutcome(site=site, site_name=site_display_name(site),
                                error=f"exception: {exc}")
        return site, res

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, total)) as ex:
        futs = [ex.submit(run_one, s) for s in use]
        for fut in concurrent.futures.as_completed(futs):
            try:
                site, res = fut.result()
            except Exception as exc:
                site, res = "?", SearchOutcome(error=str(exc))
            outcomes[site] = res
            done += 1
            if progress_cb:
                try:
                    progress_cb(site, done, total)
                except Exception:
                    pass
    return outcomes


def flatten(outcomes: dict[str, SearchOutcome],
            sort: str = "downloads") -> List[SubtitleResult]:
    """يدمج كل النتائج في قائمة واحدة مرتبة."""
    allr: List[SubtitleResult] = []
    for site in SITE_ORDER:
        o = outcomes.get(site)
        if not o:
            continue
        allr.extend(o.results)
    if sort == "downloads":
        allr.sort(key=lambda r: r.downloads, reverse=True)
    elif sort == "rating":
        allr.sort(key=lambda r: r.rating, reverse=True)
    return allr


# ------------------------------------------------------------------ التحميل
_SUB_EXT = (".srt", ".ass", ".ssa", ".vtt", ".sub", ".smi", ".txt", ".sami")


def _extract_subtitle_from_zip(data: bytes, prefer_name: str = "") -> Optional[Tuple[str, bytes]]:
    """يستخرج أول ملف ترجمة من ملف ZIP."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if prefer_name:
                for n in names:
                    if prefer_name.lower() in n.lower():
                        return Path(n).name, zf.read(n)
            for n in names:
                if n.lower().endswith(_SUB_EXT):
                    return Path(n).name, zf.read(n)
            if names:
                return Path(names[0]).name, zf.read(names[0])
    except (zipfile.BadZipFile, OSError):
        return None
    return None


def resolve_download_url(result: SubtitleResult, timeout: int = 20) -> Optional[str]:
    """يحل رابط التحميل المباشر إذا كانت النتيجة صفحة ويب."""
    mod = PROVIDERS.get(result.site)
    if mod is None:
        return None
    try:
        fn = getattr(mod, "resolve", None)
        if fn is None:
            return None
        try:
            return fn(result, timeout=timeout)
        except TypeError:
            return fn(result)
    except Exception:
        return None


def download(
    result: SubtitleResult,
    dest_dir: Optional[Path] = None,
    timeout: int = 40,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Optional[Path]:
    """
    يحمّل ملف الترجمة ويعيد مساره.
    يدعم: روابط مباشرة (.srt/.zip) و صفحات تحتاج استخراج رابط.
    """
    dest_dir = Path(dest_dir) if dest_dir else config.subtitles_cache_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    url = resolve_download_url(result, timeout=timeout)
    if not url:
        return None

    # OpenSubtitles يتطلب POST مع مفتاح
    if result.site == opensubtitles_provider.SITE and url.isdigit():
        s = make_session()
        key = opensubtitles_provider._load_key()
        s.headers["Api-Key"] = key
        s.headers["Accept"] = "application/json"
        try:
            from .http_client import post

            r = post(s, opensubtitles_provider.download_url(url),
                     json={"file_id": int(url)}, timeout=timeout)
            if r.status_code != 200:
                return None
            link = (r.json() or {}).get("link")
            if not link:
                return None
            url = link
        except Exception:
            return None

    s = make_session()
    s.headers["Referer"] = site_home(result.site) + "/"
    try:
        if progress_cb:
            progress_cb(0, 0)
        r = get(s, url, timeout=timeout, stream=True)
        if r.status_code != 200:
            return None
        data = r.content
    except Exception:
        return None

    if not data:
        return None

    base_name = _safe_name(result)

    # ملف مضغوط gzip: الواجهة القديمة لـ OpenSubtitles ترسل الترجمة مضغوطة
    if url.lower().split("?")[0].endswith(".gz") or data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError):
            return None
        if not data:
            return None

    # ملف ZIP
    if url.lower().split("?")[0].endswith(".zip") or data[:2] == b"PK":
        found = _extract_subtitle_from_zip(data, base_name)
        if found:
            fname, fdata = found
            out = dest_dir / f"{base_name}{Path(fname).suffix.lower() or '.srt'}"
            out.write_bytes(fdata)
            if progress_cb:
                progress_cb(len(fdata), len(fdata))
            return out
        return None

    # ملف مباشر
    ct = ""
    try:
        ct = (r.headers.get("Content-Type") or "").lower()
    except Exception:
        pass
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix not in _SUB_EXT:
        if "html" in ct:
            return None
        # نخمّن الصيغة من المحتوى نفسه (خاصة بعد فكّ gzip)
        head = data[:64].lstrip()[:13].lower()
        if head.startswith(b"[script info]"):
            suffix = ".ass"
        elif head.startswith(b"webvtt"):
            suffix = ".vtt"
        else:
            suffix = ".srt"
    out = dest_dir / f"{base_name}{suffix}"
    out.write_bytes(data)
    if progress_cb:
        progress_cb(len(data), len(data))
    return out


def _safe_name(result: SubtitleResult) -> str:
    """اسم ملف آمن مشتق من النتيجة."""
    raw = (result.title or result.release or result.source_id or "subtitle").strip()
    raw = re.sub(r"[\\/:*?\"<>|]+", "-", raw)
    raw = re.sub(r"\s+", " ", raw)
    raw = raw.strip(" .-_")
    if not raw:
        raw = "subtitle"
    return raw[:80]