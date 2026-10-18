"""اختبارات وحدةAmp Player (بدون واجهة رسومية)."""

from __future__ import annotations

import glob
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ampplayer.subtitle_parser import (  # noqa: E402
    clean_ass_text,
    cues_in_range,
    find_cue,
    format_duration,
    format_timestamp,
    parse_ass,
    parse_file,
    parse_microdvd,
    parse_srt_vtt,
    sidecar_candidates,
    to_srt,
)

SRT_SAMPLE = """1
00:00:01,000 --> 00:00:03,500
مرحبا بالعالم

2
00:00:04,000 --> 00:00:06,000
Hello World
ثاني

3
00:01:02,250 --> 00:01:04,000
السطر الثالث
"""

VTT_SAMPLE = """WEBVTT

00:00:01.000 --> 00:00:03.500
<c.colorE5E5E5>مرحبا</c> بالعالم

00:00:04.000 --> 00:00:06.000
Hello World
"""

ASS_SAMPLE = """[Script Info]
Title: Test
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Default,Arial,20

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,{\\an8}مرحبا\\Nبالعالم
Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,Hello World
"""


class TestTimestamp(unittest.TestCase):
    def test_format_timestamp(self):
        self.assertEqual(format_timestamp(0), "00:00:00,000")
        self.assertEqual(format_timestamp(3_661_500), "01:01:01,500")
        self.assertEqual(format_timestamp(-5), "00:00:00,000")

    def test_format_duration(self):
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(65), "1:05")
        self.assertEqual(format_duration(3725), "1:02:05")
        self.assertEqual(format_duration(-3), "0:00")

    def test_parse_variants(self):
        cues = parse_srt_vtt("1\n0:00:01,5 --> 0:00:02,25\nx\n")
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].start_ms, 1500)
        self.assertEqual(cues[0].end_ms, 2250)


class TestSrt(unittest.TestCase):
    def test_parse_basic(self):
        cues = parse_srt_vtt(SRT_SAMPLE)
        self.assertEqual(len(cues), 3)
        self.assertEqual(cues[0].start_ms, 1000)
        self.assertEqual(cues[0].end_ms, 3500)
        self.assertEqual(cues[0].text, "مرحبا بالعالم")
        self.assertEqual(cues[1].text, "Hello World\nثاني")
        self.assertEqual(cues[2].start_ms, 62_250)

    def test_round_trip(self):
        cues = parse_srt_vtt(SRT_SAMPLE)
        again = parse_srt_vtt(to_srt(cues))
        self.assertEqual(len(again), 3)
        self.assertEqual([c.start_ms for c in cues], [c.start_ms for c in again])
        self.assertEqual([c.text for c in cues], [c.text for c in again])

    def test_missing_text_blocks_ignored(self):
        s = "1\n00:00:01,000 --> 00:00:02,000\n\n2\n00:00:03,000 --> 00:00:04,000\nok\n"
        cues = parse_srt_vtt(s)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].text, "ok")

    def test_broken_timestamps_skipped(self):
        s = "1\ngarbage --> garbage\ntext\n2\n00:00:03,000 --> 00:00:04,000\nok\n"
        cues = parse_srt_vtt(s)
        self.assertEqual(len(cues), 1)

    def test_no_blank_lines_index_not_glued(self):
        # SRT متلاصقة بلا أسطر فارغة: فهرس السطر التالي لا يلتصق بالنص
        s = ("1\n00:00:01,000 --> 00:00:03,000\nأول\n"
             "2\n00:00:04,000 --> 00:00:06,000\nثاني\n"
             "3\n00:00:08,000 --> 00:00:10,000\nثالث\n")
        cues = parse_srt_vtt(s)
        self.assertEqual(len(cues), 3, [c.text for c in cues])
        self.assertEqual(cues[0].text, "أول")
        self.assertEqual(cues[1].text, "ثاني")
        self.assertEqual(cues[2].text, "ثالث")


class TestVtt(unittest.TestCase):
    def test_strips_tags(self):
        cues = parse_srt_vtt(VTT_SAMPLE, vtt=True)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].text, "مرحبا بالعالم")
        self.assertEqual(cues[0].start_ms, 1000)

    def test_webvtt_header_skipped(self):
        cues = parse_srt_vtt("WEBVTT\nKind: captions\n\n00:00:01.000 --> 00:00:02.000\nhi\n")
        self.assertEqual(len(cues), 1)


