"""نافذة الترحيب الأولى."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLabel,
    QVBoxLayout,
)

from .. import i18n
from .widgets import a11y, make_button


class OnboardingDialog(QDialog):
    """تعريف سريع بالمفاتيح الأساسية للمستخدم الكفيف."""

    def __init__(self, parent, tr: i18n.Translator) -> None:
        super().__init__(parent)
        self.tr = tr
        self.setWindowTitle(tr("onboarding.title"))
        self.setWindowIcon(parent.windowIcon())
        self.setModal(True)
        self.setAccessibleName(tr("onboarding.title"))
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if tr.is_rtl()
            else Qt.LayoutDirection.LeftToRight
        )

        root = QVBoxLayout(self)
        title = QLabel(f"<b>{tr('onboarding.title')}</b>")
        a11y(title, tr("onboarding.title"), "")
        root.addWidget(title)

        body = QLabel(tr("onboarding.text"))
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.PlainText)
        a11y(body, tr("onboarding.title"), tr("onboarding.text"))
        root.addWidget(body)

        self.chk_dont = QCheckBox(tr("onboarding.dont_show"))
        root.addWidget(self.chk_dont)

        row = QVBoxLayout()
        self.btn_start = make_button(tr("onboarding.start"), tr("onboarding.start"),
                                     tr("onboarding.start"), "Enter")
        self.btn_start.clicked.connect(self.accept)
        self.btn_skip = make_button(tr("onboarding.skip"), tr("onboarding.skip"), "")
        self.btn_skip.clicked.connect(self.reject)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_skip)
        root.addLayout(row)

        self.resize(560, 460)