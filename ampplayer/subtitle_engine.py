"""محرك مزامنة الترجمة مع التشغيل: يعرض ويقرأ السطر النشط."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Signal

from . import config
from .subtitle_parser import Cue, find_cue, format_timestamp, parse_file_safe, to_srt


class SubtitleEngine(QObject):
    """
    يدير قائمة أسطر الترجمة ويربطها بزمن التشغيل.

    المزايا:
    - البحث الثنائي عن السطر النشط
    - إزاحة توقيت قابلة للضبط (+/- 0.5 ثانية)
    - كشف إعادة العرض (عند التأخير أو القفز للخلف) لإعادة القراءة
    - سجل كامل لعرضه/نسخه
    """

    cue_changed = Signal(object)        # Cue أو None
    log_changed = Signal()
    loaded = Signal(str, int)          # المسار، عدد الأسطر
    unloaded = Signal()
    status = Signal(str)

    def __init__(self, parent: Optional[QObject] = None,
                 cfg: Optional[config.Config] = None) -> None:
        super().__init__(parent)
        # نحقل الإعدادات لأن ضبط الإزاحة يكتبها فوراً، فمن يختبر هذا
        # المحرّك يريد تخزينه المؤقت لا إعدادات المستخدم.
        self.cfg = cfg if cfg is not None else config.Config()
        self.cues: List[Cue] = []
        self.source_path: str = ""
        self.source_name: str = ""
        self.offset_ms: int = 0
        self._current: Optional[Cue] = None
        self._last_spoken_index: int = -1
        self._last_pos_ms: int = 0
        self._log: List[str] = []
        self._log_limit = 5000

    # ------------------------------------------------------------ تحميل
    def load_file(self, path: str | Path, name: str = "") -> tuple[bool, int, str]:
        """يحمّل ملف ترجمة. يعيد (نجاح، عدد الأسطر، خطأ)."""
        p = Path(path)
        if not p.exists():
            self.unload()
            return False, 0, "file_not_found"
        cues = parse_file_safe(p)
        if not cues:
            self.unload()
            return False, 0, "empty_or_unsupported"
        self.cues = cues
        self.source_path = str(p)
        self.source_name = name or p.stem
        self.offset_ms = int(float(self.cfg.get("sub_delay_offset") or 0.0) * 1000)
        self._current = None
        self._last_spoken_index = -1
        self._log = []
        self.loaded.emit(str(p), len(cues))
        self.log_changed.emit()
        self.status.emit(f"loaded:{len(cues)}")
        return True, len(cues), ""

    def load_cues(self, cues: List[Cue], name: str, source_path: str = "") -> bool:
        if not cues:
            return False
        self.cues = list(cues)
        self.source_name = name
        self.source_path = source_path
        self.offset_ms = int(float(self.cfg.get("sub_delay_offset") or 0.0) * 1000)
        self._current = None
        self._last_spoken_index = -1
        self._log = []
        self.loaded.emit(source_path or name, len(cues))
        self.log_changed.emit()
        return True

    def unload(self) -> None:
        had = bool(self.cues)
        self.cues = []
        self.source_path = ""
        self.source_name = ""
        self._current = None
        self._last_spoken_index = -1
        self._log = []
        if had:
            self.unloaded.emit()
            self.log_changed.emit()
            self.cue_changed.emit(None)

    @property
    def has_cues(self) -> bool:
        return bool(self.cues)

    # ------------------------------------------------------------ موضع
    def set_offset_seconds(self, seconds: float) -> None:
        self.offset_ms = int(seconds * 1000)
        self.cfg.set("sub_delay_offset", round(seconds, 3))
        self.cfg.sync()

    def adjust_offset(self, delta_seconds: float) -> float:
        cur = self.offset_ms / 1000.0
        new = max(-120.0, min(120.0, cur + delta_seconds))
        self.set_offset_seconds(new)
        return new

    def get_offset_seconds(self) -> float:
        return self.offset_ms / 1000.0

    def reset_offset(self) -> None:
        self.set_offset_seconds(0.0)

    # ------------------------------------------------------------ التزامن
    def update(self, pos_ms: int) -> Optional[Cue]:
        """
        يُستدعى دورياً بزمن التشغيل ويعيد السطر النشط.
        يرسل cue_changed عند تغيّر السطر.
        """
        if not self.cues:
            return None
        # كشف القفز للخلف أو القفز السريع للمزامنة
        if pos_ms < (self._last_pos_ms - 1500):
            self.reset_announce()
        self._last_pos_ms = pos_ms
        target = pos_ms - self.offset_ms
        cue = find_cue(self.cues, target)
        if cue is None:
            if self._current is not None:
                self._current = None
                self.cue_changed.emit(None)
            return None
        if self._current is None or self._current.index != cue.index:
            self._current = cue
            self.cue_changed.emit(cue)
        elif cue.text != self._current.text:
            self._current = cue
            self.cue_changed.emit(cue)
        return cue

    def should_announce(self, cue: Optional[Cue]) -> bool:
        """
        هل يجب قراءة هذا السطر صوتياً؟
        نقرأ عند تغيّر السطر فقط. وعند القفز للخلف يُعاد ضبط الحالة
        فتُقرأ الأسطر التي يمرّ بها المستخدم مرة أخرى (وهو ما يريده
        الكفيف الذي أعاد الاستماع لجزء).
        """
        if cue is None:
            return False
        return self._last_spoken_index != cue.index

    def mark_announced(self, cue: Optional[Cue]) -> None:
        if cue is not None:
            self._last_spoken_index = cue.index

    def reset_announce(self) -> None:
        """يُستدعى عند القفز للخلف أو إعادة التشغيل حتى تُقرأ الأسطر مجدداً."""
        self._last_spoken_index = -1

    # ------------------------------------------------------------ التنقل
    def current_cue(self) -> Optional[Cue]:
        return self._current

    def next_cue(self) -> Optional[Cue]:
        """السطر التالي (للقفزة اليدوية)."""
        if not self.cues:
            return None
        if self._current is None:
            return self.cues[0]
        for c in self.cues:
            if c.index > self._current.index:
                return c
        return None

    def prev_cue(self) -> Optional[Cue]:
        """السطر السابق."""
        if not self.cues:
            return None
        if self._current is None:
            return self.cues[0]
        for c in reversed(self.cues):
            if c.index < self._current.index:
                return c
        return None

    def cue_at(self, index: int) -> Optional[Cue]:
        for c in self.cues:
            if c.index == index:
                return c
        return None

    def jump_to_next(self) -> Optional[Cue]:
        """ينقل موضع القراءة إلى بداية السطر التالي."""
        c = self.next_cue()
        return c

    def jump_to_prev(self) -> Optional[Cue]:
        c = self.prev_cue()
        return c

    # ------------------------------------------------------------ السجل
    def append_log(self, text: str) -> None:
        self._log.append(text)
        if len(self._log) > self._log_limit:
            del self._log[: len(self._log) - self._log_limit]
        self.log_changed.emit()

    def clear_log(self) -> None:
        self._log = []
        self.log_changed.emit()

    def get_log(self) -> List[str]:
        return list(self._log)

    def log_text(self) -> str:
        return "\n".join(self._log)

    def export_log(self, with_times: bool = False) -> str:
        """ينشئ نص السجل، اختيارياً مع أوقات الأسطر."""
        if not with_times:
            return self.log_text()
        lines: List[str] = []
        for cue in self.cues:
            lines.append(f"{format_timestamp(cue.start_ms)} {cue.text}")
        return "\n".join(lines)

    def export_srt(self) -> str:
        return to_srt(self.cues)

    # ------------------------------------------------------------ إحصاء
    def count(self) -> int:
        return len(self.cues)

    def lines_count_text(self) -> str:
        return str(len(self.cues))

    def first_text(self) -> str:
        return self.cues[0].text if self.cues else ""

    def bounds(self) -> tuple[int, int]:
        if not self.cues:
            return 0, 0
        return self.cues[0].start_ms, self.cues[-1].end_ms