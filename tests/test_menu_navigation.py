import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton
from ampplayer.ui.menu_bar import AccessibleMenuBar


class MenuNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_shortcuts_do_not_steal_menu_arrows(self):
        from ampplayer.ui.main_window import MainWindow
        window = MainWindow()
        window.show()
        self.app.processEvents()
        try:
            self.assertNotIn(window._act['prefs'], window._menus['edit'].actions())
            self.assertIn(window._act['prefs'], window._menus['tools'].actions())
            with patch.object(window, '_seek') as seek, patch.object(window, '_nudge_volume') as volume:
                bar = window.menuBar()
                window._show_main_menu()
                first = bar.activeAction()
                QTest.keyClick(bar, Qt.Key_Right)
                self.assertNotEqual(bar.activeAction(), first)
                QTest.keyClick(bar, Qt.Key_Left)
                self.assertEqual(bar.activeAction(), first)
                QTest.keyClick(bar, Qt.Key_Down)
                menu = first.menu()
                self.assertTrue(menu.isVisible())
                previous = menu.activeAction()
                QTest.keyClick(menu, Qt.Key_Down)
                self.assertNotEqual(menu.activeAction(), previous)
                QTest.keyClick(menu, Qt.Key_Up)
                self.assertEqual(menu.activeAction(), previous)
                seek.assert_not_called()
                volume.assert_not_called()
                menu.hide()
        finally:
            window.close()

    def test_arrows_open_and_navigate_without_triggering_player(self):
        for direction in (Qt.LeftToRight, Qt.RightToLeft):
            window = QMainWindow()
            bar = AccessibleMenuBar(window)
            window.setMenuBar(bar)
            button = QPushButton('Video')
            window.setCentralWidget(button)
            bar.setLayoutDirection(direction)
            menus = [bar.addMenu(name) for name in ('File', 'Edit', 'Tools')]
            for menu in menus:
                menu.addAction('First')
                menu.addSeparator()
                menu.addAction('Second')
                menu.installEventFilter(bar)
            window.show()
            button.setFocus()
            self.app.processEvents()
            bar.activate()
            self.assertEqual(bar.activeAction(), menus[0].menuAction())
            QTest.keyClick(bar, Qt.Key_Right)
            expected = menus[1] if direction == Qt.LeftToRight else menus[2]
            self.assertEqual(bar.activeAction(), expected.menuAction())
            QTest.keyClick(bar, Qt.Key_Left)
            self.assertEqual(bar.activeAction(), menus[0].menuAction())
            QTest.keyClick(bar, Qt.Key_Down)
            self.assertTrue(menus[0].isVisible())
            self.assertEqual(menus[0].activeAction(), menus[0].actions()[0])
            QTest.keyClick(menus[0], Qt.Key_Down)
            self.assertEqual(menus[0].activeAction(), menus[0].actions()[2])
            QTest.keyClick(menus[0], Qt.Key_Up)
            self.assertEqual(menus[0].activeAction(), menus[0].actions()[0])
            menus[0].hide()
            QTest.keyClick(bar, Qt.Key_Escape)
            self.assertEqual(self.app.focusWidget(), button)
            window.close()
