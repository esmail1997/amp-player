"""
نافذة «حول البرنامج» المتوافقة مع قارئات الشاشة.

النافذة السابقة كانت تعتمد ``QMessageBox.about`` فلا يُعلن قارئ الشاشة
محتواها دائماً، ولا تحتوي بيانات التواصل. هذه النافذة:

- نصّ قابل للوصول والتركيز (يقرأه NVDA عند الفتح).
- أزرار واضحة: إرسال بريد، فتح الحساب، نسخ بيانات التواصل.
"""

from __future__ import annotations

import sys
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .. import contact
from ..i18n import Translator


class AboutDialog(QDialog):
    def __init__(self, parent, tr: Translator, info_html: str) -> None:
        super().__init__(parent)
        self.tr = tr
        self.setWindowTitle(tr("about"))
        self.setModal(True)
        self.setMinimumSize(560, 460)
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if tr.is_rtl()
            else Qt.LayoutDirection.LeftToRight
        )

        layout = QVBoxLayout(self)

        self.title = QLabel(tr("about"))
        f = self.title.font()
        f.setPointSize(f.pointSize() + 4)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setAccessibleName(tr("about"))
        layout.addWidget(self.title)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setHtml(info_html)
        self.browser.setAccessibleName(tr("about"))
        self.browser.setAccessibleDescription(tr("about.contact"))
        self.browser.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(self.browser, 1)

        self.lbl_contact = QLabel(tr("about.contact"))
        self.lbl_contact.setAccessibleName(tr("about.contact"))
        layout.addWidget(self.lbl_contact)

        self.contact_view = QTextBrowser()
        self.contact_view.setHtml(
            "<b>" + tr("about.email") + ":</b> "
            f'<a href="mailto:{contact.EMAIL}">{contact.EMAIL}</a><br>'
            "<b>" + tr("about.twitter") + ":</b> "
            f'<a href="{contact.TWITTER_URL}">@{contact.TWITTER_HANDLE}</a>'
        )
        self.contact_view.setOpenExternalLinks(True)
        self.contact_view.setAccessibleName(tr("about.contact"))
        self.contact_view.setAccessibleDescription(contact.contact_text())
        self.contact_view.setMaximumHeight(90)
        layout.addWidget(self.contact_view)

        self.btn_email = QPushButton(tr("about.open_email"))
        self.btn_email.setAccessibleName(tr("about.open_email"))
        self.btn_email.setAccessibleDescription(contact.EMAIL)
        self.btn_email.clicked.connect(self._open_email)
        layout.addWidget(self.btn_email)

        self.btn_twitter = QPushButton(tr("about.open_twitter"))
        self.btn_twitter.setAccessibleName(tr("about.open_twitter"))
        self.btn_twitter.setAccessibleDescription(
            f"@{contact.TWITTER_HANDLE}"
        )
        self.btn_twitter.clicked.connect(self._open_twitter)
        layout.addWidget(self.btn_twitter)

        self.btn_copy = QPushButton(tr("about.copy_contact"))
        self.btn_copy.setAccessibleName(tr("about.copy_contact"))
        self.btn_copy.clicked.connect(self._copy_contact)
        layout.addWidget(self.btn_copy)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.button(QDialogButtonBox.StandardButton.Close).setText(tr("close"))
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        layout.addWidget(box)

        self.browser.setFocus()

    # ---------------------------------------------------------------- أفعال
    def _copy_contact(self) -> None:
        cb = QGuiApplication.clipboard()
        cb.setText(contact.contact_text())
        self.btn_copy.setText(self.tr("about.copied"))

    def _open_email(self) -> None:
        try:
            webbrowser.open(contact.mailto_url())
        except Exception:
            pass

    def _open_twitter(self) -> None:
        try:
            webbrowser.open(contact.TWITTER_URL)
        except Exception:
            pass


def qt_version_str() -> str:
    """
    إصدار Qt القابل للاستعلام بأمان.

    النافذة القديمة كانت تستورد ``QT_VERSION_STR`` وهو غير موجود في PySide6
    (الاسم عند قيم غير موجودة يرفع ImportError) فتعطّل زر «حول» تماماً.
    """
    try:
        from PySide6 import QtCore

        for name in ("QT_VERSION_STR", "qVersion"):
            v = getattr(QtCore, name, None)
            if v is None:
                continue
            try:
                v = v() if callable(v) else v
            except Exception:
                v = None
            if v:
                return str(v)
        return str(getattr(QtCore, "__version__", "") or "")
    except Exception:
        return ""


def build_info_html(tr: Translator, *, version: str, engine_line: str,
                    ffmpeg_ok: bool, qt_version: str) -> str:
    """يبني محتوى نافذة «حول» نصًّا منظّماً يقرأه قارئ الشاشة سطراً سطراً."""
    rows = [
        f"<b>{tr('app.short_title')}</b> — v{version}",
        tr("about.about_text"),
        f"{tr('deps.version')}: {engine_line}",
        tr("deps.ffmpeg_ok") if ffmpeg_ok else tr("deps.ffmpeg_missing"),
        f"Qt {qt_version}",
        f"Python {sys.version.split()[0]}",
    ]
    return "<br>".join(rows)
