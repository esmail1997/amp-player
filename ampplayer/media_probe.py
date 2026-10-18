"""فحص معلومات الوسائط ومساراتها باستخدام ffprobe وffmpeg."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# التشغيل المباشر للملف وحده: نضيف جذر المشروع للمسار ونستورد بالاسم
# الكامل؛ والاستيراد النسبي يعمل فقط عند الاستيراد كحزمة (وهو الحال
# داخل البرنامج المجمَّع والمشغّل عبر main.py).
_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):
    sys.path.insert(0, str(_ROOT))
    from ampplayer import config  # noqa: E402
else:
    from . import config


# ---------------------------------------------------------------- أدوات
def _no_window_kwargs() -> dict:
    """منع ظهور نافذة سطر الأوامر عند تشغيل ffmpeg."""
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
    si.wShowWindow = 0  # SW_HIDE
    return {"startupinfo": si, "creationflags": 0x08000000}  # CREATE_NO_WINDOW


def ffmpeg_path() -> Optional[str]:
    """يبحث عن ffmpeg.exe في المسار أو في مجلد الأدوات."""
    env = os.environ.get("AMP_FFMPEG_PATH")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    root = Path(__file__).resolve().parent.parent
    for cand in (
        root / "tools" / "ffmpeg.exe",
        root / "ffmpeg.exe",
        root / "bin" / "ffmpeg.exe",
        Path(config.app_data_dir()) / "tools" / "ffmpeg.exe",
    ):
        if cand.exists():
            return str(cand)
    return None


def ffprobe_path() -> Optional[str]:
    """يبحث عن ffprobe.exe."""
    env = os.environ.get("AMP_FFMPEG_PATH")
    if env:
        base = Path(env).parent
        cand = base / "ffprobe.exe"
        if cand.exists():
            return str(cand)
    found = shutil.which("ffprobe")
    if found:
        return found
    root = Path(__file__).resolve().parent.parent
    for cand in (
        root / "tools" / "ffprobe.exe",
        root / "ffprobe.exe",
        Path(config.app_data_dir()) / "tools" / "ffprobe.exe",
    ):
        if cand.exists():
            return str(cand)
    return None


def has_ffmpeg() -> bool:
    return ffmpeg_path() is not None


# ---------------------------------------------------------------- نماذج
@dataclass
class MediaTrack:
    """مسار واحد (صوت أو ترجمة) داخل ملف الوسائط."""
    index: int
    kind: str = "subtitle"      # subtitle | audio | video
    codec: str = ""
    language: str = ""
    title: str = ""
    is_default: bool = False
    is_forced: bool = False

    @property
    def display_name(self) -> str:
        parts = []
        if self.language:
            parts.append(self.language)
        if self.title:
            parts.append(self.title)
        if not parts:
            parts.append(f"track {self.index}")
        if self.is_default:
            parts.append("(default)")
        if self.is_forced:
            parts.append("(forced)")
        return " - ".join(str(p) for p in parts)


@dataclass
class MediaInfo:
    """معلومات ملف الوسائط."""
    path: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    vcodec: str = ""
    acodec: str = ""
    fps: float = 0.0
    bitrate: int = 0
    subtitles: List[MediaTrack] = field(default_factory=list)
    audios: List[MediaTrack] = field(default_factory=list)
    has_embedded_subtitles: bool = False
    error: str = ""

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}" if self.width else ""

    @property
    def display_title(self) -> str:
        return Path(self.path).stem if self.path else ""

    def quality_label(self) -> str:
        """وصف مختصر للجودة (للمكفوفين)."""
        bits = []
        if self.height:
            if self.height >= 2160:
                bits.append("4K")
            elif self.height >= 1440:
                bits.append("1440p")
            elif self.height >= 1080:
                bits.append("Full HD 1080p")
            elif self.height >= 720:
                bits.append("HD 720p")
            elif self.height >= 576:
                bits.append("SD")
            else:
                bits.append(f"{self.height}p")
        if self.vcodec:
            bits.append(self.vcodec.upper())
        if self.acodec:
            bits.append(self.acodec.upper())
        if self.fps and self.fps > 1:
            bits.append(f"{self.fps:.0f}fps")
        return " | ".join(bits)


# ---------------------------------------------------------------- الاستخراج
def probe(path: str | Path) -> MediaInfo:
    """
    يستخرج معلومات الوسائط باستخدام ffprobe.
    يعيد MediaInfo فارغاً إن لم يكن ffprobe متاحاً.
    """
    info = MediaInfo(path=str(path))
    probe_exe = ffprobe_path()
    if not probe_exe:
        info.error = "ffprobe not available"
        return info
    cmd = [
        probe_exe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, timeout=60, check=False, **_no_window_kwargs()
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        info.error = str(exc)
        return info
    if out.returncode != 0:
        info.error = (out.stderr or b"").decode("utf-8", "replace")[:400]
        return info
    try:
        data = json.loads(out.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        info.error = f"JSON parse error: {exc}"
        return info

    fmt = data.get("format") or {}
    try:
        info.duration = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        info.duration = 0.0
    try:
        info.bitrate = int(fmt.get("bit_rate") or 0)
    except (TypeError, ValueError):
        info.bitrate = 0

    for stream in data.get("streams") or []:
        ctype = stream.get("codec_type")
        tags = stream.get("tags") or {}
        try:
            idx = int(stream.get("index", 0))
        except (TypeError, ValueError):
            idx = 0
        title = tags.get("title") or tags.get("TITLE") or ""
        lang = (
            tags.get("language") or stream.get("language") or ""
        )
        disp = stream.get("disposition") or {}
        if ctype == "subtitle":
            tr = MediaTrack(
                index=idx,
                kind="subtitle",
                codec=stream.get("codec_name") or "",
                language=lang,
                title=title,
                is_default=bool(disp.get("default")),
                is_forced=bool(disp.get("forced")),
            )
            info.subtitles.append(tr)
        elif ctype == "audio":
            tr = MediaTrack(
                index=idx,
                kind="audio",
                codec=stream.get("codec_name") or "",
                language=lang,
                title=title,
                is_default=bool(disp.get("default")),
            )
            info.audios.append(tr)
            if not info.acodec:
                info.acodec = tr.codec
        elif ctype == "video":
            if not info.vcodec:
                info.vcodec = stream.get("codec_name") or ""
                try:
                    info.width = int(stream.get("width") or 0)
                    info.height = int(stream.get("height") or 0)
                except (TypeError, ValueError):
                    pass
                fps = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
                try:
                    num, _, den = fps.partition("/")
                    den_f = float(den or 0)
                    info.fps = float(num) / den_f if den_f else 0.0
                except (TypeError, ValueError):
                    info.fps = 0.0

    info.has_embedded_subtitles = len(info.subtitles) > 0
    return info

