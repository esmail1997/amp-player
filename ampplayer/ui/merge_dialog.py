"""نافذة دمج ملف الترجمة داخل الفيديو باستخدام FFmpeg."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
)

from .. import config, i18n, media_probe, subtitle_merger
from ..providers.models import LANGUAGES
from .widgets import LiveRegion, a11y, make_button

VIDEO_FILTER = (
    "Video files (*.mkv *.mp4 *.avi *.mov *.m4v *.webm *.wmv *.flv *.ts "
    "*.m2ts *.mpg *.mpeg *.3gp *.ogv *.vob);;All files (*.*)"
)
SUB_FILTER = (
    "Subtitle files (*.srt *.vtt *.ass *.ssa *.sub *.sami *.smi *.txt);;All files (*.*)"
)


class _MergeWorker(QThread):
    """ينفّذ الدمج في خيط منفصل مع تحديث التقدّم."""

    progress = Signal(int, str)
    finished_ok = Signal(str)
    finished_err = Signal(str)

    def __init__(self, video: str, sub: str, out: str, lang: str,
                 title: str, copy_audio: bool, default_track: bool) -> None:
        super().__init__()
        self.video = video
        self.sub = sub
        self.out = out
        self.lang = lang
        self.title = title
        self.copy_audio = copy_audio
        self.default_track = default_track

    def run(self) -> None:
        def cb(pct: int, stage: str) -> None:
            self.progress.emit(pct, stage)

        res = subtitle_merger.merge_subtitle(
            self.video, self.sub, self.out,
            language=self.lang, title=self.title,
            default_track=self.default_track,
            copy_audio=self.copy_audio,
            progress_cb=cb,
        )
        if res.ok:
            self.finished_ok.emit(res.output)
        else:
            self.finished_err.emit(res.error)


class MergeDialog(QDialog):
    """يختار ملف الفيديو وملف الترجمة ثم يدمجهما."""

    def __init__(self, parent, tr: i18n.Translator, cfg: config.Config,
                 video_path: str = "") -> None:
        super().__init__(parent)
        self.tr = tr
        self.cfg = cfg
        self.worker: Optional[_MergeWorker] = None
        self.setWindowTitle(tr("merge.title"))
        self.setWindowIcon(parent.windowIcon())
        self.setModal(True)
        self.resize(660, 460)
        self.setAccessibleName(tr("merge.title"))
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if tr.is_rtl()
            else Qt.LayoutDirection.LeftToRight
        )

        self._build(video_path)

    def _build(self, video_path: str) -> None:
        tr = self.tr
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        if not media_probe.has_ffmpeg():
            warn = QLabel(tr("merge.needs_ffmpeg"))
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #b8860b; padding: 6px;")
            root.addWidget(warn)
            self.lbl_deps = QLabel(f"{tr('deps.ffmpeg_missing')}\n{tr('deps.ffmpeg_hint')}")
            self.lbl_deps.setWordWrap(True)
            root.addWidget(self.lbl_deps)
            btn_open = make_button(tr("open"), tr("deps.browse"),
                                   tr("deps.browse"))
            btn_open.clicked.connect(self._pick_ffmpeg)
            root.addWidget(btn_open, alignment=Qt.AlignmentFlag.AlignLeft)

        # ---- ملفات ----
        self.ed_video = QLineEdit(video_path)
        a11y(self.ed_video, tr("merge.video_file"), "Path of the video file")
        self.btn_video = make_button(tr("browse"), "Select video",
                                     tr("merge.select_video"))
        self.btn_video.clicked.connect(self._pick_video)

        self.ed_sub = QLineEdit()
        a11y(self.ed_sub, tr("merge.subtitle_file"), "Path of the subtitle file")
        self.btn_sub = make_button(tr("browse"), "Select subtitle",
                                   tr("merge.select_sub"))
        self.btn_sub.clicked.connect(self._pick_sub)

        self.ed_out = QLineEdit()
        a11y(self.ed_out, tr("merge.output"), "Where to save the merged file")
        self.btn_out = make_button(tr("browse"), "Select output",
                                   tr("merge.select_output"))
        self.btn_out.clicked.connect(self._pick_out)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for label, edit, btn in (
            (tr("merge.video_file") + ":", self.ed_video, self.btn_video),
            (tr("merge.subtitle_file") + ":", self.ed_sub, self.btn_sub),
            (tr("merge.output") + ":", self.ed_out, self.btn_out),
        ):
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(btn)
            form.addRow(label, row)
        root.addLayout(form)

        # ---- خيارات ----
        opts = QHBoxLayout()
        self.cb_lang = QComboBox()
        for code, _c2, name in LANGUAGES:
            self.cb_lang.addItem(name, code)
        idx = self.cb_lang.findData("ara")
        if idx >= 0:
            self.cb_lang.setCurrentIndex(idx)
        a11y(self.cb_lang, tr("merge.subtitle_file"), "Language code for the new track")
        opts.addWidget(QLabel(tr("sub.language") + ":"))
        opts.addWidget(self.cb_lang)

        self.ed_title = QLineEdit()
        a11y(self.ed_title, "Track title", "Optional title for the subtitle track")
        opts.addWidget(QLabel(tr("search.release") + ":"))
        opts.addWidget(self.ed_title, 1)
        root.addLayout(opts)

        self.chk_copy_audio = QCheckBox(tr("merge.copy_audio"))
        self.chk_copy_audio.setChecked(True)
        a11y(self.chk_copy_audio, tr("merge.copy_audio"), tr("merge.copy_audio"))
        root.addWidget(self.chk_copy_audio)

        self.chk_default = QCheckBox("Set as default subtitle track")
        self.chk_default.setChecked(True)
        root.addWidget(self.chk_default)

        self.chk_keep = QCheckBox(tr("merge.keep_original"))
        self.chk_keep.setChecked(bool(self.cfg.get("keep_original_on_merge")))
        root.addWidget(self.chk_keep)

        # ---- تقدّم ----
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setVisible(False)
        a11y(self.txt_log, "Merge log", "Technical log of the merge operation")
        root.addWidget(self.txt_log, 1)

        self.lbl_status = QLabel("")
        a11y(self.lbl_status, "Merge status", "Current merge status")
        root.addWidget(self.lbl_status)

        # ---- أزرار ----
        actions = QHBoxLayout()
        self.btn_start = make_button(tr("merge.start"), tr("merge.start"),
                                     tr("merge.start"), "Ctrl+Return")
        self.btn_start.clicked.connect(self.start_merge)
        self.btn_start.setDefault(True)
        self.btn_close = make_button(tr("close"), tr("close"), tr("close"), "Esc")
        self.btn_close.clicked.connect(self.reject)
        actions.addWidget(self.btn_start)
        actions.addStretch(1)
        actions.addWidget(self.btn_close)
        root.addLayout(actions)

        self.live = LiveRegion()
        self.live.setParent(self)
        if video_path:
            self._suggest_output(video_path)

    # ------------------------------------------------------------ اختيار الملفات
    def _pick_video(self) -> None:
        start = str(Path(self.ed_video.text()).parent) if self.ed_video.text() else ""
        p, _ = QFileDialog.getOpenFileName(self, self.tr("merge.select_video"), start,
                                           VIDEO_FILTER)
        if p:
            self.ed_video.setText(p)
            self._suggest_output(p)

    def _pick_sub(self) -> None:
        start = str(Path(self.ed_video.text()).parent) if self.ed_video.text() else ""
        p, _ = QFileDialog.getOpenFileName(self, self.tr("merge.select_sub"), start,
                                           SUB_FILTER)
        if p:
            self.ed_sub.setText(p)
            code = subtitle_merger.detect_lang(p)
            idx = self.cb_lang.findData(code)
            if idx >= 0:
                self.cb_lang.setCurrentIndex(idx)

    def _suggest_output(self, video: str) -> None:
        sub = self.ed_sub.text().strip()
        if sub:
            out = subtitle_merger.default_output_path(video, sub)
        else:
            v = Path(video)
            out = v.with_name(f"{v.stem} [Amp-sub]{v.suffix or '.mkv'}")
        self.ed_out.setText(str(out))

    def _pick_out(self) -> None:
        cur = self.ed_out.text() or self.ed_video.text()
        start = str(Path(cur).parent) if cur else ""
        p, _ = QFileDialog.getSaveFileName(self, self.tr("merge.select_output"), start,
                                           VIDEO_FILTER)
        if p:
            self.ed_out.setText(p)

    def _pick_ffmpeg(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self, self.tr("deps.browse_ffmpeg"), "", "ffmpeg.exe (*.exe)"
        )
        if p:
            self.cfg.set("ffmpeg_path", p)
            self.cfg.sync()
            self.lbl_deps.setText(f"{self.tr('deps.ffmpeg_ok')}: {p}")

    # ------------------------------------------------------------ الدمج
    def start_merge(self) -> None:
        video = self.ed_video.text().strip()
        sub = self.ed_sub.text().strip()
        out = self.ed_out.text().strip()
        if not video or not sub:
            self.live.announce(self.tr("merge.need_both"))
            QMessageBox.warning(self, self.tr("merge.title"), self.tr("merge.need_both"))
            return
        if not out:
            self._suggest_output(video)
            out = self.ed_out.text().strip()
        if not media_probe.has_ffmpeg():
            self.live.announce(self.tr("merge.needs_ffmpeg"))
            QMessageBox.warning(self, self.tr("merge.title"), self.tr("merge.needs_ffmpeg"))
            return
        if Path(out).resolve() == Path(video).resolve():
            self.live.announce(self.tr("merge.same_file"))
            QMessageBox.warning(self, self.tr("merge.title"), self.tr("merge.same_file"))
            return

        self.btn_start.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setVisible(True)
        self.txt_log.setVisible(True)
        self.txt_log.clear()
        self.lbl_status.setText(self.tr("merge.merging"))
        self.live.announce(self.tr("merge.merging"))

        self.worker = _MergeWorker(
            video=video, sub=sub, out=out,
            lang=self.cb_lang.currentData() or "",
            title=self.ed_title.text().strip(),
            copy_audio=self.chk_copy_audio.isChecked(),
            default_track=self.chk_default.isChecked(),
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_ok)
        self.worker.finished_err.connect(self._on_err)
        self.worker.start()

    def _on_progress(self, pct: int, stage: str) -> None:
        self.progress.setValue(pct)
        self.txt_log.append(f"[{stage}] {pct}%")

    def _on_ok(self, output: str) -> None:
        self.progress.setVisible(False)
        self.btn_start.setEnabled(True)
        msg = self.tr("merge.done", path=output)
        self.lbl_status.setText(msg)
        self.live.announce(msg)
        QMessageBox.information(self, self.tr("merge.title"), msg)

    def _on_err(self, err: str) -> None:
        self.progress.setVisible(False)
        self.btn_start.setEnabled(True)
        msg = f"{self.tr('merge.failed')}: {err}"
        self.lbl_status.setText(msg)
        self.txt_log.append(msg)
        self.live.announce(msg)
        QMessageBox.warning(self, self.tr("merge.title"), msg)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(2000)
        super().closeEvent(event)