"""اختبارات الترجمة الخارجية والبعيدة، سياسة النطق، يوتيوب، والتواصل.

كل هذه الاختبارات تعمل بلا أي أداة خارجية؛ يُتخطّى اختبار غياب yt-dlp
إذا كان مثبتاً في بيئة الاختبار.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ampplayer import subtitle_manager, subtitle_text, youtube_subs, contact  # noqa: E402
from ampplayer.subtitle_manager import SourceKind, SpeakPolicy, SubtitleManager  # noqa: E402
from ampplayer.subtitle_parser import Cue  # noqa: E402
from ampplayer import embedded_subs  # noqa: E402


# ====================================================================== النص
class TestSubtitleText(unittest.TestCase):
    def test_strip_ass_tags(self):
        raw = r"{\an8}{\pos(10,20)}مرحبا {\i1}بالعالم{\i0}"
        self.assertEqual(subtitle_text.clean_subtitle_text(raw), "مرحبا بالعالم")

    def test_strip_html_and_entities(self):
        raw = "<i>Hello</i> &amp; <b>World</b>&nbsp;!"
        self.assertEqual(subtitle_text.clean_subtitle_text(raw), "Hello & World !")

    def test_break_conversion(self):
        self.assertEqual(subtitle_text.split_lines(r"سطر1\Nسطر2\nسطر3"),
                         ["سطر1", "سطر2", "سطر3"])
        self.assertEqual(subtitle_text.merge_lines(r"سطر1\Nسطر2"), "سطر1 سطر2")

    def test_dedup_key_ignores_arabic_diacritics(self):
        a = subtitle_text.dedup_key("مَرْحَبًا بِالعَالَم")
        b = subtitle_text.dedup_key("مرحبا بالعالم!")
        self.assertEqual(a, b)

    def test_dedup_key_unifies_alef_and_taa(self):
        self.assertEqual(subtitle_text.dedup_key("أحمد"),
                         subtitle_text.dedup_key("احمد"))
        self.assertEqual(subtitle_text.dedup_key("مدرسة"),
                         subtitle_text.dedup_key("مدرسه"))

    def test_is_similar_tolerates_small_text_variations(self):
        self.assertTrue(subtitle_text.is_similar("Hello World", "He1lo W0rld"))
        self.assertFalse(subtitle_text.is_similar("Hello World", "Goodbye Moon"))

    def test_is_similar_empty(self):
        self.assertTrue(subtitle_text.is_similar("", ""))
        self.assertFalse(subtitle_text.is_similar("a", ""))


# ====================================================================== المصادر
class TestSubtitleManager(unittest.TestCase):
    def test_auto_prefers_external_over_remote(self):
        m = SubtitleManager("auto")
        m.set_source(SourceKind.EXTERNAL, True)
        m.set_source(SourceKind.REMOTE, True)
        self.assertEqual(m.active_kind(), SourceKind.EXTERNAL)

    def test_auto_skips_unavailable(self):
        m = SubtitleManager("auto")
        m.set_source(SourceKind.EXTERNAL, False)
        m.set_source(SourceKind.REMOTE, True)
        self.assertEqual(m.active_kind(), SourceKind.REMOTE)

    def test_auto_prefers_embedded_over_remote(self):
        m = SubtitleManager("auto")
        m.set_source(SourceKind.REMOTE, True)
        m.set_source(SourceKind.EMBEDDED, True)
        self.assertEqual(m.active_kind(), SourceKind.EMBEDDED)

    def test_auto_prefers_external_over_embedded(self):
        m = SubtitleManager("auto")
        m.set_source(SourceKind.EMBEDDED, True)
        m.set_source(SourceKind.EXTERNAL, True)
        self.assertEqual(m.active_kind(), SourceKind.EXTERNAL)

    def test_priority_order_is_external_embedded_remote(self):
        self.assertEqual(
            subtitle_manager.PRIORITY,
            [SourceKind.EXTERNAL, SourceKind.EMBEDDED, SourceKind.REMOTE],
        )

    def test_label_key_covers_every_kind(self):
        from ampplayer import i18n

        self.assertEqual(set(subtitle_manager.LABEL_KEY), set(SourceKind))
        for key in subtitle_manager.LABEL_KEY.values():
            self.assertIn(key, i18n._STRINGS)

    def test_manual_selection(self):
        m = SubtitleManager("auto")
        m.set_source(SourceKind.EXTERNAL, True)
        m.select(SourceKind.EXTERNAL)
        self.assertEqual(m.mode, "manual")
        self.assertEqual(m.active_kind(), SourceKind.EXTERNAL)
        # مصدر غير متاح يدوياً => لا شيء
        m.set_source(SourceKind.EXTERNAL, False)
        self.assertIsNone(m.active_kind())

    def test_no_source(self):
        m = SubtitleManager()
        self.assertIsNone(m.active_kind())
        self.assertEqual(m.available_sources(), [])


class TestSpeakPolicy(unittest.TestCase):
    def test_dedup_exact(self):
        p = SpeakPolicy()
        self.assertEqual(p.offer("مرحبا", 1000), "مرحبا")
        self.assertIsNone(p.offer("مرحبا", 1100))

    def test_dedup_diacritics(self):
        p = SpeakPolicy()
        self.assertEqual(p.offer("مَرْحَبًا", 1000), "مَرْحَبًا")
        self.assertIsNone(p.offer("مرحبا", 2000))

    def test_similar_text_variations_suppressed(self):
        p = SpeakPolicy()
        self.assertEqual(p.offer("Hello World", 1000), "Hello World")
        self.assertIsNone(p.offer("He1lo W0rld", 2000))

    def test_new_line_speaks(self):
        p = SpeakPolicy()
        self.assertEqual(p.offer("one", 0), "one")
        self.assertEqual(p.offer("two", 1000), "two")

    def test_empty_ignored(self):
        p = SpeakPolicy()
        self.assertIsNone(p.offer("", 0))
        self.assertIsNone(p.offer("   ", 0))

    def test_stats_and_reset(self):
        p = SpeakPolicy()
        p.offer("abc", 0)
        p.offer("de", 10)
        self.assertEqual(p.lines_spoken, 2)
        self.assertEqual(p.chars_spoken, 5)
        p.reset()
        self.assertEqual(p.offer("abc", 20), "abc")


# ====================================================================== يوتيوب
class TestYoutubeSubs(unittest.TestCase):
    def test_available_returns_tuple(self):
        ok, backend, detail = youtube_subs.ytdlp_available()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(backend, str)
        self.assertIn(backend, ("yt-dlp-module", "yt-dlp-exe", "none"))

    def test_normalize_langs(self):
        self.assertEqual(youtube_subs.normalize_langs("ara+eng"), ["ar", "en"])
        self.assertEqual(youtube_subs.normalize_langs("ar,en"), ["ar", "en"])
        self.assertEqual(youtube_subs.normalize_langs(""), ["ar", "en"])
        self.assertEqual(youtube_subs.normalize_langs("fr"), ["fr"])

    def test_fetch_missing_backend_message(self):
        if youtube_subs.ytdlp_available()[0]:
            self.skipTest("yt-dlp مثبت: لا يمكن اختبار مسار الغياب")
        ok, files, key, _ = youtube_subs.fetch_subtitles(
            "https://example.invalid/x", ["ar"], Path(tempfile.gettempdir())
        )
        self.assertFalse(ok)
        self.assertEqual(files, [])
        self.assertEqual(key, "ytdlp.missing")


# ====================================================================== التواصل
class TestContact(unittest.TestCase):
    def test_contact_text_has_email_and_handle(self):
        text = contact.contact_text()
        self.assertIn(contact.EMAIL, text)
        self.assertIn(contact.TWITTER_HANDLE, text)

    def test_mailto(self):
        self.assertTrue(contact.mailto_url().startswith("mailto:"))
        self.assertIn(contact.EMAIL, contact.mailto_url())


class _FakeSpeech:
    available = True

    def __init__(self):
        self.said = []

    def say(self, text, force=False):
        self.said.append(text)

    def stop(self):
        pass

    def is_busy(self):
        return False


class TestUiSourceWiring(unittest.TestCase):
    """تكامل مدير المصادر مع النافذة (offscreen، بلا صوت حقيقي)."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([sys.argv[0]])

    def setUp(self):
        from ampplayer.ui.main_window import MainWindow

        self.win = MainWindow()
        self.win.sync_timer.stop()
        self.win.ui_timer.stop()
        # الإعدادات مشتركة بين الاختبارات: نبدأ كل اختبار في الوضع التلقائي
        self.win.cfg.set("sub_source_mode", "auto")
        self.win.sub_mgr.set_mode("auto")
        self.win.sub_mgr.select(None)

    def tearDown(self):
        try:
            self.win.cfg.set("sub_source_mode", "auto")
            self.win.cfg.sync()
        except Exception:
            pass
        try:
            self.win.speech.shutdown()
            self.win.player.release()
            self.win.close()
        except Exception:
            pass

    def _set_embedded(self, cues=True):
        self.win._emb_tracks = [embedded_subs.EmbeddedTrack(2, "subrip", "ara")]
        self.win._emb_selected_index = 2
        self.win._emb_name = "فيلم [مدمج]"
        self.win._emb_cues = [Cue(1, 0, 1000, "مدمج")] if cues else []

    def test_external_wins_over_embedded(self):
        self.win._text_cues = [Cue(0, 0, 1000, "سطر خارجي")]
        self.win._text_origin = SourceKind.EXTERNAL
        self.win._sidecar_loaded = True
        self._set_embedded()
        self.win._update_source_availability()
        self.assertEqual(self.win.sub_mgr.active_kind(), SourceKind.EXTERNAL)
        self.assertEqual(
            [source.kind for source in self.win.sub_mgr.available_sources()],
            [SourceKind.EXTERNAL, SourceKind.EMBEDDED],
        )

    def test_embedded_is_read_when_no_external(self):
        self._set_embedded()
        self.win._update_source_availability()
        self.assertEqual(self.win.sub_mgr.active_kind(), SourceKind.EMBEDDED)
        self.win._sync_active_source(force=True)
        self.assertEqual([c.text for c in self.win.engine.cues], ["مدمج"])
        # المصدر المدمج يحمل وصف المسار في قائمة المصادر
        labels = [a.text() for a in self.win._menus["source"].actions()]
        self.assertTrue(any("●" in l and "1." in l for l in labels))

    def test_embedded_available_before_cues_extracted(self):
        """على mpv يُقرأ النص الحي فور اكتشاف المسار، قبل انتهاء الاستخراج."""
        self._set_embedded(cues=False)
        self.win._update_source_availability()
        self.assertEqual(self.win.sub_mgr.active_kind(), SourceKind.EMBEDDED)
        self.win._sync_active_source(force=True)
        self.assertEqual(self.win.engine.cues, [])

    def test_sync_tick_speaks_embedded_without_live_text(self):
        """مسار محرك PyAV: لا نص حي، فتُقرأ الأسطر المستخرجة مرة واحدة."""
        self._set_embedded()
        self.win._update_source_availability()
        self.win._sync_active_source(force=True)
        self.win.cfg.set("tts_announce_subtitle", True)
        self.win.speech = _FakeSpeech()
        self.win.player.get_time = lambda: 500
        self.win.player.current_subtitle_text = lambda: ""
        self.win._on_sync_tick()
        self.win._on_sync_tick()
        self.assertEqual(self.win.speech.said, ["مدمج"])

    def test_switching_to_external_reloads_engine(self):
        self._set_embedded()
        self.win._update_source_availability()
        self.win._sync_active_source(force=True)
        self.assertEqual(self.win.engine.source_name, "فيلم [مدمج]")
        self.win._text_cues = [Cue(0, 0, 1000, "خارجي")]
        self.win._text_name = "ext"
        self.win._text_origin = SourceKind.EXTERNAL
        self.win._sidecar_loaded = True
        self.win._update_source_availability()
        self.win._sync_active_source()
        self.assertEqual(self.win.engine.source_name, "ext")
        # اختيار المدمج يدوياً يعيد أسطره
        self.win._select_source(SourceKind.EMBEDDED)
        self.assertEqual(self.win.engine.source_name, "فيلم [مدمج]")

    def test_embedded_menu_lists_tracks(self):
        self.win._emb_tracks = [
            embedded_subs.EmbeddedTrack(2, "subrip", "ara"),
            embedded_subs.EmbeddedTrack(3, "hdmv_pgs_subtitle", "eng"),
        ]
        self.win._emb_selected_index = 2
        self.win._emb_auto = False
        self.win._update_embedded_menu()
        acts = [a for a in self.win._menus["emb_tracks"].actions() if a.text()]
        self.assertEqual(len(acts), 3)          # تلقائي + مساران
        self.assertFalse(acts[0].isChecked())   # تلقائي غير محدد
        self.assertTrue(acts[1].isChecked())
        self.assertFalse(acts[2].isEnabled())   # الصوري معطّل
        self.assertIn("1.", acts[1].text())

    def test_embedded_menu_empty_state(self):
        self.win._emb_tracks = []
        self.win._update_embedded_menu()
        acts = self.win._menus["emb_tracks"].actions()
        self.assertEqual(len(acts), 1)
        self.assertFalse(acts[0].isEnabled())

    def test_reset_embedded_state(self):
        self._set_embedded()
        self.win._update_source_availability()
        self.win._reset_embedded_state()
        self.win._update_source_availability()
        self.assertIsNone(self.win._emb_selected_index)
        self.assertEqual(self.win._emb_cues, [])
        self.assertNotIn(SourceKind.EMBEDDED,
                         [s.kind for s in self.win.sub_mgr.available_sources()])

    def test_manual_source_selection(self):
        self.win._text_cues = [Cue(0, 0, 1000, "سطر خارجي")]
        self.win._text_origin = SourceKind.EXTERNAL
        self.win._sidecar_loaded = True
        self.win._update_source_availability()
        self.win._select_source(SourceKind.EXTERNAL)
        self.assertEqual(self.win.sub_mgr.mode, "manual")
        self.assertEqual(self.win.sub_mgr.active_kind(), SourceKind.EXTERNAL)
        self.assertEqual(self.win.cfg.get("sub_source_mode"), "manual")

    def test_source_menu_built(self):
        self.win._text_cues = [Cue(0, 0, 1000, "سطر خارجي")]
        self.win._text_origin = SourceKind.EXTERNAL
        self.win._sidecar_loaded = True
        self.win._update_source_availability()
        menu = self.win._menus["source"]
        labels = [a.text() for a in menu.actions()]
        self.assertTrue(any("●" in l for l in labels))

    def test_sync_tick_speaks_once(self):
        cue = Cue(0, 1000, 3000, "مرحبا بالعالم")
        self.win.engine.load_cues([cue], name="t")
        self.win._text_cues = [cue]
        self.win._text_name = "t"
        self.win._text_origin = SourceKind.EXTERNAL
        self.win._sidecar_loaded = True
        self.win.sub_mgr.set_source(SourceKind.EXTERNAL, True)
        self.win.sub_mgr.set_mode("auto")
        self.win.cfg.set("tts_announce_subtitle", True)
        self.win.speech = _FakeSpeech()
        self.win.player.get_time = lambda: 2000
        self.win.player.current_subtitle_text = lambda: ""
        self.win._on_sync_tick()
        self.win._on_sync_tick()
        self.assertEqual(self.win.speech.said, ["مرحبا بالعالم"])
        # إعادة النطق اليدوي تعمل رغم منع التكرار التلقائي
        self.win._read_last_aloud()
        self.assertEqual(self.win.speech.said[-1], "مرحبا بالعالم")

    def test_live_subtitle_from_mpv_dedup(self):
        self.win.engine.unload()
        self.win._text_cues = []
        self.win._text_origin = SourceKind.EXTERNAL
        self.win._sidecar_loaded = True
        self.win.sub_mgr.clear()
        self.win.sub_mgr.set_mode("auto")
        self.win.sub_mgr.set_source(SourceKind.EXTERNAL, True)
        self.win.cfg.set("tts_announce_subtitle", True)
        self.win.speech = _FakeSpeech()
        self.win.player.get_time = lambda: 5000
        self.win.player.current_subtitle_text = lambda: r"{\an8}Hello {\i1}World"
        self.win._on_sync_tick()
        self.win._on_sync_tick()
        self.assertEqual(self.win.speech.said, ["Hello World"])


