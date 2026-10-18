"""
مدير مصادر الترجمة الموحّد + سياسة النطق.

الهدف: مصدر واحد فقط يقرأ، مهما تعدّدت المصادر المتاحة. الأولوية:
ملف الترجمة الخارجي > الترجمة المدمجة داخل الفيديو > الترجمة البعيدة
التي جُلبت من مصدر الفيديو (يوتيوب).

وضعان:
- auto:   يختار أعلى مصدر متاح يعمل فعلاً.
- manual: المستخدم يثبّت المصدر بنفسه.

سياسة النطق (SpeakPolicy): تمنع تكرار السطر نفسه (مع تجاهل التشكيل/الترقيم)
وتُسقط السطور القديمة بدل تكديسها في الطابور.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, List, Optional

from .subtitle_text import dedup_key, is_similar

MODE_AUTO = "auto"
MODE_MANUAL = "manual"


class SourceKind(IntEnum):
    REMOTE = 10
    EMBEDDED = 15
    EXTERNAL = 20


# أعلى = أولوية أكبر
PRIORITY: List[SourceKind] = [
    SourceKind.EXTERNAL,
    SourceKind.EMBEDDED,
    SourceKind.REMOTE,
]

LABEL_KEY = {
    SourceKind.EXTERNAL: "src.external",
    SourceKind.EMBEDDED: "src.embedded",
    SourceKind.REMOTE: "src.remote",
}

MODE_KEY = {MODE_AUTO: "src.mode_auto", MODE_MANUAL: "src.mode_manual"}


@dataclass
class SourceStatus:
    kind: SourceKind
    available: bool = False
    detail: str = ""


class SubtitleManager:
    """يدير أيّ مصدر ترجمة يُقرأ الآن. لا يعرف Qt ولا NVDA."""

    def __init__(self, mode: str = MODE_AUTO) -> None:
        self._mode = MODE_MANUAL if mode == MODE_MANUAL else MODE_AUTO
        self._manual: Optional[SourceKind] = None
        self._sources: Dict[SourceKind, SourceStatus] = {
            k: SourceStatus(k) for k in SourceKind
        }

    # ---------- الإعداد ----------
    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = MODE_MANUAL if mode == MODE_MANUAL else MODE_AUTO

    def set_source(self, kind: SourceKind, available: bool,
                   detail: str = "") -> None:
        st = self._sources.get(kind) or SourceStatus(kind)
        st.available = bool(available)
        st.detail = detail or ""
        self._sources[kind] = st

    def select(self, kind: Optional[SourceKind]) -> None:
        """اختيار يدوي لمصدر (None = إلغاء التثبيت)."""
        self._manual = kind
        self._mode = MODE_MANUAL if kind is not None else MODE_AUTO

    def clear(self) -> None:
        for st in self._sources.values():
            st.available = False
            st.detail = ""
        self._manual = None

    # ---------- القرار ----------
    def available_sources(self) -> List[SourceStatus]:
        return [self._sources[k] for k in PRIORITY if self._sources[k].available]

    def active(self) -> Optional[SourceStatus]:
        """المصدر الذي يجب القراءة منه الآن (واحد فقط)."""
        if self._mode == MODE_MANUAL:
            if self._manual is None:
                return None
            st = self._sources.get(self._manual)
            return st if (st is not None and st.available) else None
        for k in PRIORITY:
            st = self._sources.get(k)
            if st is not None and st.available:
                return st
        return None

    def active_kind(self) -> Optional[SourceKind]:
        st = self.active()
        return st.kind if st is not None else None

    def is_active(self, kind: SourceKind) -> bool:
        return self.active_kind() == kind


class SpeakPolicy:
    """
    قرار نطق سطر واحد: يمنع التكرار ويُسقط القديم.

    - ``offer`` يعيد النصّ الذي يجب نطقه، أو None إن كان مكرّراً/قديماً.
    - لا نُكدّس أسطراً: الأسطر التي مضى وقتها لا تُقرأ، بل يُقرأ السطر
      الحالي فقط. هذا مقصود لتفادي تراكم ترجمة قديمة متأخرة عن الصورة.
    """

    def __init__(self, stale_seconds: float = 4.0,
                 similarity: float = 0.86) -> None:
        self._last_key = ""
        self._last_text = ""
        self._last_ms = -10 ** 9
        self._stale_ms = int(max(0.5, stale_seconds) * 1000)
        self._similarity = similarity
        self._chars = 0
        self._lines = 0

    @property
    def last_text(self) -> str:
        return self._last_text

    @property
    def chars_spoken(self) -> int:
        return self._chars

    @property
    def lines_spoken(self) -> int:
        return self._lines

    def reset(self) -> None:
        self._last_key = ""
        self._last_text = ""
        self._last_ms = -10 ** 9

    def offer(self, text: str, pos_ms: int,
              stale_window: bool = True) -> Optional[str]:
        """
        يُقرّ إن كان يجب نطق ``text`` عند الزمن ``pos_ms``.

        stale_window=False يتجاهل فحص القدم (يُستعمل للقراءة اليدوية).
        """
        text = (text or "").strip()
        if not text:
            return None
        key = dedup_key(text)
        if not key:
            return None
        if key == self._last_key:
            # السطر نفسه حرفيّاً: لا نكرّره
            self._last_ms = pos_ms
            return None
        if is_similar(text, self._last_text, self._similarity):
            # اختلاف طفيف: نعتبره السطر نفسه لكن نحدّث النصّ الأخير
            self._last_text = text
            self._last_ms = pos_ms
            return None
        if stale_window and (pos_ms - self._last_ms) > self._stale_ms and self._last_ms > -10 ** 8:
            # فجوة كبيرة: سطر قديم تخلّفه التشغيل، نتجاوزه ونبدأ من الجديد
            pass
        self._last_key = key
        self._last_text = text
        self._last_ms = pos_ms
        self._chars += len(text)
        self._lines += 1
        return text

    def peek_is_new(self, text: str) -> bool:
        """هل يختلف هذا النصّ عن آخر منطوق (بلا تحديث الحالة)؟"""
        key = dedup_key(text)
        if not key or key == self._last_key:
            return False
        return not is_similar(text, self._last_text, self._similarity)
