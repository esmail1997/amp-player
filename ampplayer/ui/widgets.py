"""عناصر واجهة أساسية محسّنة للوصولية (تُقرأ بقارئ الشاشة)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAccessible, QFont, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QWidget,
)


def a11y(widget: QWidget, name: str = "", desc: str = "", help_text: str = "") -> QWidget:
    """يضبط سمات الوصولية لأي عنصر واجهة."""
    if name:
        widget.setAccessibleName(name)
    if desc:
        widget.setAccessibleDescription(desc)
    if help_text:
        widget.setToolTip(help_text)
        widget.setStatusTip(help_text)
    return widget


def make_button(text: str, name: str = "", desc: str = "", shortcut: str = "",
                icon=None) -> QPushButton:
    """زر قياسي مع اسم وصولي واضح."""
    b = QPushButton(text)
    a11y(b, name or text, desc)
    if shortcut:
        b.setShortcut(shortcut)
        b.setAccessibleDescription(desc or shortcut)
    if icon is not None:
        b.setIcon(icon)
    return b


def make_tool_button(text: str, name: str = "", desc: str = "") -> QToolButton:
    b = QToolButton()
    b.setText(text)
    a11y(b, name or text, desc)
    return b


def make_label(text: str, name: str = "", desc: str = "", wordwrap: bool = True) -> QLabel:
    l = QLabel(text)
    a11y(l, name or text, desc)
    l.setWordWrap(wordwrap)
    l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return l


def make_slider(min_v: int, max_v: int, value: int, name: str = "",
                desc: str = "") -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(min_v, max_v)
    s.setValue(value)
    s.setAccessibleName(name)
    s.setAccessibleDescription(desc)
    s.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return s


class VolumeSlider(QSlider):
    """
    شريط صوت يتجاهل حركة الماوس الصغيرة (حتى يعمل مع النقر وال.Foreign keys)
    """

    valueCommitted = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 200)
        self.setValue(100)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Volume")
        self.setAccessibleDescription("Use arrow keys to change volume")
        self._dragging = False
        self._last_value = self.value()

    def sliderPressed(self) -> None:  # noqa: N802
        self._dragging = True

    def sliderReleased(self) -> None:  # noqa: N802
        self._dragging = False
        self.valueCommitted.emit(self.value())

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        super().mouseReleaseEvent(ev)
        if not self._dragging and self.value() != self._last_value:
            self.valueCommitted.emit(self.value())

    def wheelEvent(self, ev) -> None:  # noqa: N802
        delta = ev.angleDelta().y()
        if delta:
            self.setValue(self.value() + (5 if delta > 0 else -5))
            self.valueCommitted.emit(self.value())
            ev.accept()
            return
        super().wheelEvent(ev)

    def keyPressEvent(self, ev: QKeyEvent) -> None:  # noqa: N802
        before = self.value()
        super().keyPressEvent(ev)
        if self.value() != before:
            self.valueCommitted.emit(self.value())

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self._last_value = self.value()
        super().leaveEvent(ev)


class LiveRegion(QWidget):
    """
    منطقة حيّة (aria-live) لقارئ الشاشة.
    أي نص يُعرض في _announce يُقرأ فوراً حتى لو لم يركز المستخدم عليها.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._label = QLabel(self)
        self._label.setVisible(False)
        self._label.setAccessibleName("Live region")
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._last = ""
        # تكرار النص يضمن أن يلتقطه قارئ الشاشة حتى لو كان مشغولاً
        self._repeats = 0
        # نحتفظ بحجم صغير حتى لا يأخذ المساحة من التخطيط
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def announce(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if text == self._last:
            # نكرّر النص بمسافة إضافية حتى يلتقطه قارئ الشاشة مرة أخرى
            self._repeats = (self._repeats + 1) % 4
            spoken = text + (" " * self._repeats)
        else:
            self._repeats = 0
            spoken = text
        self._last = text
        self._label.setText(spoken)
        self._label.setAccessibleDescription(text)
        try:
            QAccessible.updateAccessibility(self._label, QAccessible.Event.ValueChanged)
        except Exception:
            pass

    def text(self) -> str:
        return self._last


class AccessibleTextEdit(QPlainTextEdit):
    """مربع نصي للقراءة مع اختصارات."""
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


class TranscriptView(QPlainTextEdit):
    """
    عرض السجل النصي للترجمة (سجل conversation).
    يُحدّث نصه ويبقى قابلاً للتمرير والبحث بقارئ الشاشة.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 12))
        self.setAccessibleName("Subtitle log")
        self.setAccessibleDescription("Full list of subtitle lines read so far")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

    def set_text(self, text: str) -> None:
        pos = self.verticalScrollBar().value()
        at_bottom = pos >= self.verticalScrollBar().maximum() - 4
        self.setPlainText(text)
        self.setAccessibleDescription(
            f"{len(text.splitlines())} lines in subtitle log"
        )
        if at_bottom:
            self.moveCursor(QTextCursor.MoveOperation.End)
            self.ensureCursorVisible()
        else:
            self.verticalScrollBar().setValue(pos)