class TestAboutDialog(unittest.TestCase):
    """نافذة «حول»: تحقّق من أن الزر يعمل فعلاً (كان يرفع ImportError)."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([sys.argv[0]])

    def test_qt_version_resolves(self):
        from ampplayer.ui.about_dialog import qt_version_str

        v = qt_version_str()
        self.assertTrue(v)
        self.assertRegex(v, r"^\d+\.\d+")

    def test_open_about_does_not_raise(self):
        from PySide6.QtCore import QTimer

        from ampplayer.ui.main_window import MainWindow

        win = MainWindow()
        try:
            QTimer.singleShot(200, lambda: (
                self.app.activeModalWidget().accept()
                if self.app.activeModalWidget() else None))
            win.open_about()  # نافذة مستقرّة تُغلقها المؤقّت
        finally:
            try:
                win.sync_timer.stop()
                win.ui_timer.stop()
                win.speech.shutdown()
                win.player.release()
                win.close()
            except Exception:
                pass

    def test_dialog_exposes_contact_controls(self):
        from ampplayer import i18n
        from ampplayer.ui.about_dialog import AboutDialog, build_info_html

        tr = i18n.Translator("ar")
        html = build_info_html(tr, version="1.0.0", engine_line="x",
                               ffmpeg_ok=True, qt_version="6.11.2")
        dlg = AboutDialog(None, tr, html)
        self.assertTrue(dlg.browser.toPlainText().strip())
        self.assertEqual(dlg.btn_email.accessibleDescription(), contact.EMAIL)
        self.assertIn(contact.TWITTER_HANDLE,
                      dlg.btn_twitter.accessibleDescription())
        self.assertIn(contact.EMAIL, dlg.contact_view.accessibleDescription())


class TestPrefsSubtitleOptions(unittest.TestCase):
    """تبقى خيارات ملفات الترجمة الخارجية متاحة في التفضيلات."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([sys.argv[0]])

    def test_build_and_apply(self):
        from PySide6.QtWidgets import QWidget

        from ampplayer import config, i18n
        from ampplayer.ui.prefs_dialog import PreferencesDialog

        cfg = config.Config()
        parent = QWidget()
        dlg = PreferencesDialog(parent, i18n.Translator("ar"), cfg)
        self.assertTrue(hasattr(dlg, "chk_sidecar"))
        self.assertFalse(hasattr(dlg, "chk_ocr"))
        dlg._apply()
        self.assertIsInstance(cfg.get("sub_auto_load_sidecar"), bool)


class TestAboutHtml(unittest.TestCase):
    def test_build_info_html_contains_keys(self):
        from ampplayer import i18n
        from ampplayer.ui.about_dialog import build_info_html

        tr = i18n.Translator("ar")
        html = build_info_html(tr, version="1.0.0", engine_line="libmpv OK",
                               ffmpeg_ok=True, qt_version="6.11.2")
        self.assertIn("1.0.0", html)
        self.assertIn("libmpv OK", html)
        self.assertIn("6.11.2", html)
        self.assertIn("الترجمة الخارجية", html)


if __name__ == "__main__":
    unittest.main()
