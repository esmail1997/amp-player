"""دمج ملف الترجمة داخل الفيديو باستخدام FFmpeg (نسخ بدون إعادة ترميز)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .media_probe import ffmpeg_path, _no_window_kwargs

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".wmv", ".flv", ".ts", ".m2ts", ".mpg", ".mpeg", ".3gp", ".ogv", ".vob"}

# ترميزات الترجمة حسب حاوية الإخراج
CODEC_BY_EXT = {
    ".mkv": ["subrip", "srt"],   # Matroska يدعم كل الصيغ
    ".mp4": ["mov_text"],        # MP4 يتطلب mov_text
    ".m4v": ["mov_text"],
    ".mov": ["mov_text"],
    ".webm": ["webvtt"],
    ".avi": ["subrip"],
    ".ts": ["subrip"],
    ".m2ts": ["subrip"],
}

LANG_TAGS = [
    "ara", "eng", "fre", "ger", "spa", "ita", "rus", "por", "nld", "tur",
    "jpn", "kor", "chi", "zho", "pol", "swe", "nor", "dan", "fin", "heb",
    "per", "ind", "tha", "cze", "ces", "gre", "ell", "hun", "rum", "ron",
    "ukr", "vie", "mal", "may", "tai", "baq", "eus", "hrv", "srp", "bul",
]


def default_output_path(video_path: str | Path, sub_path: str | Path) -> Path:
    """اقتراح اسم ملف الإخراج (لا نكتب فوق الأصل)."""
    v = Path(video_path)
    suffix = v.suffix.lower()
    return v.with_name(f"{v.stem} [Amp-sub]{suffix or '.mkv'}")


def detect_lang(sub_path: str | Path) -> str:
    """يحاول استنتاج رمز اللغة من اسم الملف."""
    name = Path(sub_path).stem.lower()
    for tag in LANG_TAGS:
        if re.search(rf"(^|[^a-z]){tag}([^a-z]|$)", name):
            return tag
    # رموز ISO أخرى شائعة
    for tag in ("arabic", "english", "french", "spanish", "german"):
        if tag in name:
            return {"arabic": "ara", "english": "eng", "french": "fre",
                    "spanish": "spa", "german": "ger"}.get(tag, "und")
    return "und"


@dataclass
class MergeResult:
    ok: bool = False
    output: str = ""
    error: str = ""
    log: str = ""


def build_command(
    video: str | Path,
    subtitle: str | Path,
    output: str | Path,
    *,
    language: str = "",
    title: str = "",
    default_track: bool = True,
    copy_audio: bool = True,
    keep_original_audio_tracks: bool = True,
) -> List[str]:
    """
    يبني أمر ffmpeg للدمج.
    ننسخ الفيديو والصوت كما هما (copy) لتسريع العملية دون فقدان الجودة.
    """
    exe = ffmpeg_path()
    out_ext = Path(output).suffix.lower() or ".mkv"
    if out_ext == ".mp4":
        sub_codec = "mov_text"
    elif out_ext == ".webm":
        sub_codec = "webvtt"
    else:
        sub_codec = "srt"
    lang = language or detect_lang(subtitle) or "und"

    cmd: List[str] = [
        exe or "ffmpeg", "-y",
        "-loglevel", "error",
        "-i", str(video),
        "-i", str(subtitle),
        # نسخ كل مسارات الفيديو والصوت الأصلية
        "-map", "0",
        # استبعاد ترجمات الأصل إن موجودة (اختياري - ندمج الجديدة فقط)
        "-map", "1:0",
    ]
    # ترجمة إلى SRT داخلياً لتوحيد الصيغة قبل mux
    if sub_codec == "srt":
        cmd += ["-c:s", "srt"]
    else:
        cmd += ["-c:s", sub_codec]

    # بيانات المسار
    cmd += [f"-metadata:s:s:{0}", f"language={lang}"]
    if title:
        cmd += ["-metadata:s:s:0", f"title={title}"]

    # تحديد المسار الافتراضي
    cmd += ["-disposition:s:0", "default" if default_track else "0"]

    # ترميز الفيديو: نسخ
    cmd += ["-c:v", "copy"]
    # ترميز الصوت: نسخ أو تحويل لـ AAC لِـ mp4/webm
    if copy_audio:
        if out_ext in (".mp4", ".m4v", ".mov", ".webm"):
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "192k"]

    # حاويات mp4/webm لا تقبل كل ترميزات الفيديو.Copy
    if out_ext in (".mp4", ".m4v", ".mov", ".webm"):
        # mp4 لا يقبل h265/vp9 غالباً - ننسخ المسار كما هو
        pass

    cmd += ["-map_metadata", "0", str(output)]
    return cmd


def merge_subtitle(
    video: str | Path,
    subtitle: str | Path,
    output: Optional[str | Path] = None,
    *,
    language: str = "",
    title: str = "",
    default_track: bool = True,
    copy_audio: bool = True,
    progress_cb=None,
) -> MergeResult:
    """
    يدمج ملف الترجمة داخل الفيديو (mux بدون إعادة ترميز).
    """
    res = MergeResult()
    exe = ffmpeg_path()
    if not exe:
        res.error = "ffmpeg_not_found"
        return res

    v = Path(video)
    s = Path(subtitle)
    if not v.exists():
        res.error = f"video_missing: {v}"
        return res
    if not s.exists():
        res.error = f"subtitle_missing: {s}"
        return res

    if output is None:
        output = default_output_path(v, s)
    o = Path(output)
    if o.exists():
        try:
            o.unlink()
        except OSError:
            pass
    o.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_command(
        v, s, o,
        language=language,
        title=title,
        default_track=default_track,
        copy_audio=copy_audio,
    )

    if progress_cb:
        try:
            progress_cb(0, "starting")
        except Exception:
            pass

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_no_window_kwargs(),
        )
    except OSError as exc:
        res.error = f"launch_failed: {exc}"
        return res

    # ffmpeg يطبع شريط تقدم على stderr؛ نقرأه ونحدّث
    tail: List[str] = []
    try:
        # نقيس حجم الملف للتحقق من التقدّم
        try:
            total = o.stat().st_size if o.exists() else 0
        except OSError:
            total = 0

        assert proc.stderr is not None
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if line:
                tail.append(line)
                del tail[:-40]
            if progress_cb and total:
                try:
                    cur = o.stat().st_size
                    pct = int(min(99, cur / total * 100))
                    progress_cb(pct, "copying")
                except OSError:
                    pass
        proc.wait()
    except Exception as exc:
        proc.kill()
        res.error = f"ffmpeg_error: {exc}"
        res.log = "\n".join(tail)
        return res

    res.log = "\n".join(tail)
    if proc.returncode != 0:
        res.error = "ffmpeg_failed"
        return res
    if not o.exists() or o.stat().st_size == 0:
        res.error = "no_output"
        return res

    res.ok = True
    res.output = str(o)
    if progress_cb:
        try:
            progress_cb(100, "done")
        except Exception:
            pass
    return res


def verify_merged(output: str | Path) -> bool:
    """يتحقق من وجود ترجمة داخل الملف الناتج عبر ffprobe."""
    from .media_probe import probe

    info = probe(output)
    return info.has_embedded_subtitles