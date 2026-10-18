"""اختبارات الترجمة المدمجة داخل الفيديو (استخراج PyAV واختيار المسار).

لا تحتاج Qt ولا mpv؛ تُتخطّى اختبارات الملفات النموذجية إن غابت.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ampplayer import embedded_subs  # noqa: E402
from ampplayer.embedded_subs import EmbeddedTrack  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tools" / "fixtures"
MKV = FIXTURES / "embedded_srt.mkv"
MP4 = FIXTURES / "embedded_movtext.mp4"

EXPECTED_TEXTS = [
    "هذا سطر الترجمة الأول المدمج داخل الفيديو",
    "والآن السطر الثاني يُقرأ بصوت",
    "السطر الثالث والأخير في هذا الاختبار",
]


class TestLanguageHelpers(unittest.TestCase):
    def test_normalize_lang(self):
        self.assertEqual(embedded_subs.normalize_lang("ar"), "ara")
        self.assertEqual(embedded_subs.normalize_lang("AR-SA"), "ara")
        self.assertEqual(embedded_subs.normalize_lang("ara"), "ara")
        self.assertEqual(embedded_subs.normalize_lang("eng"), "eng")
        self.assertEqual(embedded_subs.normalize_lang(""), "")

    def test_lang_matches(self):
        self.assertTrue(embedded_subs.lang_matches("ar-SA", "ara"))
        self.assertTrue(embedded_subs.lang_matches("ara", "ar"))
        self.assertFalse(embedded_subs.lang_matches("eng", "ara"))
        self.assertFalse(embedded_subs.lang_matches("", "ara"))


class TestPickDefaultTrack(unittest.TestCase):
    def test_prefers_user_language_over_file_default(self):
        tracks = [EmbeddedTrack(2, "subrip", "eng", is_default=True),
                  EmbeddedTrack(3, "ass", "ar")]
        self.assertEqual(embedded_subs.pick_default_track(tracks, "ara").index, 3)
        self.assertEqual(embedded_subs.pick_default_track(tracks, "ar").index, 3)

    def test_falls_back_to_default_then_first(self):
        tracks = [EmbeddedTrack(2, "subrip", "eng"),
                  EmbeddedTrack(3, "subrip", "fra", is_default=True)]
        self.assertEqual(embedded_subs.pick_default_track(tracks, "ara").index, 3)
        tracks = [EmbeddedTrack(2, "subrip", "eng"), EmbeddedTrack(3, "subrip", "fra")]
        self.assertEqual(embedded_subs.pick_default_track(tracks, "ara").index, 2)

    def test_ignores_image_tracks(self):
        tracks = [EmbeddedTrack(2, "hdmv_pgs_subtitle", "ara", is_default=True),
                  EmbeddedTrack(3, "subrip", "eng")]
        pick = embedded_subs.pick_default_track(tracks, "ara")
        self.assertEqual(pick.index, 3)
        self.assertIsNone(embedded_subs.pick_default_track(
            [EmbeddedTrack(2, "dvd_subtitle", "ara")], "ara"))
        self.assertIsNone(embedded_subs.pick_default_track([], "ara"))

    def test_prefers_non_forced(self):
        tracks = [EmbeddedTrack(2, "subrip", "ara", is_forced=True),
                  EmbeddedTrack(3, "subrip", "ara")]
        self.assertEqual(embedded_subs.pick_default_track(tracks, "ara").index, 3)

    def test_track_flags(self):
        self.assertTrue(EmbeddedTrack(1, "mov_text").is_text)
        self.assertTrue(EmbeddedTrack(1, "SubRip").is_text)
        self.assertTrue(EmbeddedTrack(1, "hdmv_pgs_subtitle").is_image)
        self.assertFalse(EmbeddedTrack(1, "hdmv_pgs_subtitle").is_text)


class TestAssEventToText(unittest.TestCase):
    def test_keeps_commas_in_text_and_strips_tags(self):
        raw = r"0,0,Default,,0,0,0,,Hello, world {\i1}x{\i0}\Nline2"
        self.assertEqual(embedded_subs.ass_event_to_text(raw), "Hello, world x\nline2")

    def test_plain_text_passthrough(self):
        self.assertEqual(embedded_subs.ass_event_to_text("مرحبا"), "مرحبا")
        self.assertEqual(embedded_subs.ass_event_to_text(""), "")


class TestFixtures(unittest.TestCase):
    def test_list_tracks_mkv(self):
        if not MKV.exists():
            self.skipTest("fixture embedded_srt.mkv missing")
        tracks = embedded_subs.list_embedded_tracks(str(MKV))
        self.assertEqual(len(tracks), 1)
        t = tracks[0]
        self.assertEqual(t.index, 2)
        self.assertIn(t.codec, ("srt", "subrip"))
        self.assertTrue(t.is_text)

    def test_list_tracks_mp4(self):
        if not MP4.exists():
            self.skipTest("fixture embedded_movtext.mp4 missing")
        tracks = embedded_subs.list_embedded_tracks(str(MP4))
        self.assertEqual(len(tracks), 1)
        t = tracks[0]
        self.assertEqual(t.index, 2)
        self.assertEqual(t.codec, "mov_text")
        self.assertEqual(t.language, "ara")
        self.assertTrue(t.is_default)
        self.assertEqual(embedded_subs.pick_default_track(tracks, "ara").index, 2)

    def _check_cues(self, cues):
        self.assertEqual([c.index for c in cues], [1, 2, 3])
        self.assertEqual([c.start_ms for c in cues], [1000, 4000, 8000])
        for c in cues:
            self.assertEqual(c.end_ms - c.start_ms, 2500)
        self.assertEqual([c.text for c in cues], EXPECTED_TEXTS)

    def test_extract_mkv(self):
        if not MKV.exists():
            self.skipTest("fixture embedded_srt.mkv missing")
        self._check_cues(embedded_subs.extract_embedded_cues(str(MKV), 2))

    def test_extract_mp4(self):
        if not MP4.exists():
            self.skipTest("fixture embedded_movtext.mp4 missing")
        self._check_cues(embedded_subs.extract_embedded_cues(str(MP4), 2))

    def test_extract_non_subtitle_stream_is_empty(self):
        if not MKV.exists():
            self.skipTest("fixture embedded_srt.mkv missing")
        self.assertEqual(embedded_subs.extract_embedded_cues(str(MKV), 0), [])
        self.assertEqual(embedded_subs.extract_embedded_cues(str(MKV), 99), [])

    def test_missing_file_is_safe(self):
        self.assertEqual(embedded_subs.list_embedded_tracks("no_such_file.mkv"), [])
        self.assertEqual(embedded_subs.extract_embedded_cues("no_such_file.mkv", 2), [])

    def test_should_stop_is_honoured(self):
        if not MKV.exists():
            self.skipTest("fixture embedded_srt.mkv missing")
        # إلغاء فوري: لا استثناء، والنتيجة قائمة (قد تكون جزئية)
        cues = embedded_subs.extract_embedded_cues(str(MKV), 2, should_stop=lambda: True)
        self.assertIsInstance(cues, list)


if __name__ == "__main__":
    unittest.main()
