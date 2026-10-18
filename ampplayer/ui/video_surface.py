"""
عنصر الفيديو: يرسم إطارات محرّك FFmpeg على الشاشة.

المحرّك يسلّطنا صورة Qt جاهزة، فنرسمها ونرسم فوقها الترجمة النشطة.
الترجمة هنا مكمّلة لا أساسية: المكفوف يسمعها من لوحة النطق أسفل النافذة،
ومن يراقب معك يقرأها على الشاشة.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

# أساس حجم الخط قبل تطبيق نسبة التكبير من الإعدادات
SUB_BASE_PT = 20


class VideoSurface(QWidget):
    """
    يعرض الفيديو ويسحب الترجمة فوقه.

    لا يعرض نصاً عدا الترجمة؛ كل حالة له موصوفة عبر
    AccessibleName/AccessibleDescription ليقرأها قارئ الشاشة.
    """

    # انفجر عند تغيّر المقاس، ليُبلغ المحرّك بأقصى مقاس نرسمه فتصغّر
    # إطارات 4K قبل نسخها إلى الشاشة.
    resized = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._frame: Optional[QImage] = None
        self._subtitle = ""
        self._sub_scale = 100
        self._sub_base_pt = SUB_BASE_PT
        self._sub_position = "bottom"
        self._sub_enabled = True
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setMinimumSize(QSize(160, 90))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Video area")
        self.setAccessibleDescription("Shows the video picture")

    # ==================================================================
    # الواجهة العامة
    # ==================================================================
    def set_frame(self, image: Optional[QImage]) -> None:
        """يستقبل أحدث إطار ويطلب إعادة الرسم."""
        self._frame = image
        self.update()

    def clear(self) -> None:
        self._frame = None
        self.update()

    def set_subtitle(self, text: str) -> None:
        """يضع نص الترجمة النشطة (يُرسم فوق الصورة)."""
        text = text or ""
        if text != self._subtitle:
            self._subtitle = text
            self.update()

    def set_subtitle_scale(self, percent: int) -> None:
        percent = max(25, min(500, int(percent)))
        if percent != self._sub_scale:
            self._sub_scale = percent
            self.update()

    def set_subtitle_base_pt(self, points: int) -> None:
        """حجم الخط الأساسي بالبكسل، من إعدادات المستخدم."""
        points = max(8, min(96, int(points)))
        if points != self._sub_base_pt:
            self._sub_base_pt = points
            self.update()

    def set_subtitle_position(self, position: str) -> None:
        """موضع الترجمة على الشاشة: bottom أو top."""
        pos = "top" if str(position) == "top" else "bottom"
        if pos != self._sub_position:
            self._sub_position = pos
            self.update()

    def set_subtitle_enabled(self, on: bool) -> None:
        """إظهار الترجمة فوق الصورة أو إخفاؤها."""
        on = bool(on)
        if on != self._sub_enabled:
            self._sub_enabled = on
            self.update()

    @property
    def has_frame(self) -> bool:
        return self._frame is not None and not self._frame.isNull()

    @property
    def subtitle_text(self) -> str:
        return self._subtitle if self._sub_enabled else ""

    # ==================================================================
    # الأحداث
    # ==================================================================
    def resizeEvent(self, event) -> None:  # noqa: N802 (اسم يطلبه Qt)
        super().resizeEvent(event)
        self.resized.emit()

    def paintEvent(self, event) -> None:  # noqa: N802 (اسم يطلبه Qt)
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor(0, 0, 0))
            if self._frame is not None and not self._frame.isNull():
                self._paint_frame(painter)
            if self._sub_enabled and self._subtitle:
                self._paint_subtitle(painter)
        finally:
            painter.end()

    def _paint_frame(self, painter: QPainter) -> None:
        img = self._frame
        assert img is not None
        area = self.rect()
        iw, ih = img.width(), img.height()
        if iw <= 0 or ih <= 0:
            return
        scale = min(area.width() / iw, area.height() / ih)
        w = max(1, int(iw * scale))
        h = max(1, int(ih * scale))
        x = area.x() + (area.width() - w) // 2
        y = area.y() + (area.height() - h) // 2
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(QRect(x, y, w, h), img)

    def _wrap_lines(self, text: str, max_px: int, metrics) -> List[str]:
        """
        يقسّم الترجمة على أسطر تناسب العرض.

        بدون هذا يخرج النص عن الإطار أو يُقصّ، وهو شائع في
        الترجمة العربية لأن كلماتها أطول من نظيرتها اللاتينية.
        """
        out: List[str] = []
        for para in text.splitlines() or [""]:
            cur = ""
            for word in para.split():
                trial = f"{cur} {word}".strip()
                if cur and metrics.horizontalAdvance(trial) > max_px:
                    out.append(cur)
                    cur = word
                else:
                    cur = trial
            out.append(cur)
        return out or [""]

    def _paint_subtitle(self, painter: QPainter) -> None:
        text = self._subtitle
        font = QFont()
        font.setPointSize(max(10, int(self._sub_base_pt
                                      * (self._sub_scale / 100.0))))
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()

        area = self.rect()
        pad = max(6, font.pointSize() // 2)
        max_w = max(200, area.width() - pad * 4)
        lines = self._wrap_lines(text, max_w, metrics)
        # لا نملأ الشاشة بالنص: نكتفي بما يلائم الارتفاع المتاح
        while len(lines) > 1 and len(lines) * metrics.height() > area.height() // 2:
            font.setPointSize(max(10, font.pointSize() - 2))
            painter.setFont(font)
            metrics = painter.fontMetrics()
            lines = self._wrap_lines(text, max_w, metrics)

        line_h = metrics.height()
        total_h = line_h * len(lines)
        widest = max(metrics.horizontalAdvance(ln) for ln in lines)
        if self._sub_position == "top":
            y = area.y() + pad
        else:
            y = area.bottom() - total_h - pad

        box = QRect(
            area.x() + (area.width() - widest) // 2 - pad // 2,
            y - pad // 2,
            widest + pad,
            total_h + pad,
        )
        painter.fillRect(box, QColor(0, 0, 0, 150))

        outline = QPen(QColor(0, 0, 0, 230))
        outline.setWidth(max(2, font.pointSize() // 5))
        painter.setPen(outline)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                self._draw_lines(painter, lines, metrics, area, y, dx, dy, line_h)

        painter.setPen(QPen(QColor(255, 255, 255)))
        self._draw_lines(painter, lines, metrics, area, y, 0, 0, line_h)

    def _draw_lines(self, painter, lines, metrics, area, y,
                    dx: int, dy: int, line_h: int) -> None:
        for i, ln in enumerate(lines):
            lw = metrics.horizontalAdvance(ln)
            lx = area.x() + (area.width() - lw) // 2
            painter.drawText(lx + dx, y + i * line_h + dy, ln)