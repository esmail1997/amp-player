"""عامل نطق في خيط منفصل حتى لا تتجمد الواجهة.

نستخدم خيط بايثون عادي (daemon) بدل QThread حتى لا نحتاج إلى إدارة دورة
حياة خيط Qt، ولضمان أن إغلاق النافذة لا يُنهي العملية بشكل قسري.

محرّكات النطق (بترتيب الأفضلية الافتراضي):
1. NVDA عبر جسر NVDA Controller Client — النص يصل إلى NVDA فينطقه هو
   بصوته الخاص دون أن يلمس البرنامج جهاز الصوت، فلا تداخل مع صوت الفيلم
   ولا تقطيع. (الأفضل للمستخدمين المكفوفين الذين يشغّلون NVDA.)
2. pyttsx3 / SAPI5 — الرجوع التلقائي إن لم يكن NVDA يعمل.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject

from . import nvda_bridge

try:
    import pyttsx3

    _HAS_SAPI = True
except Exception:
    pyttsx3 = None  # type: ignore
    _HAS_SAPI = False

if _HAS_SAPI:
    # ترقيع عطب قائمة الأصوات في pyttsx3 على ويندوز (انظر tts_fix)
    from . import tts_fix

    tts_fix.apply()

# رسائل التحكم الداخلي
_MSG_SPEAK = "speak"
_MSG_STOP = "stop"
_MSG_CONFIG = "config"

_SHUTDOWN_TIMEOUT_MS = 1500

# قيم إعداد tts_engine
ENGINE_AUTO = "auto"      # NVDA إن كان يعمل، وإلا SAPI
ENGINE_NVDA = "nvda"      # NVDA فقط (SAPI احتياط فقط لو لم يوجد NVDA)
ENGINE_SYSTEM = "system"  # SAPI فقط


def tts_available() -> bool:
    """هل يوجد أي محرّك نطق في هذا النظام؟"""
    return _HAS_SAPI or nvda_bridge.dll_available()


class _Engine:
    """غلاف بسيط حول محركي النطق يعمل داخل خيط واحد فقط."""

    def __init__(self) -> None:
        self._q: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._engine = None
        self._rate = 175
        self._volume = 100
        self._voice = ""
        self._choice = ENGINE_AUTO
        self._backend = ENGINE_SYSTEM  # nvda أو sapi (يُقرَّر في التهيئة)
        self._enabled = False
        self._hold_ms = 600
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # مشغول بالنطق: تستعمله الواجهة لخفض صوت الفيلم أثناء القراءة
        self._busy = threading.Event()
        self._busy_until = 0.0

    # ---------- الطابور ----------
    def start(self) -> None:
        if not tts_available() or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="ampplayer-speech", daemon=True
        )
        self._thread.start()

    def configure(self, enabled: bool, rate: int, volume: int, voice: str,
                  choice: str = ENGINE_AUTO, hold_ms: int = 600) -> None:
        if not tts_available():
            return
        self.start()
        self._q.put((_MSG_CONFIG,
                     (bool(enabled), int(rate), int(volume), voice, str(choice),
                      max(0, int(hold_ms)))))

    def speak(self, text: str, force: bool = False) -> None:
        self.start()
        self._q.put((_MSG_SPEAK, (str(text), bool(force))))

    def stop(self) -> None:
        if self._thread is not None:
            self._q.put((_MSG_STOP, None))

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is None:
            return
        self._q.put((_MSG_STOP, None))
        self._thread.join(timeout=_SHUTDOWN_TIMEOUT_MS / 1000.0)
        self._thread = None

    # ---------- الحلقة ----------
    def _run(self) -> None:
        while True:
            try:
                kind, payload = self._q.get(timeout=0.2)
            except queue.Empty:
                if self._stop.is_set():
                    break
                continue
            if self._stop.is_set() and kind != _MSG_STOP:
                continue
            try:
                if kind == _MSG_CONFIG:
                    self._do_config(*payload)  # type: ignore[misc]
                elif kind == _MSG_SPEAK:
                    self._do_speak(*payload)
                elif kind == _MSG_STOP:
                    self._do_stop()
            except Exception:
                pass
        self._do_stop()

    # ---------- اختيار المحرك ----------
    def _select_backend(self) -> str:
        choice = self._choice
        if choice == ENGINE_NVDA:
            return ENGINE_NVDA if nvda_bridge.is_running() else ENGINE_SYSTEM
        if choice == ENGINE_SYSTEM:
            return ENGINE_SYSTEM
        # auto: NVDA إن كان يعمل
        if nvda_bridge.dll_available() and nvda_bridge.is_running():
            return ENGINE_NVDA
        return ENGINE_SYSTEM

    def _ensure_engine(self) -> bool:
        if self._engine is not None:
            return True
        try:
            self._engine = pyttsx3.init()
            return True
        except Exception:
            self._engine = None
            return False

    def _estimate_ms(self, text: str) -> int:
        """تقدير مدّة نطق نص (يُستخدم لرفع خفض الصوت بعد انتهاء النطق تقريباً)."""
        if not text:
            return 350
        wpm = max(50, int(self._rate or 175))
        chars_per_sec = wpm / 60.0 * 6.0  # قرابة 6 أحرف لكل كلمة
        secs = 0.35 + len(text) / max(1.0, chars_per_sec)
        return int(secs * 1000)

    def _do_config(self, enabled: bool, rate: int, volume: int, voice: str,
                   choice: str, hold_ms: int = 600) -> None:
        self._enabled = enabled
        self._rate, self._volume, self._voice = rate, volume, voice
        self._hold_ms = max(0, int(hold_ms))
        self._choice = choice if choice in (ENGINE_AUTO, ENGINE_NVDA, ENGINE_SYSTEM) else ENGINE_AUTO
        # يوقّف أي كلام معلّق ثم يقرّر المحرك المناسب
        self._do_stop()
        if not enabled:
            return
        self._backend = self._select_backend()
        if self._backend == ENGINE_NVDA:
            return  # NVDA يقرأ بإعدادات المستخدم وصوته؛ لا حاجة لضبط SAPI
        if not self._ensure_engine():
            return
        try:
            self._engine.setProperty("rate", self._rate)
            self._engine.setProperty("volume", self._volume / 100.0)
            if self._voice:
                for v in self._engine.getProperty("voices"):
                    if v.id == self._voice:
                        self._engine.setProperty("voice", v.id)
                        break
        except Exception:
            pass

    def _do_speak(self, text: str, force: bool = False) -> None:
        if not text or self._stop.is_set():
            return
        if not self._enabled and not force:
            return
        # عند الإجبار (أسطر الترجمة) أو عند غياب اختيار المحرك نختار المحرك
        # المناسب حاضرا (NVDA إن كان يعمل).
        back = self._backend
        if force or back == ENGINE_SYSTEM:
            back = self._select_backend()
            self._backend = back
        if back == ENGINE_NVDA:
            if not (nvda_bridge.dll_available() and nvda_bridge.is_running()):
                # NVDA توقف أثناء التشغيل: نجري على SAPI إن وُجد
                back = self._select_backend()
                self._backend = back
                if back != ENGINE_NVDA and not self._ensure_engine():
                    return
            if back == ENGINE_NVDA:
                ok = nvda_bridge.speak_text(str(text))
                if ok:
                    self._busy.set()
                    self._busy_until = (time.monotonic()
                                        + (self._estimate_ms(str(text)) + self._hold_ms) / 1000.0)
                return
        # SAPI
        if not self._ensure_engine():
            return
        try:
            self._engine.stop()
            self._engine.say(str(text))
            self._busy.set()
            self._busy_until = time.monotonic() + (self._estimate_ms(str(text)) + self._hold_ms) / 1000.0
            self._engine.runAndWait()
            # لا نمسح _busy هنا: يبقى مرفوعاً حتى تنتهي مهلة الخفض
            # (تقدير النطق + مدة الاحتفاظ) كما يقررها is_busy()
        except Exception:
            self._busy.clear()

    def is_busy(self) -> bool:
        """هل يجري النطق الآن؟ (يُقرأ من خيط الواجهة بأمان)"""
        if not self._busy.is_set():
            return False
        if self._busy_until and time.monotonic() >= self._busy_until:
            self._busy.clear()
            return False
        return True

    def _do_stop(self) -> None:
        nvda_bridge.cancel_speech()  # آمن حتى لو لم يوجد الجسر
        self._busy.clear()
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass


class SpeechController(QObject):
    """
    واجهة آمنة للاستخدام من خيط الواجهة:
    - say(): يضيف للنطق (لا يحجب)
    - stop(): يوقف النطق فوراً
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._available = tts_available()
        self._engine = _Engine()
        self._enabled = False

    @property
    def available(self) -> bool:
        return self._available

    @property
    def engine_backend(self) -> str:
        """المحرك الفعلي الحالي: nvda أو sapi."""
        return self._engine._backend  # noqa: SLF001 — مقروء لأغراض العرض

    def start(self) -> None:
        if self._available:
            self._engine.start()

    def configure(self, enabled: bool, rate: int = 175, volume: int = 100,
                  voice: str = "", choice: str = ENGINE_AUTO,
                  hold_ms: int = 600) -> None:
        self._enabled = bool(enabled)
        self._engine.configure(enabled, rate, volume, voice, choice,
                               hold_ms=max(0, int(hold_ms)))

    def say(self, text: str, force: bool = False) -> None:
        # force: يُنطق حتى لو كان النطق العام مطفأً (يُستخدم لأسطر الترجمة)
        if not self._available or not text:
            return
        if not self._enabled and not force:
            return
        self._engine.speak(text, force=force)

    def is_busy(self) -> bool:
        """هل يجري النطق الآن؟"""
        return self._engine.is_busy()

    def stop(self) -> None:
        self._engine.stop()

    def shutdown(self) -> None:
        self._engine.shutdown()