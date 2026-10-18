"""
اختبارات محرك التشغيل mpv (python-mpv + libmpv) وجسر NVDA.

متسامحة مع بيئة خالية من المكتبات: حين لا يجد الاختبار libmpv يكتفي
بالتأكد من انسحاق النية (التراجع التلقائي إلى محرك FFmpeg) دون فشل.
المدرَجة في السجل كلها بلا Qt ولا جهاز صوت، فلا حاجة لمشغّل مثبت.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ampplayer import av_engine, config, mpv_engine  # noqa: E402
from ampplayer import nvda_bridge  # noqa: E402
from ampplayer import player as player_mod  # noqa: E402

# الدوال والخصائص التي يناديها PlayerController على أي محرك.
ENGINE_SURFACE = [
    "initialize", "open", "play", "pause", "toggle_pause",
    "is_playing", "is_paused", "stop",
    "get_time", "get_duration", "set_time",
    "get_position", "set_position",
    "set_volume", "set_muted", "set_rate", "set_duck",
    "set_output_device", "list_output_devices", "audio_diagnostics",
    "get_tracks", "select_audio_stream",
    "set_render_max", "set_decode_threads", "set_sub_delay", "close",
    "cues", "audio_output_available", "audio_output_error", "engine_version",
]


def _mpv_ok() -> bool:
    return mpv_engine.mpv_ready()[0]


class TestSlotBuffer(unittest.TestCase):
    """المخازن المتناوبة لمحلّل البرمجيات: محاذاة وعرض صف صحيحان."""

    def test_alignment_and_view(self) -> None:
        w, h = 160, 100
        stride = ((w * 4) + 63) & ~63
        slot = mpv_engine._Slot(stride * h + 64, w, h)
        self.assertEqual(slot.addr % 64, 0, "address must be 64-byte aligned")
        self.assertGreaterEqual(slot.stride, w * 4)
        self.assertEqual(slot.rgb.shape, (h, w, 3))
        # strides[0] هو نفس stride المطلوب للرسم (صفوف محشوة)
        self.assertEqual(slot.rgb.strides[0], slot.stride)


class TestMpvEngine(unittest.TestCase):
    def test_ready_reports_bool(self) -> None:
        ok, note = mpv_engine.mpv_ready()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(note, str)
        self.assertIsInstance(mpv_engine.mpv_version(), str)

    @unittest.skipUnless(_mpv_ok(), "libmpv absent")
    def test_render_param_patch_installed(self) -> None:
        """معاملات الرسم البرمجي (17..20) مضبوطة بعد استيراد المكتبة."""
        types = mpv_engine._mpv_mod.MpvRenderParam.TYPES
        self.assertIn("sw_size", types)
        self.assertIn("sw_format", types)
        self.assertIn("sw_stride", types)
        self.assertIn("sw_pointer", types)
        self.assertEqual(types["sw_size"][0], 17)
        self.assertEqual(types["sw_format"][0], 18)
        self.assertEqual(types["sw_stride"][0], 19)
        self.assertEqual(types["sw_pointer"][0], 20)

    def test_interface_surface(self) -> None:
        """كل ما يناديه PlayerController متوفر على المحرك الجديد."""
        # engine_version ليست في القائمة المشتركة: المحرك القديم يعرضها عبر
        # دالة وحدة (av_version)، والجديد عبر خاصية — وPlayerController يتعامل
        # مع الاثنين بـ getattr.
        shared = [n for n in ENGINE_SURFACE if n != "engine_version"]
        missing = [n for n in shared if not hasattr(mpv_engine.MpvEngine, n)]
        self.assertEqual(missing, [], f"mpv engine missing: {missing}")
        # وسيلة تحقق: واجهة المحرك القديم تفهمها أيضاً
        old_missing = [n for n in shared if not hasattr(av_engine.MediaEngine, n)]
        self.assertEqual(old_missing, [], f"av engine missing: {old_missing}")
        self.assertTrue(hasattr(mpv_engine.MpvEngine, "engine_version"))

    def test_factory_choices(self) -> None:
        cfg = config.Config()
        cfg.set("player_engine", "pyav")
        self.assertIsInstance(player_mod._pick_engine(cfg), av_engine.MediaEngine)

        cfg.set("player_engine", "mpv")
        eng = player_mod._pick_engine(cfg)
        if _mpv_ok():
            self.assertIsInstance(eng, mpv_engine.MpvEngine)
        else:
            # غياب mpv = تراجع تلقائي إلى FFmpeg (لا فشل)
            self.assertIsInstance(eng, av_engine.MediaEngine)

    def test_subtitle_live_surface(self) -> None:
        """Methods ونهايات النص الحي للترجمة موجودة على محرك mpv وحدها."""
        self.assertTrue(hasattr(mpv_engine.MpvEngine, "current_subtitle_text"))
        self.assertTrue(hasattr(mpv_engine.MpvEngine, "attach_subtitle"))
        # محرك FFmpeg: لا يحتاجها (PlayerController يستعمل getattr بأمان)
        self.assertFalse(hasattr(av_engine.MediaEngine, "current_subtitle_text"))
        self.assertFalse(hasattr(av_engine.MediaEngine, "attach_subtitle"))
        # قبل أي تهيئة: قيم آمنة بلا استثناء
        eng = mpv_engine.MpvEngine(config.Config())
        self.assertEqual(eng.current_subtitle_text(), "")
        self.assertFalse(eng.attach_subtitle(""))
        eng.close()

    def _wait_file_loaded(self, eng, timeout: float = 3.0) -> None:
        import time

        deadline = time.monotonic() + timeout
        while eng._mpv is None or not getattr(eng, "_has_file", False):
            if time.monotonic() > deadline:
                self.fail("file-loaded لم يصل خلال المهلة")
            time.sleep(0.1)

    def _wait_text(self, eng, expected: str, timeout: float = 5.0) -> str:
        import time

        seen = ""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            seen = eng.current_subtitle_text()
            if seen == expected:
                break
            time.sleep(0.1)
        return seen

    @unittest.skipUnless(_mpv_ok(), "libmpv absent")
    def test_embedded_track_is_read_after_selection_and_external_overrides(self) -> None:
        """المسار المدمج يُقرأ بعد اختياره، وملف خارجي يتقدّم عليه، ثم الإلغاء يصفّر sid.

        ملف الاختبار يحوي 3 أسطر مدمجة (srt) في التيار رقم 2.
        """
        import tempfile

        fix = Path(__file__).resolve().parent.parent / "tools" / "fixtures" / "embedded_srt.mkv"
        if not fix.exists():
            self.skipTest("fixture embedded_srt.mkv missing")

        eng = mpv_engine.MpvEngine(config.Config())
        try:
            ok, err = eng.initialize()
            self.assertTrue(ok, err)
            ok, err = eng.open(str(fix))
            self.assertTrue(ok, err)
            self._wait_file_loaded(eng)
            # لا شيء مختار تلقائياً قبل أن تطلبه الواجهة
            self.assertFalse(eng._mpv.sid)
            self.assertEqual([t.index for t in eng.list_subtitle_tracks()], [2])

            # اختيار المسار المدمج → النص الحي هو السطر الأول
            self.assertTrue(eng.select_subtitle_stream(2))
            eng.set_time(1.2)
            eng.play()
            self.assertEqual(
                self._wait_text(eng, "هذا سطر الترجمة الأول المدمج داخل الفيديو"),
                "هذا سطر الترجمة الأول المدمج داخل الفيديو",
            )

            # ملف خارجي يتقدّم على المدمج
            srt = tempfile.NamedTemporaryFile(
                "w", suffix=".srt", encoding="utf-8", delete=False
            )
            try:
                srt.write(
                    "1\n00:00:01,000 --> 00:00:03,000\nسطر خارجي للتجربة\n\n"
                )
                srt.close()
                self.assertTrue(eng.attach_subtitle(srt.name))
                eng.set_time(1.2)
                eng.play()
                self.assertEqual(self._wait_text(eng, "سطر خارجي للتجربة"),
                                 "سطر خارجي للتجربة")
                selected = [t for t in eng._mpv.track_list
                            if t.get("type") == "sub" and t.get("selected")]
                self.assertTrue(selected and selected[0].get("external"))

                # العودة إلى المدمج ثم الإلغاء
                self.assertTrue(eng.select_subtitle_stream(2))
                eng.set_time(4.2)
                self.assertEqual(self._wait_text(eng, "والآن السطر الثاني يُقرأ بصوت"),
                                 "والآن السطر الثاني يُقرأ بصوت")
                self.assertTrue(eng.select_subtitle_stream(None))
                self.assertFalse(eng._mpv.sid)
            finally:
                os.unlink(srt.name)
            # فهرس غير ترجمي يُرفض
            self.assertFalse(eng.select_subtitle_stream(0))
        finally:
            eng.close()

    @unittest.skipUnless(_mpv_ok(), "libmpv absent")
    def test_subtitle_selection_before_file_loaded_survives(self) -> None:
        """اختيار الترجمة قبل وصول file-loaded لا يضيع (كان sid يُصفَّر عند التحميل)."""
        import time

        fixtures = Path(__file__).resolve().parent.parent / "tools" / "fixtures"
        fix = fixtures / "embedded_srt.mkv"
        srt = fixtures / "subs.srt"
        if not fix.exists() or not srt.exists():
            self.skipTest("fixtures missing")

        # 1) ملف خارجي مُرفق فور open()
        eng = mpv_engine.MpvEngine(config.Config())
        try:
            ok, err = eng.initialize()
            self.assertTrue(ok, err)
            ok, err = eng.open(str(fix))
            self.assertTrue(ok, err)
            self.assertTrue(eng.attach_subtitle(str(srt)))
            self._wait_file_loaded(eng)
            time.sleep(0.4)
            sel = [t for t in eng._mpv.track_list
                   if t.get("type") == "sub" and t.get("selected")]
            self.assertTrue(sel, "no subtitle track selected after file-loaded")
            self.assertTrue(sel[0].get("external"))
        finally:
            eng.close()

        # 2) مسار مدمج مختار فور open()
        eng = mpv_engine.MpvEngine(config.Config())
        try:
            ok, err = eng.initialize()
            self.assertTrue(ok, err)
            ok, err = eng.open(str(fix))
            self.assertTrue(ok, err)
            self.assertTrue(eng.select_subtitle_stream(2))
            self._wait_file_loaded(eng)
            time.sleep(0.4)
            sel = [t for t in eng._mpv.track_list
                   if t.get("type") == "sub" and t.get("selected")]
            self.assertTrue(sel, "embedded track not selected after file-loaded")
            self.assertFalse(sel[0].get("external"))
            self.assertEqual(int(sel[0].get("ff-index", -1)), 2)
        finally:
            eng.close()

    def test_lifecycle_safe(self) -> None:
        """تهيئة وإغلاق المحرك بلا ملف: لا تعثر ولا استثناء."""
        eng = mpv_engine.MpvEngine(config.Config())
        eng.close()  # إغلاق قبل أي تهيئة: لا شيء يجب أن يقع
        if not _mpv_ok():
            return
        eng = mpv_engine.MpvEngine(config.Config())
        ok, err = eng.initialize()
        self.assertTrue(ok, err)
        self.assertTrue(eng.audio_output_available)
        self.assertEqual(eng.get_time(), 0.0)
        self.assertEqual(eng.get_duration(), 0.0)
        self.assertFalse(eng.is_playing())
        eng.close()
        # بعد الإغلاق يظل «متاحاً» بالمعنى الحرفي (المكتبة في الحزمة)،
        # لكن لا شيء مشغلاً:
        self.assertIsNone(eng._mpv)
        self.assertFalse(eng.is_playing())


class TestEmbeddedSubtitleSurface(unittest.TestCase):
    """واجهة اختيار مسار الترجمة المدمج موجودة وآمنة قبل التهيئة."""

    def test_engine_and_controller_expose_embedded_selection(self) -> None:
        self.assertTrue(hasattr(mpv_engine.MpvEngine, "select_subtitle_stream"))
        self.assertTrue(hasattr(mpv_engine.MpvEngine, "list_subtitle_tracks"))
        self.assertTrue(hasattr(player_mod.PlayerController, "select_subtitle_stream"))
        self.assertTrue(hasattr(player_mod.PlayerController, "get_subtitle_tracks"))

    def test_safe_before_initialize(self) -> None:
        eng = mpv_engine.MpvEngine(config.Config())
        self.assertFalse(eng.select_subtitle_stream(2))
        self.assertFalse(eng.select_subtitle_stream(None))
        self.assertEqual(eng.list_subtitle_tracks(), [])
        eng.close()


class TestNvdaBridge(unittest.TestCase):
    def test_functions_are_safe(self) -> None:
        self.assertIsInstance(nvda_bridge.dll_available(), bool)
        self.assertIsInstance(nvda_bridge.is_running(), bool)
        # نص فارغ: لا يُنطق، ويعود نجاحاً بلا خطأ
        self.assertTrue(nvda_bridge.speak_text(""))
        nvda_bridge.cancel_speech()  # بلا استثناء حتى لو NVDA غير يعمل
        self.assertIsInstance(nvda_bridge.engine_summary(), str)

    def test_selftest_check_mpv(self) -> None:
        from ampplayer.selftest import _check_mpv

        self.assertIsInstance(_check_mpv(), str)


class TestForcedSubtitleSpeech(unittest.TestCase):
    """نطق الترجمة يصل إلى القارئ حتى مع إيقاف النطق العام (force)."""

    def test_forced_speech_reaches_nvda_bridge(self) -> None:
        from ampplayer import nvda_bridge
        from ampplayer.speech_worker import SpeechController

        if not nvda_bridge.dll_available():
            self.skipTest("nvda dll absent")
        records: list = []
        orig = nvda_bridge.speak_text
        nvda_bridge.speak_text = lambda t: (records.append(str(t)) or True)  # type: ignore[assignment]
        sc = SpeechController()
        try:
            sc.configure(enabled=False, rate=175, volume=100, voice="", choice="auto")
            sc.say("normal-dropped-when-disabled")
            self._spin(0.5)
            self.assertEqual(records, [], "non-forced say must drop when disabled")
            sc.say("سطر ترجمة مباشر", force=True)
            self._spin(3.0)
            self.assertTrue(
                records and "سطر ترجمة مباشر" in records,
                f"forced subtitle line not spoken: {records}",
            )
        finally:
            nvda_bridge.speak_text = orig  # type: ignore[assignment]
            sc.shutdown()

    def _spin(self, seconds: float) -> None:
        import time

        time.sleep(seconds)


if __name__ == "__main__":
    unittest.main()