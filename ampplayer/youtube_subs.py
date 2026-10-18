"""
جلب ترجمة يوتيوب عبر yt-dlp (اختياري).

يُستخدم عندما يكون الفيديو من يوتيوب وترجمته متاحة على الموقع ولم تُضمَّن
في الملف المحلي. إن لم يكن yt-dlp مثبتاً نُبلّغ برسالة واضحة ولا نُعطّل
بقية الميزات.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple

_TIMEOUT = 300


def ytdlp_available() -> Tuple[bool, str, str]:
    """يعيد (متاح، المحرّك، التفصيل): yt-dlp-module | yt-dlp-exe | none."""
    try:
        import yt_dlp  # type: ignore  # noqa: F401

        return True, "yt-dlp-module", getattr(yt_dlp, "version", "")
    except Exception:
        pass
    exe = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if not exe:
        cand = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "yt-dlp" / "yt-dlp.exe"
        if cand.exists():
            exe = str(cand)
    if exe:
        return True, "yt-dlp-exe", exe
    return False, "none", "yt_dlp_not_found"


def _collect(out_dir: Path) -> List[str]:
    subs: List[str] = []
    for p in sorted(out_dir.glob("*")):
        if p.suffix.lower() in (".srt", ".vtt", ".ass", ".ssa"):
            subs.append(str(p))
    return subs


def fetch_subtitles(url: str, langs: List[str], out_dir: Path,
                    timeout: int = _TIMEOUT) -> Tuple[bool, List[str], str, str]:
    """
    ينزّل ترجمات الفيديو (اليدوية وتلقائية التوليد عند توفرها).

    يعيد (نجاح، قائمة الملفات، مفتاح رسالة، تفصيل).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    langs = [l for l in (langs or []) if l] or ["ar", "en"]
    ok, backend, detail = ytdlp_available()
    if not ok:
        return False, [], "ytdlp.missing", detail

    tmpl = str(out_dir / "%(id)s.%(ext)s")
    if backend == "yt-dlp-module":
        try:
            import yt_dlp  # type: ignore

            opts = {
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": list(langs),
                "subtitlesformat": "srt/vtt/best",
                "outtmpl": tmpl,
                "quiet": True,
                "noprogress": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as exc:
            return False, [], "ytdlp.error", f"{type(exc).__name__}: {exc}"
    else:
        cmd = [detail, "--skip-download", "--write-subs", "--write-auto-subs",
               "--sub-langs", ",".join(langs), "--sub-format", "srt/vtt/best",
               "-o", tmpl, url]
        try:
            run = subprocess.run(
                cmd, capture_output=True, timeout=timeout, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            return False, [], "ytdlp.error", f"{type(exc).__name__}: {exc}"
        if run.returncode != 0 and not _collect(out_dir):
            return False, [], "ytdlp.error", (run.stderr or "")[-400:]

    files = _collect(out_dir)
    if not files:
        return False, [], "ytdlp.none", ",".join(langs)
    return True, files, "ytdlp.ok", ""


def normalize_langs(value: str) -> List[str]:
    """يحوّل "ara+eng" أو "ar,en" إلى قائمة أكواد يوتيوب (ar, en)."""
    raw = str(value or "").replace("+", ",").replace(";", ",")
    out: List[str] = []
    for part in raw.split(","):
        p = part.strip().lower()
        if not p:
            continue
        out.append({"ara": "ar", "eng": "en"}.get(p, p))
    return out or ["ar", "en"]
