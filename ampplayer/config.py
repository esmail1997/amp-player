"""إعدادات البرنامج المحفوظة في QSettings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import QSettings, QStandardPaths

from .i18n import AR, EN

APP_ORG = "AmpPlayer"
APP_DOMAIN = "amp.player"
ENV_CONFIG_FILE = "AMP_CONFIG_FILE"


def app_data_dir() -> Path:
    """مجلد بيانات التطبيق القابل للكتابة."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not base:
        base = str(Path.home() / ".ampplayer")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    """مجلد التخزين المؤقت للترجمات والتحويلات."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    if not base:
        base = str(app_data_dir() / "cache")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def subtitles_cache_dir() -> Path:
    p = cache_dir() / "subtitles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = app_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULTS: Dict[str, Any] = {
    # عام
    "lang": AR,
    "rtl": True,
    "autoplay_next": True,
    "remember_position": True,
    # 0 = يترك FFmpeg يقرّر بنفسه
    "decode_threads": 0,
    # محرك التشغيل: mpv (الافتراضي، مع التراجع التلقائي) أو pyav
    "player_engine": "mpv",
    "loop_playlist": False,
    # الترجمة
    "sub_auto_load_sidecar": True,
    "sub_auto_search_if_missing": True,
    "sub_default_lang": "ara",
    "sub_font_size": 34,
    "sub_font": "",
    "sub_color": "#FFFFFF",
    "sub_outline_color": "#000000",
    "sub_outline_thickness": 2,
    "sub_background_opacity": 0,
    "sub_position": "bottom",
    "sub_delay_offset": 0.0,
    "sub_show_on_screen": True,
    "sub_pause_on_line": False,
    "sub_panel_visible": True,
    "sub_repeat_last": 2,
    # مصدر الترجمة الخارجية: auto أو manual
    "sub_source_mode": "auto",
    "yt_source_url": "",
    # خفض مؤقت أثناء النطق
    "tts_duck_while_speaking": True,
    # مدة بقاء الصوت منخفضاً بعد انتهاء النطق (مللي ثانية)
    "tts_duck_hold_ms": 600,
    # النطق / الوصولية
    "tts_enabled": False,
    "tts_engine": "auto",
    "tts_voice": "",
    "tts_rate": 175,
    "tts_volume": 100,
    "tts_announce_subtitle": True,
    "tts_announce_state": True,
    "tts_announce_volume": True,
    "tts_announce_markers": True,
    "show_subtitle_log": True,
    # المسارات
    # ffmpeg اختياري: محرّك التشغيل لا يحتاجه، هو فقط لدمج الترجمة في الفيديو
    "ffmpeg_path": "",
    "ffmpeg_lib_path": "",
    "download_dir": "",
    # آخر مجلد فتحه المستخدم من نوافذ "فتح ملف" (تُترك فارغة أول مرة)
    "last_open_dir": "",
    # فهرس جهاز الإخراج الصوتي في sounddevice (1- = الافتراضي للنظام)
    "audio_device": -1,
    "keep_original_on_merge": True,
    # مواقع الترجمة
    "sites_opensubtitles": True,
    "sites_subdl": True,
    "sites_yifysubtitles": True,
    "sites_tvsubtitles": True,
    "sites_enabled_list": ["opensubtitles", "subdl", "yifysubtitles", "tvsubtitles"],
    "search_season": "",
    "search_episode": "",
    "search_release": "",
    "search_imdb": "",
    "search_language": "ara",
    # الحالة المحفوظة
    "recent_files": [],
    "window_geometry": "",
    "window_state": "",
    "first_run_done": False,
    "onboarding_seen": False,
}


class Config:
    """
    غلاف حول QSettings مع قيم افتراضية آمنة.

    يمكن توجيه التخزين إلى ملف بديل عبر AMP_CONFIG_FILE. نستعمله في
    الاختبارات تحديداً: من دونه كانت الاختبارات تكتب في سجل المستخدم
    الحقيقي، فتنقل إزاحة الترجمة وسرعة الصوت بين الجولات، ويفشل
    اختبار لأنها لم تبدأ من صفر.
    """

    def __init__(self, path: str | None = None) -> None:
        target = path or os.environ.get(ENV_CONFIG_FILE, "")
        if target:
            p = Path(target)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._s = QSettings(str(p), QSettings.Format.IniFormat)
        else:
            self._s = QSettings(APP_ORG, APP_DOMAIN)

    # ---------- واجهة شائعة ----------
    def get(self, key: str, default: Any = None) -> Any:
        if key not in DEFAULTS:
            return default
        val = self._s.value(key, DEFAULTS[key])
        return self._coerce(key, val)

    def set(self, key: str, value: Any) -> None:
        self._s.setValue(key, value)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._s.clear()
        else:
            self._s.remove(key)

    def reset_all(self) -> None:
        self._s.clear()
        self.sync()

    def sync(self) -> None:
        self._s.sync()

    def all_keys(self) -> List[str]:
        return list(DEFAULTS.keys())

    def as_dict(self) -> Dict[str, Any]:
        return {k: self.get(k) for k in DEFAULTS}

    # ---------- أدوات ----------
    @staticmethod
    def _coerce(key: str, value: Any) -> Any:
        default = DEFAULTS.get(key)
        try:
            if isinstance(default, bool):
                if isinstance(value, str):
                    return value.strip().lower() in ("1", "true", "yes", "on")
                return bool(value)
            if isinstance(default, int) and not isinstance(default, bool):
                return int(value)
            if isinstance(default, float):
                return float(value)
            if isinstance(default, list):
                if isinstance(value, str):
                    s = value.strip()
                    if not s:
                        return []
                    try:
                        parsed = json.loads(s)
                        return parsed if isinstance(parsed, list) else [str(parsed)]
                    except json.JSONDecodeError:
                        return [x for x in s.split("|") if x]
                return list(value)
            if isinstance(default, str):
                return "" if value is None else str(value)
        except (TypeError, ValueError):
            return default
        return value

    # ---------- اختصارات مخصصة ----------
    @property
    def lang(self) -> str:
        v = self.get("lang")
        return v if v in (AR, EN) else AR

    def toggle_lang(self) -> str:
        new = EN if self.lang == AR else AR
        self.set("lang", new)
        self.sync()
        return new

    def recent_files(self) -> List[str]:
        return [str(x) for x in self.get("recent_files") or []]

    def add_recent(self, path: str, limit: int = 15) -> None:
        try:
            files = self.recent_files()
        except Exception:
            files = []
        if path in files:
            files.remove(path)
        files.insert(0, path)
        del files[limit:]
        self.set("recent_files", files)
        self.sync()

    def clear_recent(self) -> None:
        self.set("recent_files", [])
        self.sync()