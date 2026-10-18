"""نافذة فحص المتطلبات (محرّك FFmpeg المدمج / FFmpeg الاختياري / قارئ الصوت)."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

from .. import av_engine, config, i18n, media_probe
from .widgets import LiveRegion, a11y, make_button

PIP_URL = "https://pypi.org/project/av/"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/"


class _DownloadWorker(QThread):
    """ينزّل حزمة ثنائية حرة (FFmpeg) للتوزيع مستقلة."""

    progress = Signal(int, str)
    finished_ok = Signal(str)
    finished_err = Signal(str)

    def __init__(self, url: str, dest_zip: Path) -> None:
        super().__init__()
        self.url = url
        self.dest = dest_zip
        self._abort = False

    def run(self) -> None:
        import requests

        try:
            self.progress.emit(0, "starting")
            with requests.get(self.url, stream=True, timeout=60,
                              headers={"User-Agent": "AmpPlayer"}) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                with open(self.dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=262_144):
                        if self._abort:
                            break
                        if chunk:
                            f.write(chunk)
                            got += len(chunk)
                            pct = int(got / total * 100) if total else 0
                            self.progress.emit(pct, "downloading")
            self.progress.emit(100, "extracting")
            self.finished_ok.emit(str(self.dest))
        except Exception as exc:
            self.finished_err.emit(str(exc))


class RequirementsDialog(QDialog):
    """يعرض حالة المتطلبات ويساعد في تثبيتها."""

    def __init__(self, parent, tr: i18n.Translator, cfg: config.Config) -> None:
        super().__init__(parent)
        self.tr = tr
        self.cfg = cfg
        self.worker: Optional[_DownloadWorker] = None
        self.setWindowTitle(tr("deps.title"))
        self.setWindowIcon(parent.windowIcon())
        self.setModal(True)
        self.resize(640, 520)
        self.setAccessibleName(tr("deps.title"))
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if tr.is_rtl()
            else Qt.LayoutDirection.LeftToRight
        )
        self._build()

    def _build(self) -> None:
        tr = self.tr
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setFont(self.font())
        a11y(self.lbl_summary, "Requirements summary", "Overall status")
        root.addWidget(self.lbl_summary)

        # ---- محرّك FFmpeg ----
        self.box_engine = QLabel("")
        self.box_engine.setWordWrap(True)
        self.box_engine.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        a11y(self.box_engine, "Media engine status",
             "Whether the bundled FFmpeg media engine is available")
        root.addWidget(self.box_engine)
        self.row_engine = QHBoxLayout()
        self.btn_engine_site = make_button(tr("open"), "Open the FFmpeg download page",
                                        tr("deps.engine_hint"))
        self.btn_engine_site.clicked.connect(lambda: webbrowser.open(PIP_URL))
        self.btn_engine_path = make_button(tr("deps.browse"),
                                        "Locate the media engine manually",
                                        tr("deps.browse"))
        self.btn_engine_path.clicked.connect(self._pick_engine)
        self.row_engine.addWidget(self.btn_engine_site)
        self.row_engine.addWidget(self.btn_engine_path)
        self.row_engine.addStretch(1)
        root.addLayout(self.row_engine)

        # ---- محرّك mpv (الاختياري الجديد) ----
        self.box_mpv = QLabel("")
        self.box_mpv.setWordWrap(True)
        self.box_mpv.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        a11y(self.box_mpv, "mpv engine status",
             "Whether the bundled mpv playback engine is available")
        root.addWidget(self.box_mpv)

        # ---- FFmpeg ----
        self.box_ff = QLabel("")
        self.box_ff.setWordWrap(True)
        self.box_ff.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        a11y(self.box_ff, "FFmpeg status", "Whether FFmpeg is available")
        root.addWidget(self.box_ff)
        self.row_ff = QHBoxLayout()
        self.btn_ff_site = make_button(tr("open"), "Open FFmpeg website",
                                       tr("deps.ffmpeg_hint"))
        self.btn_ff_site.clicked.connect(lambda: webbrowser.open(FFMPEG_URL))
        self.btn_ff_path = make_button(tr("deps.browse"), "Locate FFmpeg manually",
                                       tr("deps.browse"))
        self.btn_ff_path.clicked.connect(self._pick_ff)
        self.btn_ff_dl = make_button(tr("deps.download_ffmpeg"), tr("deps.download_ffmpeg"),
                                     tr("deps.download_ffmpeg"))
        self.btn_ff_dl.clicked.connect(self._download_ffmpeg)
        self.row_ff.addWidget(self.btn_ff_site)
        self.row_ff.addWidget(self.btn_ff_path)
        self.row_ff.addWidget(self.btn_ff_dl)
        self.row_ff.addStretch(1)
        root.addLayout(self.row_ff)

        # ---- TTS ----
        self.box_tts = QLabel("")
        self.box_tts.setWordWrap(True)
        a11y(self.box_tts, "Speech engine status", "Whether text-to-speech is available")
        root.addWidget(self.box_tts)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        root.addStretch(1)

        # ---- أزرار ----
        actions = QHBoxLayout()
        self.btn_recheck = make_button(tr("retry"), tr("retry"), "Check again", "F5")
        self.btn_recheck.clicked.connect(self.refresh)
        self.btn_close = make_button(tr("close"), tr("close"), tr("close"), "Esc")
        self.btn_close.clicked.connect(self.accept)
        actions.addWidget(self.btn_recheck)
        actions.addStretch(1)
        actions.addWidget(self.btn_close)
        root.addLayout(actions)

        self.live = LiveRegion()
        self.live.setParent(self)
        self.refresh()

    # ------------------------------------------------------------ الفحص
    def refresh(self) -> None:
        tr = self.tr
        ok, err = av_engine.av_available()
        ver = av_engine.av_version()
        sd, sd_err = av_engine._import_sounddevice()  # noqa: SLF001
        ff = media_probe.ffmpeg_path()
        from ..speech_worker import tts_available

        tts_ok = tts_available()

        # محرّك التشغيل
        if ok and sd is not None:
            detail = f"{tr('deps.version')} {ver}" if ver else ""
            extra = f"{tr('deps.audio_device_ok')}"
            self.box_engine.setText(
                f"✔ {tr('deps.engine_ok')}\n" + (f"{detail}\n" if detail else "") + extra
            )
            self.box_engine.setStyleSheet("color: #1a7f37;")
            self.btn_engine_site.setEnabled(False)
            self.btn_engine_path.setEnabled(True)
        elif ok:
            # FFmpeg موجود لكن لا جهاز صوت: نقولها بوضوح ولا نُبطل التشغيل
            self.box_engine.setText(
                f"✔ {tr('deps.engine_ok')}  ({tr('deps.version')} {ver})\n"
                f"⚠ {tr('deps.audio_device_missing')}\n{sd_err[:160]}"
            )
            self.box_engine.setStyleSheet("color: #b8860b;")
            self.btn_engine_site.setEnabled(False)
            self.btn_engine_path.setEnabled(True)
        else:
            self.box_engine.setText(
                f"✘ {tr('deps.engine_missing')}\n{tr('deps.engine_hint')}\n{err[:200]}"
            )
            self.box_engine.setStyleSheet("color: #b42318;")
            self.btn_engine_site.setEnabled(True)
            self.btn_engine_path.setEnabled(True)

        # mpv (يُفضَّل؛ وعند غيابه يستخدم البرنامج FFmpeg تلقائياً)
        from ..mpv_engine import mpv_ready

        mpv_ok, mpv_note = mpv_ready()
        if mpv_ok:
            self.box_mpv.setText(f"✔ {tr('deps.mpv_ok')}\n{mpv_note}")
            self.box_mpv.setStyleSheet("color: #1a7f37;")
        else:
            self.box_mpv.setText(
                f"✘ {tr('deps.mpv_missing')}\n{mpv_note}"
            )
            self.box_mpv.setStyleSheet("color: #777777;")

        # FFmpeg
        if ff:
            self.box_ff.setText(f"✔ {tr('deps.ffmpeg_ok')}\n{tr('deps.path')}: {ff}")
            self.box_ff.setStyleSheet("color: #1a7f37;")
            self.btn_ff_dl.setEnabled(False)
        else:
            self.box_ff.setText(
                f"✘ {tr('deps.ffmpeg_missing')}\n{tr('deps.ffmpeg_hint')}\n"
                f"{tr('deps.copy_hint')}"
            )
            self.box_ff.setStyleSheet("color: #b8860b;")
            self.btn_ff_dl.setEnabled(True)

        # TTS
        if tts_ok:
            self.box_tts.setText(f"✔ {tr('deps.tts_ok')}")
            self.box_tts.setStyleSheet("color: #1a7f37;")
        else:
            self.box_tts.setText(f"✘ {tr('deps.tts_missing')}")
            self.box_tts.setStyleSheet("color: #777777;")

        # ملخص: FFmpeg الاختياري لا يمنع التشغيل، فنذكره بلا علامة خطأ قاتل
        if ok and tts_ok:
            head = "✔ " + tr("deps.all_ok")
            self.lbl_summary.setText(head)
            self.lbl_summary.setStyleSheet("color: #1a7f37; font-weight: bold;")
        else:
            missing = []
            if not ok:
                missing.append("FFmpeg")
            if sd is None:
                missing.append(tr("deps.audio_device"))
            if not tts_ok:
                missing.append("TTS")
            self.lbl_summary.setText("✘ " + ", ".join(missing))
            self.lbl_summary.setStyleSheet("color: #b42318; font-weight: bold;")
        if not ff:
            self.lbl_summary.setText(
                self.lbl_summary.text() + "  — " + tr("deps.ffmpeg_hint")
            )

        self.live.announce(self.lbl_summary.text())

    # ------------------------------------------------------------ التثبيت
    def _pick_engine(self) -> None:
        """
        يختار ملف مكتبة FFmpeg يدوياً.

        PyAV يبحث عن مكتباته داخل الحزمة نفسها، فلا يحتاج هذا عادةً. نُبقيه
        لمن يعمل بمكتبات مستقلة أو نسخة مخصّصة.
        """
        p, _ = QFileDialog.getOpenFileName(
            self, self.tr("deps.browse"), "",
            "FFmpeg libraries (*.dll *.so *.dylib *.lib);;All files (*)",
        )
        if p:
            self.cfg.set("ffmpeg_lib_path", p)
            self.cfg.sync()
            self.refresh()

    def _pick_ff(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, self.tr("deps.browse"),
                                           "", "ffmpeg.exe (*.exe)")
        if p:
            self.cfg.set("ffmpeg_path", p)
            self.cfg.sync()
            self.refresh()

    def _download_ffmpeg(self) -> None:
        """ينزّل نسخة FFmpeg محمولة إلى مجلد الأدوات."""
        self.btn_ff_dl.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setVisible(True)
        self.live.announce(self.tr("deps.downloading"))
        dest = Path(config.app_data_dir()) / "tools"
        dest.mkdir(parents=True, exist_ok=True)
        zip_path = dest / "ffmpeg.zip"
        # رابط حزمة ثابتة (نواة Windows 64-bit)
        url = (
            "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
            "latest/ffmpeg-master-latest-win64-gpl.zip"
        )
        self.worker = _DownloadWorker(url, zip_path)
        self.worker.progress.connect(self._on_dl_progress)
        self.worker.finished_ok.connect(self._on_dl_ok)
        self.worker.finished_err.connect(self._on_dl_err)
        self.worker.start()

    def _on_dl_progress(self, pct: int, stage: str) -> None:
        self.progress.setValue(pct)

    def _on_dl_ok(self, zip_path: str) -> None:
        import zipfile

        self.progress.setVisible(False)
        tools = Path(config.app_data_dir()) / "tools"
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for name in zf.namelist():
                    base = Path(name).name
                    if base in ("ffmpeg.exe", "ffprobe.exe"):
                        target = tools / base
                        with zf.open(name) as src, open(target, "wb") as dst:
                            dst.write(src.read())
            Path(zip_path).unlink(missing_ok=True)
            self.cfg.set("ffmpeg_path", str(tools / "ffmpeg.exe"))
            self.cfg.sync()
            self.live.announce(self.tr("deps.download_done"))
            self.refresh()
        except Exception as exc:
            self.live.announce(str(exc))

    def _on_dl_err(self, err: str) -> None:
        self.progress.setVisible(False)
        self.btn_ff_dl.setEnabled(True)
        self.live.announce(f"{self.tr('error.generic', msg=err)}")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(2000)
        super().closeEvent(event)