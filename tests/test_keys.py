"""اختبارات لوحة المفاتيح والوصولية في النافذة الرئيسية."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app: QApplication | None = None


def get_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([sys.argv[0]])
    return _app


class TestKeyboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = get_app()

    def setUp(self):
        from ampplayer.ui.main_window import MainWindow

        self.win = MainWindow()
        self.win.show()
        self.app.processEvents()

    def tearDown(self):
        try:
            self.win.close()
        except Exception:
            pass

    def _all_actions(self):
        """كل إجراءات النافذة بما فيها قوائم شريط القوائم."""
        out = list(self.win.actions())
        for menu_act in self.win.menuBar().actions():
            menu = menu_act.menu()
            if menu is None:
                continue
            for a in menu.actions():
                out.append(a)
                sub = a.menu()
                if sub is not None:
                    out.extend(sub.actions())
        return out

    def _action_for(self, key: str):
        want = QKeySequence(key).toString()
        for a in self._all_actions():
            if a.shortcut().toString() == want:
                return a
        return None

    def test_documented_shortcuts_exist(self):
        """كل اختصار معلن في نافذة الاختصارات يجب أن يكون مربوطاً فعلاً."""
        from ampplayer.ui.shortcuts_dialog import SHORTCUTS

        missing = []
        for items in SHORTCUTS.values():
            for keys, _label in items:
                if self._action_for(keys) is None:
                    missing.append(keys)
        self.assertEqual(missing, [], f"shortcuts with no handler: {missing}")

    def test_no_duplicate_shortcuts(self):
        """
        Qt يُعطّل الاختصارات المكرّرة على مستوى النافذة، فيلتفت الاختصار
        إلى زره. نتحقق أن كل اختصار مربوط مرة واحدة فقط.
        """
        seen: dict[str, int] = {}
        for a in self._all_actions():
            s = a.shortcut().toString()
            if s:
                seen[s] = seen.get(s, 0) + 1
        dupes = sorted(k for k, n in seen.items() if n > 1)
        self.assertEqual(dupes, [], f"duplicate shortcuts: {dupes}")

    def test_seek_does_nothing_without_media(self):
        # لا يوجد ملف مفتوح: يجب ألا يرمي استثناء
        self.win._seek(10000)
        self.win._seek(-10000)

    def test_rate_changes_label(self):
        self.win._nudge_rate(0.25)
        self.assertEqual(self.win.player.get_rate(), 1.25)
        self.assertIn("1.25", self.win.lbl_speed.text())
        self.win._reset_rate()
        self.assertEqual(self.win.player.get_rate(), 1.0)
        self.assertIn("1.00", self.win.lbl_speed.text())

    def test_rate_is_clamped(self):
        self.win._set_rate(99.0)
        self.assertLessEqual(self.win.player.get_rate(), 4.0)
        self.win._set_rate(0.01)
        self.assertGreaterEqual(self.win.player.get_rate(), 0.25)
        self.win._reset_rate()

    def test_volume_clamped_and_announced(self):
        self.win._nudge_volume(10)
        self.assertEqual(self.win.player.get_volume(), 110)
        self.assertIn("110", self.win.volume.accessibleDescription())
        self.win._on_volume(500)
        self.assertEqual(self.win.player.get_volume(), 200)
        self.win._on_volume(-50)
        self.assertEqual(self.win.player.get_volume(), 0)
        self.win._on_volume(100)

    def test_mute_toggle(self):
        self.assertFalse(self.win.player.is_muted())
        self.win._toggle_mute()
        self.assertTrue(self.win.player.is_muted())
        self.win._toggle_mute()
        self.assertFalse(self.win.player.is_muted())

    def test_unmuting_when_volume_raised(self):
        self.win.player.set_muted(True)
        self.win._on_volume(120)
        self.assertFalse(self.win.player.is_muted())

    def test_subtitle_shift_updates_engine_and_player(self):
        from tests.test_ui import SRT

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.srt"
            p.write_text(SRT, encoding="utf-8")
            self.win.load_subtitle_path(str(p))

            self.win._shift_subtitle(0.5)
            self.assertAlmostEqual(self.win.engine.get_offset_seconds(), 0.5, places=3)
            self.assertEqual(self.win.player.get_sub_delay(), 500_000)
            self.win._shift_subtitle(-1.0)
            self.assertAlmostEqual(self.win.engine.get_offset_seconds(), -0.5, places=3)
            self.win.reset_sub_offset()
            self.assertEqual(self.win.engine.get_offset_seconds(), 0.0)
            self.assertEqual(self.win.player.get_sub_delay(), 0)

    def test_player_sub_scale_is_remembered(self):
        self.win.player.set_sub_text_scale(150)
        self.assertEqual(self.win.player.get_sub_text_scale(), 150)
        self.win.player.set_sub_text_scale(5000)
        self.assertEqual(self.win.player.get_sub_text_scale(), 500)

    def test_live_region_in_layout(self):
        """المنطقة الحيّة يجب أن تكون ضمن تخطيط النافذة ليقرأها NVDA."""
        found = False
        for w in self.win.centralWidget().findChildren(type(self.win.live_region)):
            found = True
            break
        self.assertTrue(found)
        self.win.live_region.announce("اختبار")
        self.assertEqual(self.win.live_region.text(), "اختبار")

    def test_live_region_dedup_still_speaks(self):
        self.win.live_region.announce("نفس النص")
        first = self.win.live_region._label.text()
        self.win.live_region.announce("نفس النص")
        self.assertNotEqual(first, self.win.live_region._label.text())
        self.assertEqual(self.win.live_region.text(), "نفس النص")

    def test_media_filter_matches_folder_scan(self):
        from ampplayer.ui.main_window import MEDIA_EXTENSIONS

        exts = {e.lower().lstrip(".") for e in MEDIA_EXTENSIONS}
        self.assertIn("mkv", exts)
        self.assertIn("mp3", exts)
        self.assertIn("flac", exts)
        self.assertNotIn("srt", exts)

    def test_escape_outside_fullscreen_is_noop(self):
        self.win._escape()  # لا يوجد ملء شاشة ولا نافذة فرعية

    def test_shortcuts_dialog_lists_real_bindings(self):
        from ampplayer.ui.shortcuts_dialog import ShortcutsDialog

        dlg = ShortcutsDialog(self.win, self.win.tr)
        self.assertTrue(dlg.windowTitle())
        dlg.close()


class TestShortcutActivation(unittest.TestCase):
    """
    وجود الاختصار في جدول الواجهة لا يكفي: يجب أن يُنشئ الإجراء أثراً فعلياً
    عند الضغط على المفتاح. هذه الاختبارات تكشف الاختصارات «المربوطة على
    القوائم فقط» التي يتجاهلها Qt عند وجود نسخة مكرّرة على النافذة.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = get_app()

    def setUp(self):
        from ampplayer.ui.main_window import MainWindow

        self.win = MainWindow()
        self.win.show()
        self.app.processEvents()
        # نبدأ من لغة عربية معروفة حتى لا تتسرب حالة بين الاختبارات
        self.win.cfg.set("lang", "ar")
        self.win.cfg.sync()

    def tearDown(self):
        self.win.cfg.set("lang", "ar")
        self.win.cfg.reset()
        try:
            self.win.close()
        except Exception:
            pass

    def _press(self, key, mod=Qt.KeyboardModifier.NoModifier):
        QTest.keyClick(self.win, key, mod)
        self.app.processEvents()

    def test_m_mutes(self):
        self.assertFalse(self.win.player.is_muted())
        self._press(Qt.Key.Key_M)
        self.assertTrue(self.win.player.is_muted())
        self._press(Qt.Key.Key_M)
        self.assertFalse(self.win.player.is_muted())

    def test_equals_and_backspace_change_speed(self):
        self._press(Qt.Key.Key_Equal)
        self.assertEqual(self.win.player.get_rate(), 1.25)
        self._press(Qt.Key.Key_Minus)
        self.assertEqual(self.win.player.get_rate(), 1.0)
        self._press(Qt.Key.Key_Backspace)
        self.assertEqual(self.win.player.get_rate(), 1.0)

    def test_f9_toggles_subtitle_panel(self):
        start = self.win.readout.isVisible()
        self._press(Qt.Key.Key_F9)
        self.app.processEvents()
        self.assertNotEqual(self.win.readout.isVisible(), start)
        self._press(Qt.Key.Key_F9)
        self.app.processEvents()
        self.assertEqual(self.win.readout.isVisible(), start)

    def test_f9_matches_menu_checkbox_state(self):
        """القائمة والاختصار يجب أن يبقيا متطابقين (لا انفصال بينهما)."""
        self._press(Qt.Key.Key_F9)
        self.app.processEvents()
        self.assertEqual(
            self.win._act["show_panel"].isChecked(),
            self.win.readout.isVisible(),
        )

    def test_toggle_state_is_consistent_at_startup(self):
        """
        حالة الإجراءات القابلة للتحديد يجب أن تطابق حالة الودجت عند بدء
        التشغيل. الخطأ السابق: كان يُقرأ isVisible() قبل عرض النافذة فيُرجع
        False، فتبدأ الحالة «غير محددة» وتبتلع أول ضغطة.
        """
        for name, widget in (("show_panel", self.win.readout),
                             ("toggle_playlist", self.win.playlist_dock)):
            with self.subTest(action=name):
                self.assertEqual(
                    self.win._act[name].isChecked(), widget.isVisible(),
                    f"{name} out of sync with its widget at startup",
                )

    def test_restored_window_state_does_not_desync_menu(self):
        """
        بعد استعادة حالة نافذة مخزّنة (dock مخفي) يجب أن تعكس القائمة الواقع
        فوراً، وإلا أخطأ المستخدم في أول ضغطة على زر القائمة.
        """
        self.win.playlist_dock.setVisible(False)
        self.win._sync_toggle_states()
        self.assertFalse(self.win._act["toggle_playlist"].isChecked())

        self.win.playlist_dock.setVisible(True)
        self.win._sync_toggle_states()
        self.assertTrue(self.win._act["toggle_playlist"].isChecked())

    def test_playlist_toggle_matches_checkbox(self):
        for _ in range(3):
            start = self.win.playlist_dock.isVisible()
            self.win._toggle_playlist()
            self.app.processEvents()
            self.assertNotEqual(self.win.playlist_dock.isVisible(), start)
            self.assertEqual(
                self.win._act["toggle_playlist"].isChecked(),
                self.win.playlist_dock.isVisible(),
            )

    def test_ctrl_shift_l_switches_language(self):
        from ampplayer import i18n

        self.assertEqual(self.win.cfg.lang, i18n.AR)
        self._press(Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.win.cfg.lang, i18n.EN)
        # نعود للعربية حتى لا يتأثر بقية الاختبارات
        self._press(Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.win.cfg.lang, i18n.AR)

    def test_s_and_x_do_not_crash_without_subtitle(self):
        """S و X يعملان على مستوى النافذة حتى بلا ترجمة محمّلة."""
        self._press(Qt.Key.Key_S)
        self._press(Qt.Key.Key_X)

    def test_f1_opens_shortcuts_dialog(self):
        opened = []

        def grab():
            w = QApplication.activeModalWidget()
            if w is not None:
                opened.append(type(w).__name__)
                w.close()

        QTimer.singleShot(0, grab)
        self._press(Qt.Key.Key_F1)
        self.app.processEvents()
        self.assertEqual(opened, ["ShortcutsDialog"])

    def test_ctrl_shift_arrows_shift_subtitle(self):
        from tests.test_ui import SRT

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.srt"
            p.write_text(SRT, encoding="utf-8")
            self.win.load_subtitle_path(str(p))
            self.win.reset_sub_offset()

            self._press(Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.ShiftModifier)
            self.assertAlmostEqual(self.win.engine.get_offset_seconds(), 0.5, places=3)
            self._press(Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.ShiftModifier)
            self.assertAlmostEqual(self.win.engine.get_offset_seconds(), 0.0, places=3)

    def test_every_documented_shortcut_is_a_window_action(self):
        """
        كل اختصار معلن يجب أن يكون QAction مربوطاً على النافذة نفسها
        (لا على عنصر قائمة) حتى يعمل مع كل العناصر النشطة.
        """
        from ampplayer.ui.shortcuts_dialog import SHORTCUTS

        window_shortcuts = {
            a.shortcut().toString() for a in self.win.actions() if a.shortcut()
        }
        menu_only = []
        for items in SHORTCUTS.values():
            for keys, _label in items:
                if QKeySequence(keys).toString() not in window_shortcuts:
                    menu_only.append(keys)
        self.assertEqual(menu_only, [], f"not bound on the window: {menu_only}")


if __name__ == "__main__":
    unittest.main(verbosity=2)