class TestAss(unittest.TestCase):
    def test_parse(self):
        cues = parse_ass(ASS_SAMPLE)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].start_ms, 1000)
        self.assertEqual(cues[0].end_ms, 3500)
        self.assertEqual(cues[0].text, "مرحبا\nبالعالم")
        self.assertEqual(cues[1].text, "Hello World")

    def test_clean_tags(self):
        # \h = مسافة صلبة، و {\an8} = محاذاة أعلى
        self.assertEqual(clean_ass_text(r"{\an8}مرحبا{\i1}يا\hعالم"), "مرحبايا عالم")

    def test_commas_in_text_preserved(self):
        s = ("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
             "MarginV, Effect, Text\n"
             "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,one, two, three\n")
        cues = parse_ass(s)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].text, "one, two, three")


class TestMicroDvd(unittest.TestCase):
    def test_parse(self):
        content = "[25][50]Line one|Line two\n[75][100]Second\n"
        cues = parse_microdvd(content)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].start_ms, 1000)
        self.assertEqual(cues[0].end_ms, 2000)
        self.assertEqual(cues[0].text, "Line one\nLine two")


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.cues = parse_srt_vtt(SRT_SAMPLE)

    def test_find_active(self):
        self.assertIsNotNone(find_cue(self.cues, 2000))
        self.assertIsNotNone(find_cue(self.cues, 5000))

    def test_find_gap(self):
        # السطر الأول ينتهي 3500 (+تسامح 400) والثاني يبدأ 4000
        # لذا 3950 فجوة حقيقية
        self.assertIsNone(find_cue(self.cues, 3950))
        self.assertIsNone(find_cue(self.cues, 0))

    def test_find_cue_tolerance(self):
        self.assertIsNotNone(find_cue(self.cues, 3600))

    def test_cues_in_range(self):
        got = cues_in_range(self.cues, 0, 5000)
        self.assertEqual(len(got), 2)
        # السطر الثالث: 62250 -> 64000
        got2 = cues_in_range(self.cues, 60_000, 63_000)
        self.assertEqual(len(got2), 1)
        self.assertEqual(cues_in_range(self.cues, 70_000, 80_000), [])


class TestFiles(unittest.TestCase):
    def test_parse_file_detects(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.srt"
            p.write_text(SRT_SAMPLE, encoding="utf-8")
            self.assertEqual(len(parse_file(p)), 3)
            p2 = Path(d) / "a.vtt"
            p2.write_text(VTT_SAMPLE, encoding="utf-8")
            self.assertEqual(len(parse_file(p2)), 2)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            parse_file("/nonexistent/nope.srt")

    def test_utf8_bom(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.srt"
            p.write_bytes(b"\xef\xbb\xbf" + SRT_SAMPLE.encode("utf-8"))
            self.assertEqual(len(parse_file(p)), 3)

    def test_cp1256(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.srt"
            text = "1\n00:00:01,000 --> 00:00:03,000\nمرحبا\n"
            p.write_bytes(text.encode("cp1256"))
            cues = parse_file(p)
            self.assertEqual(len(cues), 1)

    def test_sidecar_detection(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            v = d / "Movie.mkv"
            v.write_bytes(b"x")
            (d / "Movie.srt").write_text(SRT_SAMPLE, encoding="utf-8")
            (d / "Movie.ar.srt").write_text(SRT_SAMPLE, encoding="utf-8")
            (d / "Other.srt").write_text(SRT_SAMPLE, encoding="utf-8")
            found = sidecar_candidates(v)
            names = [f.name for f in found]
            self.assertIn("Movie.srt", names)
            self.assertIn("Movie.ar.srt", names)
            self.assertNotIn("Other.srt", names)
            self.assertEqual(found[0].name, "Movie.srt")


class TestRealWorld(unittest.TestCase):
    """اختبارات على ملفات تنزيلها فعلاً من SubDL (إن وُجدت)."""

    def test_downloaded_arabic_subtitle(self):
        pats = glob.glob(str(Path(tempfile.gettempdir()) / "tmp*" / "*.ass"))
        pats += glob.glob(str(Path(tempfile.gettempdir()) / "tmp*" / "*.srt"))
        if not pats:
            self.skipTest("no downloaded subtitle found")
        cues = parse_file(pats[0])
        self.assertGreater(len(cues), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)