"""نافذة البحث عن ترجمة وتحميلها من مواقع الترجمة."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
)

from .. import config, i18n
from ..providers import manager
from ..providers.models import LANGUAGES, SubtitleResult
from .widgets import LiveRegion, a11y, make_button

# مفتاح فهرس البيانات داخل عناصر القائمة
ROLE_RESULT = Qt.ItemDataRole.UserRole + 1


class _SearchWorker(QObject):
    """يبحث في المواقع بالتوازي دون تجميد الواجهة."""
    done = Signal(dict)

    def __init__(self, query: str, lang: str, season: str, episode: str,
                 imdb: str, sites: list[str], timeout: int) -> None:
        super().__init__()
        self.args = (query, lang, season, episode, imdb, sites, timeout)

    def run(self) -> None:
        q, lang, season, episode, imdb, sites, timeout = self.args
        outcomes = manager.search_all(
            query=q, lang=lang, season=season, episode=episode,
            imdb_id=imdb, sites=sites, timeout=timeout,
        )
        self.done.emit(outcomes)


class _ExpandWorker(QObject):
    """يوسّع نتيجة مجموعة إلى قائمة ملفاتها."""
    done = Signal(list)

    def __init__(self, result: SubtitleResult, lang: str, timeout: int) -> None:
        super().__init__()
        self.result = result
        self.lang = lang
        self.timeout = timeout

    def run(self) -> None:
        mod = manager.PROVIDERS.get(self.result.site)
        out: list[SubtitleResult] = []
        if mod is not None and hasattr(mod, "expand"):
            try:
                out = mod.expand(self.result, timeout=self.timeout)
            except Exception:
                out = []
        if not out and self.result.download_url:
            out = [self.result]
        self.done.emit(out)


class _DownloadWorker(QObject):
    """يحمّل ملف الترجمة."""
    done = Signal(bool, str)

    def __init__(self, result: SubtitleResult, dest: Path, timeout: int) -> None:
        super().__init__()
        self.result = result
        self.dest = dest
        self.timeout = timeout

    def run(self) -> None:
        try:
            p = manager.download(self.result, self.dest, timeout=self.timeout)
        except Exception as exc:
            self.done.emit(False, str(exc))
            return
        if p:
            self.done.emit(True, str(p))
        else:
            self.done.emit(False, "")


class SubtitleSearchDialog(QDialog):
    """البحث عن ترجمة عبر الإنترنت وتحميلها."""

    subtitle_chosen = Signal(str)
    open_site_requested = Signal(str, str)

    def __init__(self, parent, tr: i18n.Translator, cfg: config.Config) -> None:
        super().__init__(parent)
        self.tr = tr
        self.cfg = cfg
        self.setWindowTitle(tr("search.title"))
        self.setWindowIcon(parent.windowIcon())
        self.resize(1020, 700)
        self.setModal(True)
        self.setAccessibleName(tr("search.title"))

        self.results: list[SubtitleResult] = []
        self.outcomes: dict = {}
        self.current_group: Optional[SubtitleResult] = None
        self._thread: Optional[QThread] = None
        self._worker = None

        self._build()
        self._prefill()

    # ------------------------------------------------------------ البناء
    def _build(self) -> None:
        tr = self.tr
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ===== نموذج البحث =====
        form_box = QGroupBox(tr("search.title"))
        form = QFormLayout(form_box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ed_query = QLineEdit()
        a11y(self.ed_query, tr("search.query"),
             "Movie or series name to search for")
        self.ed_query.setFocus()
        form.addRow(tr("search.query") + ":", self.ed_query)

        row_lang = QHBoxLayout()
        self.cb_lang = QComboBox()
        self.cb_lang.addItem("Any / الكل", "")
        for code, _c2, name in LANGUAGES:
            self.cb_lang.addItem(name, code)
        idx = self.cb_lang.findData(self.cfg.get("search_language") or "ara")
        if idx > 0:
            self.cb_lang.setCurrentIndex(idx)
        a11y(self.cb_lang, tr("search.language"), "Subtitle language to search")
        row_lang.addWidget(self.cb_lang)

        self.sp_season = QSpinBox()
        self.sp_season.setRange(0, 99)
        self.sp_season.setSpecialValueText("-")
        a11y(self.sp_season, tr("search.season"), "Season number, 0 for none")
        row_lang.addWidget(QLabel(tr("search.season") + ":"))
        row_lang.addWidget(self.sp_season)

        self.sp_episode = QSpinBox()
        self.sp_episode.setRange(0, 999)
        self.sp_episode.setSpecialValueText("-")
        a11y(self.sp_episode, tr("search.episode"), "Episode number, 0 for none")
        row_lang.addWidget(QLabel(tr("search.episode") + ":"))
        row_lang.addWidget(self.sp_episode)
        row_lang.addStretch(1)
        form.addRow(row_lang)

        self.ed_imdb = QLineEdit()
        self.ed_imdb.setPlaceholderText("tt1234567")
        a11y(self.ed_imdb, tr("search.imdb"), "IMDb id, optional, improves accuracy")
        form.addRow(tr("search.imdb") + ":", self.ed_imdb)

        self.ed_release = QLineEdit()
        a11y(self.ed_release, tr("search.release"),
             "Video release name, e.g. 1080p BluRay")
        form.addRow(tr("search.release") + ":", self.ed_release)

        # اختيار المواقع
        site_row = QHBoxLayout()
        site_row.addWidget(QLabel(tr("prefs.sites") + ":"))
        self.cb_sites = QComboBox()
        self.cb_sites.addItem(tr("search.all_sites"), "")
        for site in manager.SITE_ORDER:
            self.cb_sites.addItem(manager.site_display_name(site), site)
        a11y(self.cb_sites, tr("search.site"), "Which site to search")
        site_row.addWidget(self.cb_sites, 1)
        form.addRow(site_row)

        self.btn_search = make_button(tr("search.start"), tr("search.start"),
                                      "Start searching subtitle sites", "Return")
        self.btn_search.clicked.connect(self.start_search)
        self.btn_search.setDefault(True)
        form.addRow(self.btn_search)

        root.addWidget(form_box)

        # ===== شريط الحالة =====
        status_row = QHBoxLayout()
        self.lbl_status = QLabel("")
        a11y(self.lbl_status, "Search status", "Current search status")
        status_row.addWidget(self.lbl_status, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(220)
        self.progress.setVisible(False)
        status_row.addWidget(self.progress)
        root.addLayout(status_row)

        # ===== النتائج =====
        split = QSplitter(Qt.Orientation.Horizontal)

        self.list_results = QListWidget()
        self.list_results.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_results.setFont(QFont("Segoe UI", 10))
        a11y(self.list_results, tr("search.results"),
             "Search results list. Use up and down arrows to browse.")
        self.list_results.currentRowChanged.connect(self._on_result_selected)
        self.list_results.itemDoubleClicked.connect(self._on_result_double)
        split.addWidget(self.list_results)

        self.txt_details = QTextBrowser()
        self.txt_details.setOpenExternalLinks(True)
        a11y(self.txt_details, "Result details", "Details of the selected subtitle")
        split.addWidget(self.txt_details)
        split.setSizes([560, 440])
        root.addWidget(split, 1)

        # ===== أزرار الإجراءات =====
        actions = QHBoxLayout()
        self.btn_expand = make_button(tr("search.expand_files"),
                                      tr("search.expand_files"),
                                      "List the individual subtitle files")
        self.btn_expand.clicked.connect(self.expand_selected)
        self.btn_download = make_button(tr("download"), tr("download"),
                                        tr("search.downloading"), "Ctrl+D")
        self.btn_download.clicked.connect(self.download_selected)
        self.btn_open_site = make_button(tr("search.open_site"),
                                         tr("search.open_site"),
                                         "Open the website in your browser", "Ctrl+B")
        self.btn_open_site.clicked.connect(self._open_site_clicked)
        self.btn_close = make_button(tr("close"), tr("close"), tr("close"), "Esc")
        self.btn_close.clicked.connect(self.reject)
        for b in (self.btn_expand, self.btn_download, self.btn_open_site, self.btn_close):
            actions.addWidget(b)
        actions.addStretch(1)
        root.addLayout(actions)

        self.hint = QLabel(tr("search.manual_hint"))
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #777777;")
        root.addWidget(self.hint)

        self.live = LiveRegion()
        self.live.setParent(self)

    def _prefill(self) -> None:
        """يملأ النموذج من الملف الحالي إن أمكن."""
        parent = self.parent()
        current = getattr(parent, "current_path", "")
        if current and not current.lower().startswith(("http", "rtsp")):
            name = Path(current).stem
            self.ed_query.setText(name)
            self.ed_release.setText(name)
        s = self.cfg.get("search_season") or ""
        e = self.cfg.get("search_episode") or ""
        if str(s).isdigit():
            self.sp_season.setValue(int(s))
        if str(e).isdigit():
            self.sp_episode.setValue(int(e))
        imp = self.cfg.get("search_imdb") or ""
        if imp:
            self.ed_imdb.setText(str(imp))

    # ------------------------------------------------------------ البحث
    def start_search(self) -> None:
        query = self.ed_query.text().strip()
        if not query:
            self.live.announce(self.tr("search.check_query"))
            self.ed_query.setFocus()
            return
        site = self.cb_sites.currentData() or ""
        sites = [site] if site else manager.enabled_sites(self.cfg)
        self.cfg.set("search_season", str(self.sp_season.value()))
        self.cfg.set("search_episode", str(self.sp_episode.value()))
        self.cfg.set("search_imdb", self.ed_imdb.text().strip())
        self.cfg.sync()

        self.list_results.clear()
        self.txt_details.clear()
        self.results = []
        self.btn_download.setEnabled(False)
        self.progress.setRange(0, len(sites))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.btn_search.setEnabled(False)
        self.lbl_status.setText(self.tr("search.searching"))
        self.live.announce(self.tr("search.searching"))

        self._start_worker(
            _SearchWorker(
                query,
                self.cb_lang.currentData() or "",
                str(self.sp_season.value()),
                str(self.sp_episode.value()),
                self.ed_imdb.text().strip(),
                sites,
                20,
            ),
            self._on_search_done,
        )

    def _on_search_done(self, outcomes: dict) -> None:
        self.outcomes = outcomes
        self.progress.setVisible(False)
        self.btn_search.setEnabled(True)

        results = manager.flatten(outcomes, sort="downloads")
        self.results = results
        total = 0
        for site in manager.SITE_ORDER:
            o = outcomes.get(site)
            if not o:
                continue
            count = len(o.results)
            total += count
            note = ""
            if o.error:
                note = f" ({o.error})"
            elif o.needs_manual and not count:
                note = " (browser)"
            self.lbl_status.setText(
                f"{manager.site_display_name(site)}: {count}{note}"
            )
            # عنصر رأس لكل موقع
            head = QListWidgetItem(f"— {manager.site_display_name(site)} ({count}) —")
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            head.setForeground(Qt.GlobalColor.gray)
            self.list_results.addItem(head)
            for r in o.results:
                it = QListWidgetItem(self._format(r))
                it.setData(ROLE_RESULT, r)
                it.setToolTip(r.label())
                self.list_results.addItem(it)

        if total == 0:
            self.lbl_status.setText(self.tr("search.no_results"))
            self.live.announce(self.tr("search.no_results"))
        else:
            self.lbl_status.setText(f"{self.tr('search.results')}: {total}")
            self.live.announce(f"{total} {self.tr('search.results')}")

    @staticmethod
    def _format(r: SubtitleResult) -> str:
        bits = [f"[{r.site_name}]", r.title or r.release]
        if r.year:
            bits.append(f"({r.year})")
        if r.season:
            bits.append(f"S{r.season}")
        if r.episode:
            bits.append(f"E{r.episode}")
        bits.append(r.display_language or "?")
        if r.downloads:
            bits.append(f"{r.downloads}↓")
        if r.kind == "group":
            bits.append(f"{r.note}")
        elif r.note:
            bits.append(r.note)
        return "  ".join(str(b) for b in bits if b)

    # ------------------------------------------------------------ التحديد
    def current_result(self) -> Optional[SubtitleResult]:
        row = self.list_results.currentRow()
        if row < 0:
            return None
        item = self.list_results.item(row)
        if item is None:
            return None
        return item.data(ROLE_RESULT)

    def _on_result_selected(self, row: int) -> None:
        r = self.current_result()
        if r is None:
            self.btn_download.setEnabled(False)
            return
        self.current_group = r
        self.btn_download.setEnabled(bool(r.download_url) or r.kind != "group")
        self.txt_details.setHtml(self._details_html(r))
        self.live.announce(r.label())

    def _on_result_double(self, item: QListWidgetItem) -> None:
        self.download_selected()

    def _details_html(self, r: SubtitleResult) -> str:
        rows = [
            ("Site", r.site_name),
            ("Title", r.title),
            ("Release", r.release),
            ("Year", r.year),
            ("Language", r.display_language),
            ("Season", r.season),
            ("Episode", r.episode),
            ("Downloads", r.downloads),
            ("Type", r.kind),
            ("Note", r.note),
        ]
        html = ['<div dir="ltr" style="text-align:left">',
                f"<h3>{r.title}</h3><table cellpadding='4'>"]
        for k, v in rows:
            if v not in ("", None, 0):
                html.append(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>")
        if r.url:
            html.append(f"<tr><td><b>URL</b></td>"
                        f"<td><a href='{r.url}'>{r.url}</a></td></tr>")
        html.append("</table></div>")
        return "".join(html)

    # ------------------------------------------------------------ التوسيع
    def expand_selected(self) -> None:
        r = self.current_result()
        if r is None:
            return
        mod = manager.PROVIDERS.get(r.site)
        if mod is None or not hasattr(mod, "expand"):
            self.live.announce(self.tr("search.no_files"))
            return
        self.lbl_status.setText(self.tr("search.searching"))
        lang = self.cb_lang.currentData() or ""
        self._start_worker(_ExpandWorker(r, lang, 25), self._on_expand_done)

    def _on_expand_done(self, items: list) -> None:
        self.lbl_status.setText(self.tr("search.results") + f": {len(items)}")
        # نستبدل عنصر المجموعة بقائمة ملفاتها
        row = self.list_results.currentRow()
        self.list_results.takeItem(row)
        at = row
        if not items:
            head = QListWidgetItem(self.tr("search.no_files"))
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_results.insertItem(at, head)
            return
        for r in items:
            it = QListWidgetItem(self._format(r))
            it.setData(ROLE_RESULT, r)
            it.setToolTip(r.label())
            self.list_results.insertItem(at, it)
            at += 1
        self.list_results.setCurrentRow(row)
        self.live.announce(f"{len(items)} {self.tr('search.results')}")

    # ------------------------------------------------------------ التحميل
    def download_selected(self) -> None:
        r = self.current_result()
        if r is None:
            return
        dest_dir = self.cfg.get("download_dir") or ""
        if not dest_dir:
            from .. import config as _c

            dest_dir = str(_c.subtitles_cache_dir())
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.btn_download.setEnabled(False)
        self.lbl_status.setText(self.tr("search.downloading"))
        self.live.announce(self.tr("search.downloading"))
        self._start_worker(
            _DownloadWorker(r, Path(dest_dir), 40), self._on_download_done
        )

    def _on_download_done(self, ok: bool, path: str) -> None:
        self.progress.setVisible(False)
        self.btn_download.setEnabled(True)
        if ok:
            self.lbl_status.setText(f"{self.tr('search.download_ok')}: {Path(path).name}")
            self.live.announce(
                f"{self.tr('search.download_ok')}. {Path(path).name}. "
                f"{self.tr('search.added_to_app')}"
            )
            self.subtitle_chosen.emit(path)
            QMessageBox.information(
                self, self.tr("search.title"),
                f"{self.tr('search.download_ok')}\n\n{path}\n\n"
                f"{self.tr('search.added_to_app')}"
            )
            self.accept()
        else:
            self.lbl_status.setText(self.tr("search.download_fail"))
            self.live.announce(self.tr("search.download_fail"))

    # ------------------------------------------------------------ الموقع
    def _open_site_clicked(self) -> None:
        r = self.current_result()
        site = r.site if r else (self.cb_sites.currentData() or "")
        if not site:
            site = manager.SITE_ORDER[0]
        self.open_site_requested.emit(site, self.ed_query.text().strip())

    # ------------------------------------------------------------ العامل
    def _start_worker(self, worker: QObject, callback) -> None:
        self._stop_worker()
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_worker_done)
        self._thread = thread
        self._worker = worker
        self._callback = callback
        thread.start()

    def _on_worker_done(self, payload) -> None:
        cb = getattr(self, "_callback", None)
        if cb is not None:
            try:
                cb(payload)
            except Exception:
                pass

    def _stop_worker(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread = None
            self._worker = None

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_worker()
        super().closeEvent(event)

    def reject(self) -> None:
        self._stop_worker()
        super().reject()