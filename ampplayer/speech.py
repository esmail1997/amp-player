"""محرك النطق (Text-to-Speech) باستخدام pyttsx3."""

from __future__ import annotations

from typing import List

try:
    import pyttsx3
    _HAS_PYTTSX3 = True
except Exception:
    pyttsx3 = None  # type: ignore
    _HAS_PYTTSX3 = False

if _HAS_PYTTSX3:
    # ترقيع عطب قائمة الأصوات في pyttsx3 على ويندوز (انظر tts_fix)
    from . import tts_fix

    tts_fix.apply()


class Speaker:
    """
    غلاف حول pyttsx3 يوفر:
    - نطق غير حاجب (non-blocking) في خيط منفصل
    - إيقاف فوري
    - اختيار الصوت والسرعة
    """

    def __init__(self) -> None:
        self._engine = None
        self._enabled = False
        self._rate = 175
        self._volume = 100
        self._voice_id = ""
        self._busy = False
        self._ready = _HAS_PYTTSX3

    @property
    def available(self) -> bool:
        return self._ready

    def init(self) -> bool:
        """تهيئة محرك النطق (مرة واحدة)."""
        if not self._ready:
            return False
        if self._engine is not None:
            return True
        try:
            self._engine = pyttsx3.init()
            self._apply()
            return True
        except Exception:
            self._ready = False
            self._engine = None
            return False

    def voices(self) -> List[tuple[str, str]]:
        """قائمة الأصوات المتاحة (id, اسم)."""
        if not self.init():
            return []
        try:
            return [(v.id, v.name) for v in self._engine.getProperty("voices")]  # type: ignore[union-attr]
        except Exception:
            return []

    def set_voice(self, voice_id: str) -> None:
        self._voice_id = voice_id
        self._apply()

    def set_rate(self, rate: int) -> None:
        self._rate = int(rate)
        self._apply()

    def set_volume(self, vol: int) -> None:
        self._volume = int(vol)
        self._apply()

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        if on:
            self.init()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _apply(self) -> None:
        if self._engine is None:
            return
        try:
            self._engine.setProperty("rate", self._rate)
            self._engine.setProperty("volume", self._volume / 100.0)
            if self._voice_id:
                for v in self._engine.getProperty("voices"):
                    if v.id == self._voice_id:
                        self._engine.setProperty("voice", v.id)
                        break
        except Exception:
            pass

    def speak(self, text: str, interrupt: bool = True) -> None:
        """ينطق نصاً بشكل غير حاجب."""
        if not text or not self._enabled:
            return
        if not self.init():
            return
        try:
            if interrupt:
                self._engine.stop()  # type: ignore[union-attr]
            self._busy = True
            self._engine.say(text)  # type: ignore[union-attr]
            self._engine.runAndWait()  # type: ignore[union-attr]
            self._busy = False
        except Exception:
            self._busy = False

    def stop(self) -> None:
        try:
            if self._engine is not None:
                self._engine.stop()  # type: ignore[union-attr]
        except Exception:
            pass
        self._busy = False


# نسخة مشتركة
speaker = Speaker()