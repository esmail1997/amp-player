"""نافذة عرض اختصارات لوحة المفاتيح."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QLabel,
    QVBoxLayout,
)

from .. import i18n
from .widgets import a11y

SHORTCUTS = {
    "general": [
        ("Ctrl+O", "menu.open_file"),
        ("Ctrl+D", "menu.open_folder"),
        ("F10", "menu.file"),
        ("F11", "fullscreen"),
        ("F1", "menu.tips"),
        ("Ctrl+Shift+L", "prefs.language"),
        ("Esc", "close"),
    ],
    "playback": [
        ("Space", "play"),
        ("Ctrl+S", "stop"),
        ("Ctrl+PgUp", "prev"),
        ("Ctrl+PgDown", "next"),
        ("Right", "seek_forward"),
        ("Left", "seek_backward"),
        ("Shift+Right", "seek_forward_long"),
        ("Shift+Left", "seek_backward_long"),
        ("Up", "volume_up"),
        ("Down", "volume_down"),
        ("M", "mute_toggle"),
        ("=", "speed_up"),
        ("-", "speed_down"),
        ("Backspace", "speed_reset"),
    ],
    "subtitles": [
        ("S", "read_aloud_current"),
        ("X", "read_aloud_stop"),
        ("Ctrl+Right", "next_subtitle"),
        ("Ctrl+Left", "prev_subtitle"),
        ("Ctrl+Shift+Right", "subtitle_delay_less"),
        ("Ctrl+Shift+Left", "subtitle_delay_more"),
        ("Ctrl+C", "sub.copy_line"),
        ("F9", "show_subtitle_panel"),
        ("R", "sub.search_online"),
        ("B", "merge.title"),
    ],
}


class ShortcutsDialog(QDialog):
    """جدول الاختصارات."""

    def __init__(self, parent, tr: i18n.Translator) -> None:
        super().__init__(parent)
        self.tr = tr
        self.setWindowTitle(tr("shortcuts.title"))
        self.setWindowIcon(parent.windowIcon())
        self.setModal(True)
        self.resize(560, 620)
        self.setAccessibleName(tr("shortcuts.title"))
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if tr.is_rtl()
            else Qt.LayoutDirection.LeftToRight
        )

        root = QVBoxLayout(self)
        for group_key, items in SHORTCUTS.items():
            title = tr("shortcuts." + group_key)
            box = QGroupBox(title)
            lay = QVBoxLayout(box)
            for keys, ikey in items:
                row = QLabel(f"<b>{keys}</b>  —  {tr(ikey)}")
                row.setTextFormat(Qt.TextFormat.RichText)
                a11y(row, f"{keys}, {tr(ikey)}", f"{keys} does {tr(ikey)}")
                lay.addWidget(row)
            root.addWidget(box)
        root.addStretch(1)