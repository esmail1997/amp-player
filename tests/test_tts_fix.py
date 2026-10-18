"""اختبار ترقيع قائمة الأصوات في pyttsx3 (بلا تشغيل صوت فعلي)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ampplayer import tts_fix  # noqa: E402


class _FakeToken:
    """كيان يقلّد صوت SAPI: اللغة قيمة نصية مفصولة بفاصلة منقوطة."""

    def __init__(self, language: str) -> None:
        self._language = language
        self.Id = "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Test"

    def GetDescription(self) -> str:
        return "Test Voice"

    def GetAttribute(self, name: str):
        if name == "Language":
            return self._language
        if name == "Gender":
            return "Male"
        if name == "Age":
            return "Adult"
        return ""


class SingleLanguageTests(unittest.TestCase):
    def test_single_language_passes_through(self):
        shim = tts_fix._SingleLanguage(_FakeToken("0409"))
        self.assertEqual(shim.GetAttribute("Language"), "0409")

    def test_multi_language_reduced_to_first_valid(self):
        """بالضبط العطب: ``401;1`` كان يُسقط int(x, 16)."""
        shim = tts_fix._SingleLanguage(_FakeToken("401;1"))
        self.assertEqual(shim.GetAttribute("Language"), "401")

    def test_three_languages(self):
        shim = tts_fix._SingleLanguage(_FakeToken("401;409;10"))
        self.assertEqual(shim.GetAttribute("Language"), "401")

    def test_all_invalid_kept_unchanged(self):
        shim = tts_fix._SingleLanguage(_FakeToken("zz;yy"))
        self.assertEqual(shim.GetAttribute("Language"), "zz;yy")

    def test_other_attributes_and_members_forwarded(self):
        token = _FakeToken("401;1")
        shim = tts_fix._SingleLanguage(token)
        self.assertEqual(shim.GetAttribute("Gender"), "Male")
        self.assertEqual(shim.GetDescription(), "Test Voice")
        self.assertTrue(shim.Id.startswith("HKEY_"))


class ApplyTests(unittest.TestCase):
    def test_apply_is_idempotent(self):
        self.assertTrue(tts_fix.apply())
        from pyttsx3.drivers import sapi5

        first = sapi5.SAPI5Driver._toVoice
        self.assertTrue(getattr(first, "_amp_wrapped", False))
        self.assertTrue(tts_fix.apply())
        second = sapi5.SAPI5Driver._toVoice
        self.assertIs(first, second)

    def test_wrapped_driver_handles_multilang_token(self):
        """المسار كاملاً: من كيان SAPI إلى كائن Voice بلا خطأ."""
        self.assertTrue(tts_fix.apply())
        from pyttsx3.drivers import sapi5

        voice = sapi5.SAPI5Driver._toVoice(_FakeToken("401;1"))
        self.assertEqual(voice.name, "Test Voice")
        self.assertTrue(voice.languages)


if __name__ == "__main__":
    unittest.main()
