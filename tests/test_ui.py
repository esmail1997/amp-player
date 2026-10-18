"""اختبار تكامل للواجهة الرسومية (يعمل في وضع offscreen)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ampplayer import config, i18n  # noqa: E402
from ampplayer.subtitle_engine import SubtitleEngine  # noqa: E402

SRT = """1
00:00:01,000 --> 00:00:03,500
مرحبا بالعالم

2
00:00:04,000 --> 00:00:06,000
Hello World

3
00:00:07,000 --> 00:00:09,000
السطر الثالث
"""

_app: QApplication | None = None


def get_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([sys.argv[0]])
    return _app


class TestEngine(unittest.TestCase):
    def setUp(self):
        get_app()
        self.d = tempfile.TemporaryDirectory()
        self.p = Path(self.d.name) / "test.srt"
        self.p.write_text(SRT, encoding="utf-8")
        self.engine = SubtitleEngine()

    def tearDown(self):
        self.d.cleanup()

    def test_load(self):
        ok, n, err = self.engine.load_file(self.p)
        self.assertTrue(ok, err)
        self.assertEqual(n, 3)

    def test_sync(self):
        self.engine.load_file(self.p)
        self.assertIsNone(self.engine.update(0))
        c = self.engine.update(2000)
        self.assertIsNotNone(c)
        self.assertEqual(c.index, 1)
        self.assertEqual(self.engine.update(5000).index, 2)
        self.assertIsNone(self.engine.update(6500))

    def test_announce_dedup(self):
        self.engine.load_file(self.p)
        c1 = self.engine.update(2000)
        self.assertTrue(self.engine.should_announce(c1))
        self.engine.mark_announced(c1)
        self.assertFalse(self.engine.should_announce(c1))
        c2 = self.engine.update(5000)
        self.assertTrue(self.engine.should_announce(c2))

    def test_rewind_reannounce(self):
        self.engine.load_file(self.p)
        self.engine.update(8000)
        self.engine.mark_announced(self.engine.current_cue())
        self.engine.update(2000)   # قفزة للخلف
        self.assertTrue(self.engine.should_announce(self.engine.current_cue()))

    def test_offset(self):
        self.engine.load_file(self.p)
        self.engine.set_offset_seconds(1.0)
        self.assertEqual(self.engine.get_offset_seconds(), 1.0)
        # بإزاحة ثانية واحدة، عند 2s نحن فعلياً في 1s
        self.assertEqual(self.engine.update(2000).index, 1)
        self.engine.reset_offset()

    def test_navigation(self):
        self.engine.load_file(self.p)
        self.engine.update(2000)
        self.assertEqual(self.engine.next_cue().index, 2)
        self.assertEqual(self.engine.prev_cue(), None)
        self.engine.update(8000)
        self.assertEqual(self.engine.prev_cue().index, 2)

    def test_export(self):
        self.engine.load_file(self.p)
        self.assertIn("00:00:01,000", self.engine.export_srt())
        self.engine.append_log("سطر أول")
        self.assertIn("سطر أول", self.engine.log_text())


class TestMainWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = get_app()

    def setUp(self):
        from ampplayer.ui.main_window import MainWindow

        self.cfg = config.Config()
        self.win = MainWindow()
        # نعرض النافذة حتى تعكس العناصر حالة الرؤية بشكل صحيح
        self.win.show()
        self.app.processEvents()

    def tearDown(self):
        try:
            self.win.sync_timer.stop()
            self.win.ui_timer.stop()
            self.win.speech.shutdown()
            self.win.player.release()
            self.win.close()
        except Exception:
            pass

    def test_builds(self):
        self.assertTrue(self.win.centralWidget() is not None)
        self.assertTrue(self.win.menuBar() is not None)

    def test_grab_frame_handles_slot_view(self):
        """الشاشة السوداء: منظر المخزن (rgb0) غير متصل بسبب قناة ألفا.

        مخزن المحرك أربعة بايتات للبكسل، وقد كان تمريره إلى QImage كما هو
        يُرفض (BufferError) فتبقى الصورة سوداء. نتحقق أن _grab_frame ينسخه
        نسخاً محكماً فيُنتج صورة صحيحة الألوان عبر مخزن المحرك الحقيقي.
        """
        from PySide6.QtGui import QImage

        from ampplayer import mpv_engine

        player = self.win.player
        w, h = 160, 90
        slot = mpv_engine._Slot(h * w * 4 + 64, w, h)
        self.assertFalse(
            slot.rgb.flags["C_CONTIGUOUS"], "منظر المخزن يجب أن يكون غير متصل"
        )
        slot.rgb[0, 0] = (10, 20, 30)

        grabbed: list = []
        player.set_frame_sink(lambda img: grabbed.append(img))
        with player._frame_lock:
            player._frame_arr = slot.rgb
            player._frame_size = (w, h)
        player._grab_frame()

        self.assertTrue(grabbed, "_grab_frame لم يُنتج أي صورة (شاشة سوداء)")
        img = grabbed[0]
        self.assertFalse(img.isNull())
        self.assertEqual((img.width(), img.height()), (w, h))
        self.assertEqual(
            tuple(QImage.pixelColor(img, 0, 0).getRgb()[:3]), (10, 20, 30)
        )

    def test_slot_supports_non_multiple_of_16_width(self):
        """عرض غير مضاعف لـ16 كان يفشل reshape فيه فيتوقف الرسم."""
        from ampplayer import mpv_engine

        for w in (1265, 1231, 7, 999):
            slot = mpv_engine._Slot(w * 4 * 3 + 64, w, 3)
            self.assertEqual(slot.rgb.shape, (3, w, 3))
            self.assertEqual(slot.stride, w * 4)

    def test_all_actions_have_text(self):
        for key, act in self.win._act.items():
            self.assertTrue(act.text().strip(), f"action {key} has empty text")

    def test_no_two_menu_actions_share_a_label(self):
        """
        تسميات مكرّرة تربك قارئ الشاشة (يسمع نفس الاسم لإمرين مختلفين).
        """
        seen: dict[str, str] = {}
        for key, act in self.win._act.items():
            text = act.text().strip()
            if not text:
                continue
            self.assertNotIn(
                text, seen, f"actions {seen.get(text)} and {key} share label {text!r}"
            )
            seen[text] = key

    def test_subtitle_offset_reset_label_mentions_subtitle(self):
        """
        إجراء إعادة ضبط توقيت الترجمة كان يستخدم نص «إعادة السرعة الطبيعية».
        """
        act = self.win._act["sub_offset_reset"]
        try:
            self.win.tr.set_language("ar")
            self.win._apply_language()
            self.assertIn("ترجم", act.text())
            self.win.tr.set_language("en")
            self.win._apply_language()
            self.assertIn("subtitle", act.text().lower())
        finally:
            self.win.tr.set_language("ar")
            self.win._apply_language()

    def test_accessible_names(self):
        for name in ("btn_play", "btn_stop", "btn_open", "btn_next", "btn_prev"):
            btn = getattr(self.win, name)
            self.assertTrue(btn.accessibleName().strip(),
                            f"{name} missing accessible name")

    def test_rtl_switch(self):
        self.win._apply_language()
        self.assertEqual(
            self.win.layoutDirection(), Qt.LayoutDirection.RightToLeft
        )
        self.win.tr.set_language("en")
        self.win._apply_language()
        self.assertEqual(self.win.layoutDirection(), Qt.LayoutDirection.LeftToRight)
        self.win.tr.set_language("ar")

    def test_open_and_playlist(self):
        with tempfile.TemporaryDirectory() as d:
            # نستخدم ملف فيديو وهمي؛ سنتحقق من إضافة القائمة فقط
            f = Path(d) / "movie.mkv"
            f.write_bytes(b"\0")
            self.win.open_paths([str(f)], play_first=False)
            self.assertEqual(len(self.win.playlist), 1)
            self.assertEqual(self.win.playlist_list.count(), 1)
            self.assertTrue(self.win.playlist_list.item(0).text().startswith("1."))
            self.win._clear_playlist()
            self.assertEqual(len(self.win.playlist), 0)

    def test_seek_slider_labels(self):
        self.win._on_ui_tick()
        self.assertIn("/", self.win.lbl_time.text())
        self.assertTrue(self.win.lbl_time.accessibleDescription())

    def test_subtitle_load_updates_readout(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.srt"
            p.write_text(SRT, encoding="utf-8")
            self.assertTrue(self.win.load_subtitle_path(str(p)))
            self.assertEqual(self.win.engine.count(), 3)
            self.win.engine.update(2000)
            self.app.processEvents()
            self.assertIn("مرحبا", self.win.readout.current_label.text())

    def test_playlist_dock_accessible(self):
        self.assertTrue(self.win.playlist_list.accessibleName())

    def test_live_region_announce(self):
        self.win.live_region.announce("اختبار")
        self.assertEqual(self.win.live_region.text(), "اختبار")

    def test_toggle_playlist(self):
        before = self.win.playlist_dock.isVisible()
        self.win._toggle_playlist()
        self.assertNotEqual(self.win.playlist_dock.isVisible(), before)
        self.win._toggle_playlist()


class TestDialogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = get_app()

    def _parent(self):
        from ampplayer.ui.main_window import MainWindow

        if not hasattr(self, "_w"):
            self._w = MainWindow()
        return self._w

    def test_shortcuts_dialog(self):
        from ampplayer.ui.shortcuts_dialog import ShortcutsDialog

        dlg = ShortcutsDialog(self._parent(), i18n.tr)
        self.assertTrue(dlg.windowTitle())
        dlg.close()

    def test_requirements_dialog(self):
        from ampplayer.ui.requirements_dialog import RequirementsDialog

        dlg = RequirementsDialog(self._parent(), i18n.tr, config.Config())
        self.assertTrue(dlg.lbl_summary.text())
        dlg.close()

    def test_merge_dialog(self):
        from ampplayer.ui.merge_dialog import MergeDialog

        dlg = MergeDialog(self._parent(), i18n.tr, config.Config(), "")
        self.assertTrue(dlg.ed_video.text() == "")
        dlg.close()

    def test_search_dialog(self):
        from ampplayer.ui.search_dialog import SubtitleSearchDialog

        dlg = SubtitleSearchDialog(self._parent(), i18n.tr, config.Config())
        self.assertTrue(dlg.windowTitle())
        self.assertGreater(dlg.cb_lang.count(), 10)
        dlg.close()

    def test_prefs_dialog(self):
        from ampplayer.ui.prefs_dialog import PreferencesDialog

        dlg = PreferencesDialog(self._parent(), i18n.tr, config.Config())
        self.assertTrue(dlg.sp_size.value() > 0)
        dlg.close()

    def test_onboarding(self):
        from ampplayer.ui.onboarding import OnboardingDialog

        dlg = OnboardingDialog(self._parent(), i18n.tr)
        self.assertTrue(dlg.btn_start.text())
        dlg.close()


class TestI18n(unittest.TestCase):
    def test_all_keys_both_langs(self):
        from ampplayer import i18n as I

        for lang in ("ar", "en"):
            t = I.Translator(lang)
            for key in I._STRINGS:
                val = t(key)
                self.assertTrue(val, f"{key} empty in {lang}")
                self.assertNotEqual(val, key, f"{key} missing in {lang}")

    def test_formatting(self):
        t = i18n.Translator("en")
        self.assertIn("/path", t("merge.done", path="/path"))

    def test_rtl_flag(self):
        self.assertTrue(i18n.Translator("ar").is_rtl())
        self.assertFalse(i18n.Translator("en").is_rtl())

    def test_fallback_language(self):
        self.assertEqual(i18n.Translator("fr").language, "ar")

    def test_used_keys_exist(self):
        """كل مفتاح مستخدم في الكود يجب أن يكون موجوداً في القاموس."""
        import re
        from pathlib import Path as P

        used = set()
        base = P(__file__).resolve().parent.parent / "ampplayer"
        # نتجاهل المفاتيح المبنية بالدمج مثل tr("shortcuts." + name)
        pattern = re.compile(
            r'''(?:tr\(|self\.tr\()\s*\(?\s*["']([a-z][a-z0-9_.]*)["'](?!\s*\+)'''
        )
        for f in base.rglob("*.py"):
            for m in pattern.finditer(f.read_text(encoding="utf-8")):
                used.add(m.group(1))
        from ampplayer import i18n as I

        missing = sorted(k for k in used if k not in I._STRINGS)
        self.assertEqual(missing, [], f"missing i18n keys: {missing}")


class TestMerger(unittest.TestCase):
    def test_default_output_path(self):
        from ampplayer.subtitle_merger import default_output_path

        out = default_output_path("C:/m/My Movie.mkv", "C:/m/s.srt")
        self.assertEqual(out.suffix, ".mkv")
        self.assertIn("Amp-sub", out.name)
        self.assertNotEqual(out.name, "My Movie.mkv")

    def test_detect_lang(self):
        from ampplayer.subtitle_merger import detect_lang

        self.assertEqual(detect_lang("Movie.ara.srt"), "ara")
        self.assertEqual(detect_lang("Movie.english.srt"), "eng")
        self.assertEqual(detect_lang("random.srt"), "und")

    def test_command_contains_maps(self):
        from ampplayer.subtitle_merger import build_command

        cmd = build_command("v.mkv", "s.srt", "o.mkv")
        joined = " ".join(cmd)
        self.assertIn("-i", cmd)
        self.assertIn("-map 1:0", joined)
        self.assertIn("srt", joined)
        self.assertIn("copy", joined)

    def test_mp4_uses_mov_text(self):
        from ampplayer.subtitle_merger import build_command

        cmd = build_command("v.mp4", "s.srt", "o.mp4")
        self.assertIn("mov_text", cmd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
