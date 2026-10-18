"""نافذة التفضيلات."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import config, i18n
from .widgets import a11y, make_button


class PreferencesDialog(QDialog):
    """إعدادات البرنامج."""

    def __init__(self, parent, tr: i18n.Translator, cfg: config.Config) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.tr = tr
        self.setWindowTitle(tr("prefs.title"))
        self.setWindowIcon(parent.windowIcon())
        self.setModal(True)
        self.resize(700, 620)
        self.setAccessibleName(tr("prefs.title"))
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if tr.is_rtl()
            else Qt.LayoutDirection.LeftToRight
        )
        self._build()

    def _build(self) -> None:
        tr = self.tr
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        a11y(tabs, "Preferences tabs", "Use left and right arrows to switch tabs")
        root.addWidget(tabs, 1)

        # ================= عام =================
        g1 = QWidget()
        f1 = QFormLayout(g1)
        self.chk_autoplay = QCheckBox(tr("prefs.autoplay_next"))
        self.chk_autoplay.setChecked(bool(self.cfg.get("autoplay_next")))
        f1.addRow(self.chk_autoplay)

        self.chk_remember = QCheckBox(tr("prefs.remember_pos"))
        self.chk_remember.setChecked(bool(self.cfg.get("remember_position")))
        f1.addRow(self.chk_remember)

        # عدد خيوط فك الترميز. FFmpeg يوزّع العمل بينها، وهذا ما يجعل
        # الفيديو بدقة 4K سلساً على المعالجات متعددة النواة.
        self.sp_threads = QSpinBox()
        self.sp_threads.setRange(0, 32)
        self.sp_threads.setSpecialValueText(tr("prefs.decode_auto"))
        self.sp_threads.setValue(int(self.cfg.get("decode_threads") or 0))
        self.sp_threads.setAccessibleName(tr("prefs.decode_threads"))
        self.sp_threads.setToolTip(tr("prefs.decode_threads_hint"))
        f1.addRow(tr("prefs.decode_threads") + ":", self.sp_threads)

        # جهاز الإخراج الصوتي: بعض الأجهزة (بلوتوث/وهمية) تقطّع، فيُغيّر
        # المستخدم الجهاز من هنا دون فتح لوحة تحكم ويندوز.
        self.cb_device = QComboBox()
        self.cb_device.addItem(tr("prefs.audio_default"), -1)
        self._devices = self._output_devices()
        for idx, name in self._devices:
            self.cb_device.addItem(name, idx)
        sel = self.cb_device.findData(int(self.cfg.get("audio_device") or -1))
        self.cb_device.setCurrentIndex(sel if sel >= 0 else 0)
        a11y(self.cb_device, tr("prefs.audio_device"), tr("prefs.audio_device_hint"))
        f1.addRow(tr("prefs.audio_device") + ":", self.cb_device)

        self.chk_loop = QCheckBox("Loop playlist")
        self.chk_loop.setChecked(bool(self.cfg.get("loop_playlist")))
        f1.addRow(self.chk_loop)

        self.chk_auto_search = QCheckBox(tr("prefs.auto_sub_search"))
        self.chk_auto_search.setChecked(bool(self.cfg.get("sub_auto_search_if_missing")))
        f1.addRow(self.chk_auto_search)

        tabs.addTab(g1, tr("prefs.tabs.general"))

        # ================= لغة =================
        g2 = QWidget()
        f2 = QFormLayout(g2)
        self.cb_lang = QComboBox()
        self.cb_lang.addItem("العربية", "ar")
        self.cb_lang.addItem("English", "en")
        idx = self.cb_lang.findData(self.cfg.lang)
        if idx >= 0:
            self.cb_lang.setCurrentIndex(idx)
        a11y(self.cb_lang, tr("prefs.language"), tr("prefs.language"))
        f2.addRow(tr("prefs.language") + ":", self.cb_lang)

        self.chk_rtl = QCheckBox(tr("prefs.rtl"))
        self.chk_rtl.setChecked(bool(self.cfg.get("rtl")))
        f2.addRow(self.chk_rtl)

        lbl = QLabel(tr("prefs.restart_required"))
        lbl.setStyleSheet("color: #777777;")
        f2.addRow(lbl)
        tabs.addTab(g2, tr("prefs.tabs.language"))

        # ================= ترجمة =================
        g3 = QWidget()
        f3 = QFormLayout(g3)
        self.chk_sidecar = QCheckBox(tr("sub.auto_load"))
        self.chk_sidecar.setChecked(bool(self.cfg.get("sub_auto_load_sidecar")))
        f3.addRow(self.chk_sidecar)

        self.chk_onscreen = QCheckBox(tr("sub.on_screen"))
        self.chk_onscreen.setChecked(bool(self.cfg.get("sub_show_on_screen")))
        f3.addRow(self.chk_onscreen)

        self.chk_pause_line = QCheckBox(tr("sub.pause_on_line"))
        self.chk_pause_line.setChecked(bool(self.cfg.get("sub_pause_on_line")))
        f3.addRow(self.chk_pause_line)

        self.chk_panel = QCheckBox(tr("sub.panel_title"))
        self.chk_panel.setChecked(bool(self.cfg.get("sub_panel_visible")))
        f3.addRow(self.chk_panel)

        self.sp_size = QSpinBox()
        self.sp_size.setRange(12, 80)
        self.sp_size.setValue(int(self.cfg.get("sub_font_size") or 34))
        a11y(self.sp_size, tr("sub.size"), "Subtitle font size in pixels")
        f3.addRow(tr("sub.size") + ":", self.sp_size)

        self.cb_pos = QComboBox()
        self.cb_pos.addItem("Bottom", "bottom")
        self.cb_pos.addItem("Top", "top")
        idx = self.cb_pos.findData(str(self.cfg.get("sub_position")))
        if idx >= 0:
            self.cb_pos.setCurrentIndex(idx)
        f3.addRow(tr("sub.force_position") + ":", self.cb_pos)

        self.sp_opacity = QSpinBox()
        self.sp_opacity.setRange(0, 100)
        self.sp_opacity.setValue(int(self.cfg.get("sub_background_opacity") or 0))
        a11y(self.sp_opacity, tr("sub.background_opacity"), "0 = fully opaque")
        f3.addRow(tr("sub.background_opacity") + ":", self.sp_opacity)

        self.sp_repeat = QSpinBox()
        self.sp_repeat.setRange(0, 5)
        self.sp_repeat.setValue(int(self.cfg.get("sub_repeat_last") or 0))
        a11y(self.sp_repeat, tr("sub.lines_count"),
             "How many times to repeat a subtitle line")
        f3.addRow(tr("sub.lines_count") + ":", self.sp_repeat)

        # وضع اختيار مصدر الترجمة (تلقائي/يدوي)
        self.cb_src_mode = QComboBox()
        self.cb_src_mode.addItem(tr("src.mode_auto"), "auto")
        self.cb_src_mode.addItem(tr("src.mode_manual"), "manual")
        idx = self.cb_src_mode.findData(str(self.cfg.get("sub_source_mode") or "auto"))
        if idx >= 0:
            self.cb_src_mode.setCurrentIndex(idx)
        a11y(self.cb_src_mode, tr("prefs.src_mode"), tr("sub.source"))
        f3.addRow(tr("prefs.src_mode") + ":", self.cb_src_mode)
        tabs.addTab(g3, tr("prefs.tabs.subtitles"))

        # ================= sites =================
        g4 = QWidget()
        v4 = QVBoxLayout(g4)
        v4.addWidget(QLabel(tr("prefs.sites")))
        self.lst_sites = QListWidget()
        self.lst_sites.setAccessibleName(tr("prefs.sites"))
        self.lst_sites.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        from ..providers import manager

        enabled = set(manager.enabled_sites(self.cfg))
        for site in manager.SITE_ORDER:
            item = QListWidgetItem(manager.site_display_name(site))
            item.setData(Qt.ItemDataRole.UserRole, site)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if site in enabled else Qt.CheckState.Unchecked
            )
            item.setToolTip(manager.site_home(site))
            self.lst_sites.addItem(item)
        v4.addWidget(self.lst_sites, 1)

        row_key = QHBoxLayout()
        row_key.addWidget(QLabel("OpenSubtitles API key:"))
        self.ed_os_key = QLineEdit()
        from ..providers import opensubtitles_provider as osp

        self.ed_os_key.setText(osp._load_key())
        self.ed_os_key.setEchoMode(QLineEdit.EchoMode.Password)
        a11y(self.ed_os_key, "OpenSubtitles API key",
             "Optional. Search works without it; the key enables the "
             "modern API as a fallback.")
        row_key.addWidget(self.ed_os_key, 1)
        v4.addLayout(row_key)

        lbl_key = QLabel(
            "Optional. OpenSubtitles is searched without a key by default "
            "(legacy API). A key only adds api.opensubtitles.com as a fallback "
            "→ https://www.opensubtitles.com/en/consumers"
        )
        lbl_key.setWordWrap(True)
        lbl_key.setStyleSheet("color: #777777;")
        v4.addWidget(lbl_key)
        tabs.addTab(g4, "Sites")

        # ================= صوت =================
        g5 = QWidget()
        f5 = QFormLayout(g5)
        self.chk_tts = QCheckBox(tr("menu.voice_tts"))
        self.chk_tts.setChecked(bool(self.cfg.get("tts_enabled")))
        f5.addRow(self.chk_tts)

        self.sp_rate = QSpinBox()
        self.sp_rate.setRange(50, 400)
        self.sp_rate.setValue(int(self.cfg.get("tts_rate") or 175))
        a11y(self.sp_rate, tr("prefs.speech_rate"), "Words per minute")
        f5.addRow(tr("prefs.speech_rate") + ":", self.sp_rate)

        self.sp_vol = QSpinBox()
        self.sp_vol.setRange(0, 100)
        self.sp_vol.setValue(int(self.cfg.get("tts_volume") or 100))
        a11y(self.sp_vol, tr("prefs.speech_volume"), "0 to 100")
        f5.addRow(tr("prefs.speech_volume") + ":", self.sp_vol)

        self.cb_voice = QComboBox()
        from ..speech import speaker as _speaker

        self._voices: list[tuple[str, str]] = []
        if _speaker.available:
            self._voices = _speaker.voices()
        self.cb_voice.addItem("Default", "")
        for vid, vname in self._voices:
            self.cb_voice.addItem(vname, vid)
        idx = self.cb_voice.findData(str(self.cfg.get("tts_voice") or ""))
        if idx >= 0:
            self.cb_voice.setCurrentIndex(idx)
        a11y(self.cb_voice, tr("prefs.speech_voice"), "Text-to-speech voice")
        f5.addRow(tr("prefs.speech_voice") + ":", self.cb_voice)

        self.cb_engine = QComboBox()
        for val, key in (("auto", "engine.auto"),
                         ("nvda", "engine.nvda"),
                         ("system", "engine.system")):
            self.cb_engine.addItem(tr(key), val)
        idx = self.cb_engine.findData(str(self.cfg.get("tts_engine") or "auto"))
        if idx >= 0:
            self.cb_engine.setCurrentIndex(idx)
        a11y(self.cb_engine, tr("prefs.speech_engine"), "nvda or system voice")
        f5.addRow(tr("prefs.speech_engine") + ":", self.cb_engine)
        lbl_note = QLabel(tr("engine.voice_note"))
        lbl_note.setStyleSheet("color: #777777;")
        lbl_note.setWordWrap(True)
        f5.addRow(lbl_note)

        self.chk_ann_sub = QCheckBox(tr("prefs.announce_subtitle"))
        self.chk_ann_sub.setChecked(bool(self.cfg.get("tts_announce_subtitle")))
        f5.addRow(self.chk_ann_sub)

        self.chk_ann_state = QCheckBox(tr("prefs.announce_state"))
        self.chk_ann_state.setChecked(bool(self.cfg.get("tts_announce_state")))
        f5.addRow(self.chk_ann_state)

        self.chk_ann_vol = QCheckBox(tr("prefs.announce_volume"))
        self.chk_ann_vol.setChecked(bool(self.cfg.get("tts_announce_volume")))
        f5.addRow(self.chk_ann_vol)

        self.chk_duck = QCheckBox(tr("prefs.duck_while_speaking"))
        self.chk_duck.setChecked(bool(self.cfg.get("tts_duck_while_speaking")))
        f5.addRow(self.chk_duck)

        self.sp_duck_hold = QSpinBox()
        self.sp_duck_hold.setRange(0, 5000)
        self.sp_duck_hold.setSingleStep(100)
        self.sp_duck_hold.setSuffix(" ms")
        self.sp_duck_hold.setValue(int(self.cfg.get("tts_duck_hold_ms") or 600))
        a11y(self.sp_duck_hold, tr("prefs.duck_hold"),
             "How long volume stays lowered after speech ends")
        self.sp_duck_hold.setEnabled(bool(self.cfg.get("tts_duck_while_speaking")))
        self.chk_duck.toggled.connect(self.sp_duck_hold.setEnabled)
        f5.addRow(tr("prefs.duck_hold") + ":", self.sp_duck_hold)

        self.chk_show_log = QCheckBox(tr("prefs.show_logs"))
        self.chk_show_log.setChecked(bool(self.cfg.get("show_subtitle_log")))
        f5.addRow(self.chk_show_log)
        tabs.addTab(g5, tr("prefs.tabs.speech"))

        # ================= متقدم =================
        g6 = QWidget()
        f6 = QFormLayout(g6)
        # محرّك التشغيل لا يحتاج ضبطاً: حزمة av تحمل مكتباته معها.
        # نترك الحقل لمَن يعمل بمكتبات مستقلة فقط.
        self.ed_lib = QLineEdit(str(self.cfg.get("ffmpeg_lib_path") or ""))
        self.btn_lib = make_button(tr("browse"), "Browse FFmpeg libraries",
                                   tr("prefs.browse_ffmpeg_lib"))
        self.btn_lib.clicked.connect(self._pick_lib)
        r1 = QHBoxLayout()
        r1.addWidget(self.ed_lib, 1)
        r1.addWidget(self.btn_lib)
        f6.addRow(tr("prefs.ffmpeg_lib_path") + ":", r1)

        self.ed_ff = QLineEdit(str(self.cfg.get("ffmpeg_path") or ""))
        self.btn_ff = make_button(tr("browse"), "Browse FFmpeg",
                                  tr("prefs.browse_ffmpeg"))
        self.btn_ff.clicked.connect(self._pick_ff)
        r2 = QHBoxLayout()
        r2.addWidget(self.ed_ff, 1)
        r2.addWidget(self.btn_ff)
        f6.addRow(tr("prefs.ffmpeg_path") + ":", r2)

        self.ed_dl = QLineEdit(str(self.cfg.get("download_dir") or ""))
        self.btn_dl = make_button(tr("browse"), "Browse download folder", tr("browse"))
        self.btn_dl.clicked.connect(self._pick_dl)
        r3 = QHBoxLayout()
        r3.addWidget(self.ed_dl, 1)
        r3.addWidget(self.btn_dl)
        f6.addRow("Download folder:", r3)

        self.btn_cache = make_button(tr("prefs.open_cache"), tr("prefs.open_cache"),
                                     tr("prefs.open_cache"))
        self.btn_cache.clicked.connect(self._open_cache)
        f6.addRow(self.btn_cache)

        self.btn_reset = make_button(tr("prefs.reset"), tr("prefs.reset"),
                                     tr("prefs.reset"))
        self.btn_reset.clicked.connect(self._reset)
        f6.addRow(self.btn_reset)
        tabs.addTab(g6, tr("prefs.tabs.advanced"))

        # ================= أزرار =================
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        box.button(QDialogButtonBox.StandardButton.Save).setText(tr("save"))
        box.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("cancel"))
        box.accepted.connect(self._apply)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    # ------------------------------------------------------------ أدوات
    def _pick_lib(self) -> None:
        """يختار مجلد مكتبات FFmpeg لمن لا يريد تحميلها من الحزمة."""
        p = QFileDialog.getExistingDirectory(
            self, self.tr("prefs.browse_ffmpeg_lib"), ""
        )
        if p:
            self.ed_lib.setText(p)

    def _pick_ff(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self, self.tr("prefs.browse_ffmpeg"), "", "ffmpeg.exe (ffmpeg.exe)"
        )
        if p:
            self.ed_ff.setText(p)

    def _pick_dl(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "Download folder")
        if p:
            self.ed_dl.setText(p)

    def _open_cache(self) -> None:
        import os

        from .. import config as _c

        path = str(_c.cache_dir())
        try:
            os.startfile(path)  # noqa: S606
        except Exception:
            pass

    def _output_devices(self) -> list:
        """أجهزة الإخراج (الفهرس، الاسم). يعمل حتى لو فشل فتح الصوت."""
        try:
            from .. import av_engine

            return av_engine.output_devices()
        except Exception:
            return []

    def _reset(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        if QMessageBox.question(
            self, self.tr("prefs.reset"), self.tr("prefs.reset")
        ) == QMessageBox.StandardButton.Yes:
            self.cfg.reset_all()
            self.reject()

    # ------------------------------------------------------------ حفظ
    def _apply(self) -> None:
        c = self.cfg
        c.set("autoplay_next", self.chk_autoplay.isChecked())
        c.set("remember_position", self.chk_remember.isChecked())
        c.set("decode_threads", self.sp_threads.value())
        c.set("audio_device", int(self.cb_device.currentData() or -1))
        c.set("loop_playlist", self.chk_loop.isChecked())
        c.set("sub_auto_search_if_missing", self.chk_auto_search.isChecked())
        c.set("lang", self.cb_lang.currentData() or "ar")
        c.set("rtl", self.chk_rtl.isChecked())
        c.set("sub_auto_load_sidecar", self.chk_sidecar.isChecked())
        c.set("sub_show_on_screen", self.chk_onscreen.isChecked())
        c.set("sub_pause_on_line", self.chk_pause_line.isChecked())
        c.set("sub_panel_visible", self.chk_panel.isChecked())
        c.set("sub_font_size", self.sp_size.value())
        c.set("sub_position", self.cb_pos.currentData() or "bottom")
        c.set("sub_background_opacity", self.sp_opacity.value())
        c.set("sub_repeat_last", self.sp_repeat.value())
        c.set("sub_source_mode", self.cb_src_mode.currentData() or "auto")
        c.set("tts_enabled", self.chk_tts.isChecked())
        c.set("tts_rate", self.sp_rate.value())
        c.set("tts_volume", self.sp_vol.value())
        c.set("tts_voice", self.cb_voice.currentData() or "")
        c.set("tts_engine", self.cb_engine.currentData() or "auto")
        c.set("tts_announce_subtitle", self.chk_ann_sub.isChecked())
        c.set("tts_announce_state", self.chk_ann_state.isChecked())
        c.set("tts_announce_volume", self.chk_ann_vol.isChecked())
        c.set("tts_duck_while_speaking", self.chk_duck.isChecked())
        c.set("tts_duck_hold_ms", self.sp_duck_hold.value())
        c.set("show_subtitle_log", self.chk_show_log.isChecked())
        c.set("ffmpeg_lib_path", self.ed_lib.text().strip())
        c.set("ffmpeg_path", self.ed_ff.text().strip())
        c.set("download_dir", self.ed_dl.text().strip())

        # المواقع المفعّلة
        enabled = []
        for i in range(self.lst_sites.count()):
            item = self.lst_sites.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                enabled.append(item.data(Qt.ItemDataRole.UserRole))
        c.set("sites_enabled_list", enabled)
        for site in enabled:
            c.set(f"sites_{site}", True)
        for site in ("opensubtitles", "subdl", "yifysubtitles", "tvsubtitles"):
            if site not in enabled:
                c.set(f"sites_{site}", False)

        # مفتاح OpenSubtitles
        from ..providers import opensubtitles_provider as osp

        osp.save_key(self.ed_os_key.text().strip())

        c.sync()
        self.accept()