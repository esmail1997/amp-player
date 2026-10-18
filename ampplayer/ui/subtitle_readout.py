"""لوحة قراءة الترجمة: تعرض السطر الحالي والتالي مع سجل كامل."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import config, i18n
from ..subtitle_engine import SubtitleEngine
from ..subtitle_parser import Cue, format_timestamp
from .widgets import TranscriptView, a11y, make_button, make_label


class SubtitleReadout(QFrame):
    """
    اللوحة السفلية المخصصة لعرض الترجمة:
      - السطر الحالي (بخط كبير)
      - السطر التالي (أصغر رمادياً)
      - عدّاد رقم السطر
      - سجل كامل قابل للتمرير
    """

    seek_to_cue_requested = Signal(int)     # milliseconds
    read_aloud_requested = Signal()
    stop_speech_requested = Signal()
    offset_changed = Signal(float)

    def __init__(self, engine: SubtitleEngine, tr: i18n.Translator,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.tr = tr
        self.cfg = config.Config()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("subtitleReadout")

        # ---------- تخطيط السطر الحالي ----------
        self.current_label = make_label("", name="Current subtitle",
                                       desc="The subtitle line being read now")
        self.current_label.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.current_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_label.setMinimumHeight(64)
        self.current_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        self.next_label = make_label("", name="Next subtitle",
                                     desc="The upcoming subtitle line")
        self.next_label.setFont(QFont("Segoe UI", 12))
        self.next_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_label.setStyleSheet("color: #999999;")

        self.index_label = QLabel("")
        self.index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.index_label.setStyleSheet("color: #666666;")
        a11y(self.index_label, "Subtitle position",
             "Current subtitle number out of total")

        current_box = QVBoxLayout()
        current_box.setContentsMargins(8, 6, 8, 6)
        current_box.setSpacing(2)
        current_box.addWidget(self.current_label)
        current_box.addWidget(self.next_label)
        current_box.addWidget(self.index_label)

        # ---------- أزرار التحكم بالترجمة ----------
        # الاختصارات تُسجَّل في MainWindow._bind_keys مرة واحدة فقط،
        # لأن Qt يُعطّل الاختصارات المكرّرة على مستوى النافذة.
        self.btn_prev = make_button("", "Previous subtitle", tr("prev_subtitle"))
        self.btn_next = make_button("", "Next subtitle", tr("next_subtitle"))
        self.btn_read = make_button("", "Read subtitle aloud", tr("read_aloud_current"))
        self.btn_stop = make_button("", "Stop reading", tr("read_aloud_stop"))
        self.btn_copy = make_button("", "Copy current line", tr("sub.copy_line"))
        self.btn_earlier = make_button("-0.5s", "Delay subtitles 0.5 seconds",
                                       tr("subtitle_delay_more"))
        self.btn_later = make_button("+0.5s", "Advance subtitles 0.5 seconds",
                                     tr("subtitle_delay_less"))
        self.btn_log = make_button("", "Clear subtitle log", tr("sub.clear_log"))
        self.btn_export = make_button("", "Save subtitle log", tr("sub.export_log"))
        self.btn_close = make_button("", "Hide subtitle panel",
                                     tr("hide_subtitle_panel"))

        for b in (self.btn_prev, self.btn_next, self.btn_read, self.btn_stop,
                  self.btn_copy, self.btn_earlier, self.btn_later,
                  self.btn_log, self.btn_export, self.btn_close):
            b.setMinimumWidth(40)

        self.btn_prev.clicked.connect(self._on_prev)
        self.btn_next.clicked.connect(self._on_next)
        self.btn_read.clicked.connect(self.read_aloud_requested)
        self.btn_stop.clicked.connect(self.stop_speech_requested)
        self.btn_copy.clicked.connect(self._on_copy)
        self.btn_earlier.clicked.connect(lambda: self._shift(-0.5))
        self.btn_later.clicked.connect(lambda: self._shift(0.5))
        self.btn_log.clicked.connect(self._on_clear_log)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_close.clicked.connect(self.hide)

        controls = QHBoxLayout()
        controls.setContentsMargins(4, 2, 4, 4)
        controls.setSpacing(4)
        for b in (self.btn_prev, self.btn_next, self.btn_read, self.btn_stop,
                  self.btn_copy, self.btn_earlier, self.btn_later,
                  self.btn_log, self.btn_export, self.btn_close):
            controls.addWidget(b)
        controls.addStretch(1)

        # ---------- السجل ----------
        self.log_view = TranscriptView()
        self.log_view.setMaximumHeight(110)
        self.log_view.setVisible(bool(self.cfg.get("show_subtitle_log")))

        self.toggle_log_btn = make_button("", "Toggle subtitle log",
                                          tr("prefs.show_logs"), "")
        self.toggle_log_btn.setCheckable(True)
        self.toggle_log_btn.setChecked(bool(self.cfg.get("show_subtitle_log")))
        self.toggle_log_btn.toggled.connect(self._on_toggle_log)

        # ---------- تخطيط عام ----------
        layout = QGridLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(4)
        layout.addLayout(current_box, 0, 0)
        layout.addLayout(controls, 1, 0)
        layout.addWidget(self.log_view, 2, 0)
        layout.addWidget(self.toggle_log_btn, 3, 0, alignment=Qt.AlignmentFlag.AlignCenter)

        # نربط إشارات المحرك
        engine.cue_changed.connect(self.on_cue_changed)
        engine.log_changed.connect(self._refresh_log)
        engine.loaded.connect(self._on_loaded)
        engine.unloaded.connect(self._on_unloaded)

        self.set_placeholder()

    # ------------------------------------------------------------ الترجمة
    def retranslate(self, tr: i18n.Translator) -> None:
        self.tr = tr
        self.btn_prev.setAccessibleName(tr("prev_subtitle"))
        self.btn_next.setAccessibleName(tr("next_subtitle"))
        self.btn_read.setAccessibleName(tr("read_aloud_current"))
        self.btn_stop.setAccessibleName(tr("read_aloud_stop"))
        self.btn_copy.setAccessibleName(tr("sub.copy_line"))
        self.btn_log.setAccessibleName(tr("sub.clear_log"))
        self.btn_export.setAccessibleName(tr("sub.export_log"))
        self.btn_close.setAccessibleName(tr("hide_subtitle_panel"))
        self.toggle_log_btn.setAccessibleName(tr("prefs.show_logs"))
        self.btn_prev.setToolTip(tr("prev_subtitle"))
        self.btn_next.setToolTip(tr("next_subtitle"))
        self.btn_read.setToolTip(tr("read_aloud_current"))
        self.btn_stop.setToolTip(tr("read_aloud_stop"))
        self.btn_copy.setToolTip(tr("sub.copy_line"))
        self.btn_log.setToolTip(tr("sub.clear_log"))
        self.btn_export.setToolTip(tr("sub.export_log"))
        self.btn_close.setToolTip(tr("hide_subtitle_panel"))

    # ------------------------------------------------------------ الحالة
    def set_placeholder(self, text: str = "") -> None:
        msg = text or self.tr("sub.no_subtitles")
        self.current_label.setText(msg)
        self.current_label.setFont(QFont("Segoe UI", 12))
        self.next_label.setText("")
        self.index_label.setText("")
        self.current_label.setAccessibleDescription(msg)

    def clear_placeholder(self) -> None:
        """يمسح الرسالة المؤقتة بعد تحميل ترجمة بنجاح."""
        self.current_label.setText("")
        self.current_label.setAccessibleDescription("")

    def on_cue_changed(self, cue: Optional[Cue]) -> None:
        if cue is None:
            self.current_label.setText("")
            self.next_label.setText("")
            self.index_label.setText("")
            self.current_label.setAccessibleDescription(self.tr("sub.no_subtitles"))
            return
        self.current_label.setText(cue.text)
        self.current_label.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        # وصف كامل لقارئ الشاشة: النص + رقم السطر + الموقع الزمني
        desc = (f"Subtitle {cue.index} of {self.engine.count()}, "
                f"at {format_timestamp(cue.start_ms)}. {cue.text}")
        self.current_label.setAccessibleDescription(desc)
        nxt = self.engine.next_cue()
        self.next_label.setText(nxt.text.replace("\n", " ") if nxt else "")
        if nxt:
            self.next_label.setAccessibleDescription(f"Next line: {nxt.text}")
        self.index_label.setText(
            f"{self.tr('sub.line')} {cue.index} / {self.engine.count()}  |  "
            f"{self.tr('sub.time')} {format_timestamp(cue.start_ms)}"
        )
        # في سجل القراءة
        stamp = format_timestamp(cue.start_ms)
        self.engine.append_log(f"[{stamp}] {cue.text}")

    def _refresh_log(self) -> None:
        self.log_view.set_text(self.engine.log_text())

    def _on_loaded(self, path: str, count: int) -> None:
        name = Path(path).name if path else ""
        self.current_label.setText("")
        self.next_label.setText("")
        self.index_label.setText(f"{self.tr('sub.lines_count')}: {count}")
        self.current_label.setAccessibleDescription(
            f"Subtitle file loaded: {name}, {count} lines"
        )

    def _on_unloaded(self) -> None:
        self.set_placeholder()

    # ------------------------------------------------------------ تفاعل
    def _on_prev(self) -> None:
        c = self.engine.jump_to_prev()
        if c is not None:
            self.seek_to_cue_requested.emit(c.start_ms)

    def _on_next(self) -> None:
        c = self.engine.jump_to_next()
        if c is not None:
            self.seek_to_cue_requested.emit(c.start_ms)

    def _shift(self, delta: float) -> None:
        new = self.engine.adjust_offset(delta)
        self.offset_changed.emit(new)
        self.index_label.setText(
            f"{self.tr('sub.delay_offset')}: {new:+.1f}s"
        )

    def _on_copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        cue = self.engine.current_cue()
        text = cue.text if cue else self.engine.log_text()
        if text:
            QApplication.clipboard().setText(text)

    def _on_clear_log(self) -> None:
        self.engine.clear_log()

    def _on_export(self) -> None:
        if not self.engine.has_cues:
            return
        start = self.engine.source_path
        default = Path(start).with_suffix(".txt").name if start else "subtitles.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("sub.export_log"), default, "Text files (*.txt);;SRT (*.srt)"
        )
        if not path:
            return
        try:
            if path.lower().endswith(".srt"):
                Path(path).write_text(self.engine.export_srt(), encoding="utf-8")
            else:
                Path(path).write_text(self.engine.log_text(), encoding="utf-8")
        except OSError:
            pass

    def _on_toggle_log(self, on: bool) -> None:
        self.log_view.setVisible(on)
        self.cfg.set("show_subtitle_log", on)
        self.cfg.sync()

    def toggle(self) -> None:
        self.setVisible(not self.isVisible())

    def focus_current(self) -> None:
        self.current_label.setFocus(Qt.FocusReason.OtherFocusReason)