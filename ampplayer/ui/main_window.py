"""النافذة الرئيسية لبرنامج Amp Player."""

from __future__ import annotations

import re
import webbrowser
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QByteArray, QObject, QStandardPaths, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import (
    __version__,
    av_engine,
    config,
    contact,
    i18n,
    media_probe,
    subtitle_manager,
    subtitle_text,
    youtube_subs,
)
from .. import embedded_subs
from ..player import PlayerController
from ..speech_worker import SpeechController
from ..subtitle_engine import SubtitleEngine
from ..subtitle_manager import SourceKind, SubtitleManager
from ..subtitle_parser import Cue, format_duration, sidecar_candidates
from .widgets import LiveRegion, VolumeSlider, a11y, make_button, make_slider

MEDIA_EXTENSIONS = (
    "mkv mp4 avi mov m4v webm wmv flv ts m2ts mpg mpeg 3gp ogv vob "
    "mp3 m4a aac flac wav ogg opus wma aiff ape alac"
).split()

MEDIA_FILTER = (
    "Media files (" + " ".join("." + e for e in MEDIA_EXTENSIONS) + ");;"
    "All files (*.*)"
)
SUB_EXTENSIONS = "srt vtt ass ssa sub sami smi txt".split()

SUB_FILTER = (
    "Subtitle files (" + " ".join("." + e for e in SUB_EXTENSIONS) + ");;"
    "All files (*.*)"
)


class PlaylistItem:
    __slots__ = ("path", "title", "is_url")

    def __init__(self, path: str, title: str = "", is_url: bool = False) -> None:
        self.path = path
        self.title = title or Path(path).stem
        self.is_url = is_url


class _AutoSubtitleWorker(QObject):
    """
    بحث تلقائي عن ترجمة عند فتح فيلم بلا ملف ترجمة خارجي.

    يعمل في خيط خلفي حتى لا تتجمد الواجهة، ويُكمل البحث والتحميل
    ثم يُرسل مسار ملف الترجمة (أو نصاً فارغاً إن لم يُعثر على شيء).
    """

    done = Signal(str)

    def __init__(self, path: str, lang: str) -> None:
        super().__init__()
        self.path = path
        self.lang = lang or "ara"

    def run(self) -> None:
        try:
            p = self._work()
        except Exception:
            p = None
        self.done.emit(str(p) if p else "")

    def _work(self) -> Optional[str]:
        from ..providers import manager

        stem = Path(self.path).stem
        season = episode = ""
        m = re.search(r"[Ss](\d{1,2})[Ee](\d{1,3})", stem)
        query = stem
        if m:
            season, episode = m.group(1), m.group(2)
            query = re.sub(r"[Ss]\d{1,2}[Ee]\d{1,3}.*$", "", stem).strip() or stem
        outcomes = manager.search_all(
            query=query, lang=self.lang,
            season=season, episode=episode, timeout=12,
        )
        best = self._pick(manager.flatten(outcomes))
        if best is None:
            return None
        return manager.download(best, timeout=40)

    def _pick(self, results):
        """يفضّل العربية وبقية أشكالها، ثم الأعلى تحميلاً. وإلا أي نتيجة قابلة للتحميل."""
        aliases = {self.lang.lower(), "ara", "ar", "arb", "عربي"}
        pool = [
            r for r in results
            if (r.language_code or r.language or "").lower() in aliases
            and (r.download_url or r.url)
        ]
        if not pool:
            pool = [r for r in results if (r.download_url or r.url)]
        if not pool:
            return None
        pool.sort(
            key=lambda r: (int(r.downloads or 0), float(r.rating or 0.0)),
            reverse=True,
        )
        return pool[0]


class _EmbeddedCuesWorker(QObject):
    """
    يستخرج أسطر مسار ترجمة مدمج في خيط خلفي (PyAV) ثم يُرسلها إلى الواجهة.

    الاستخراج يقرأ حزم الترجمة وحدها فهو سريع، لكنه يمرّ على الملف كاملاً
    فلا نجريه في خيط الواجهة.
    """

    done = Signal(str, int, object)   # المسار، فهرس التيار، قائمة Cue

    def __init__(self, path: str, stream_index: int) -> None:
        super().__init__()
        self.path = path
        self.stream_index = int(stream_index)

    def run(self) -> None:
        try:
            cues = embedded_subs.extract_embedded_cues(self.path, self.stream_index)
        except Exception:
            cues = []
        self.done.emit(self.path, self.stream_index, cues)


class MainWindow(QMainWindow):
    """النافذة الرئيسية."""

    def __init__(self) -> None:
        super().__init__()
        self.cfg = config.Config()
        self.tr = i18n.Translator(self.cfg.lang)
        self.engine = SubtitleEngine(self)
        self.player = PlayerController(self)
        self.speech = SpeechController(self)

        self.playlist: list[PlaylistItem] = []
        self.current_index: int = -1
        self.current_path: str = ""
        self.media_info: Optional[media_probe.MediaInfo] = None
        self._seeking = False
        self._loading_media = False
        self._fullscreen = False
        self._probe_thread_result: Optional[media_probe.MediaInfo] = None
        # هل اختار المستخدم ملف ترجمة خارجياً لهذا الملف؟
        self._sidecar_loaded = False
        # آخر سطر ترجمة حي نطقناه من mpv (لمنع تكرار النطق)
        self._last_live_sub = ""
        # بحث تلقائي عن ترجمة عند فتح فيلم بلا ترجمة (إعداد sub_auto_search_if_missing)
        self._auto_search_busy = False
        self._auto_search_path = ""
        self._auto_thread: Optional[QThread] = None

        # ------- مصادر الترجمة -------
        # مدير يضمن أن مصدراً واحداً فقط يقرأ (خارجي أو بعيد)
        self.sub_mgr = SubtitleManager(str(self.cfg.get("sub_source_mode") or "auto"))
        # سياسة النطق: تمنع تكرار السطر وتُسقط القديم بدل تكديسه
        self.speak_policy = subtitle_manager.SpeakPolicy(
            stale_seconds=float(self.cfg.get("sub_repeat_last") or 2) + 2.0
        )
        # خطّ الترجمة المحمّل حالياً لاستعادته عند تبديل المصدر
        self._text_cues: list[Cue] = []
        self._text_name = ""
        self._text_path = ""
        self._text_origin: Optional[SourceKind] = None
        self._yt_busy = False
        self._active_kind: Optional[SourceKind] = None
        self._last_spoken_text = ""
        # ------- الترجمة المدمجة داخل الفيديو -------
        self._emb_tracks: list[embedded_subs.EmbeddedTrack] = []
        self._emb_selected_index: Optional[int] = None   # فهرس تيار FFmpeg
        self._emb_auto = True                            # اختيار المسار تلقائي؟
        self._emb_cues: list[Cue] = []
        self._emb_name = ""
        self._emb_thread: Optional[QThread] = None
        self._emb_job: Optional[tuple] = None            # (المسار، الفهرس) الجاري
        self._emb_group: Optional[QActionGroup] = None

        self.setWindowTitle(self.tr("app.title"))
        self.setAcceptDrops(True)
        self.resize(1150, 780)
        self.setMinimumSize(720, 480)

        self._build_ui()
        self._build_menus()
        self._bind_keys()
        self._build_statusbar()
        self._apply_language()
        self._restore_geometry()

        # مؤقت المزامنة: يحدّث الترجمة والوقت 10 مرات/ثانية
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(100)
        self.sync_timer.timeout.connect(self._on_sync_tick)
        self.sync_timer.start()

        # مؤقت أبطأ لتحديث الواجهة
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(1000)
        self.ui_timer.timeout.connect(self._on_ui_tick)
        self.ui_timer.start()

        self._init_player()
        self._init_speech()
        self._load_recent_menu()
        self._update_source_menu()
        self._update_embedded_menu()

        self.live_region.announce(self.tr("playback.nothing"))

    # ==================================================================
    # بناء الواجهة
    # ==================================================================
    def _build_ui(self) -> None:
        # ----- عنصر الفيديو -----
        from .video_surface import VideoSurface

        self.video = VideoSurface()
        self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # ----- لوحة الترجمة -----
        from .subtitle_readout import SubtitleReadout

        self.readout = SubtitleReadout(self.engine, self.tr)
        self.readout.setVisible(bool(self.cfg.get("sub_panel_visible")))
        self.readout.seek_to_cue_requested.connect(self._seek_to_cue)
        self.readout.read_aloud_requested.connect(self._read_current_aloud)
        self.readout.stop_speech_requested.connect(self.speech.stop)

        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter.addWidget(self.video)
        self.main_splitter.addWidget(self.readout)
        self.main_splitter.setStretchFactor(0, 4)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([500, 220])

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._build_controls())
        lay.addWidget(self.main_splitter, 1)
        self.setCentralWidget(central)

        # ----- قائمة التشغيل -----
        self.playlist_dock = QDockWidget(self.tr("playlist.title"), self)
        self.playlist_dock.setObjectName("playlistDock")
        self.playlist_list = QListWidget()
        self.playlist_list.setAccessibleName(self.tr("playlist.title"))
        self.playlist_list.setAccessibleDescription(
            "Media playlist. Use arrow keys to move and Enter to play."
        )
        self.playlist_list.itemDoubleClicked.connect(self._on_playlist_activate)
        self.playlist_list.currentRowChanged.connect(self._on_playlist_row)
        self.playlist_dock.setWidget(self.playlist_list)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.playlist_dock)

        ptb = QMenu("...")
        ptb.addAction(self.tr("playlist.add_file"), self.add_files_dialog)
        ptb.addAction(self.tr("playlist.add_folder"),
                      lambda: self.add_folder_dialog(play_first=False))
        ptb.addAction(self.tr("playlist.add_url"), self.add_url_dialog)
        ptb.addSeparator()
        ptb.addAction(self.tr("playlist.remove"), self._remove_selected)
        ptb.addAction(self.tr("playlist.clear"), self._clear_playlist)
        self.playlist_dock.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_dock.customContextMenuRequested.connect(
            lambda p: ptb.exec(self.playlist_dock.mapToGlobal(p))
        )
        self._playlist_menu = ptb

        # ----- منطقة حيّة للإعلانات -----
        # يجب أن تكون جزءاً من شجرة الواجهة ليقرأها قارئ الشاشة
        self.live_region = LiveRegion()
        self.live_region.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.live_region, 0)

    def _build_controls(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("controlBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(6)

        # الاختصارات تُسجَّل مرة واحدة في _bind_keys لتفادي تعارض Qt
        self.btn_open = make_button("Open", self.tr("menu.open_file"),
                                    self.tr("menu.open_file"))
        self.btn_open.clicked.connect(self.open_file_dialog)

        self.btn_play = make_button("Play", self.tr("play"), self.tr("play"))
        self.btn_play.clicked.connect(self.toggle_play)

        self.btn_stop = make_button("Stop", self.tr("stop"), self.tr("stop"))
        self.btn_stop.clicked.connect(self._on_stop)

        self.btn_prev = make_button("<<", self.tr("prev"), self.tr("prev"))
        self.btn_prev.clicked.connect(self.play_prev)

        self.btn_next = make_button(">>", self.tr("next"), self.tr("next"))
        self.btn_next.clicked.connect(self.play_next)

        self.lbl_time = QLabel("0:00 / 0:00")
        a11y(self.lbl_time, "Playback time",
             "Elapsed time and total duration. Press F9 for options.")

        self.seek = make_slider(0, 1000, 0, self.tr("playback.seek_slider"),
                                "Use arrow keys to seek. Home and End jump to ends.")
        self.seek.sliderPressed.connect(self._on_seek_start)
        self.seek.sliderReleased.connect(self._on_seek_end)
        self.seek.sliderMoved.connect(self._on_seek_move)

        self.volume = VolumeSlider()
        a11y(self.volume, self.tr("playback.volume_slider"),
             "Use arrow keys to change volume")
        self.volume.valueCommitted.connect(self._on_volume)
        self.volume.setFixedWidth(110)

        self.lbl_speed = QLabel("1.00x")
        a11y(self.lbl_speed, self.tr("playback.speed_label"), "Playback speed")
        self.lbl_speed.setFixedWidth(52)

        self.btn_fullscreen = make_button("[ ]", self.tr("fullscreen"),
                                          self.tr("fullscreen"))
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)

        self.btn_menu = make_button("☰", "Main menu", "Open the main menu")
        self.btn_menu.clicked.connect(self._show_main_menu)

        for w in (self.btn_open, self.btn_prev, self.btn_play, self.btn_stop,
                  self.btn_next):
            h.addWidget(w)
        h.addWidget(self.lbl_time)
        h.addWidget(self.seek, 1)
        h.addWidget(self.volume)
        h.addWidget(self.lbl_speed)
        h.addWidget(self.btn_fullscreen)
        h.addWidget(self.btn_menu)
        return bar

    def _make_action(self, text: str, slot=None, checkable: bool = False) -> QAction:
        """ينشئ QAction ويربطه بالدالة (PySide6 لا يقبل الدالة في المُنشئ)."""
        act = QAction(text, self)
        if checkable:
            act.setCheckable(True)
        if slot is not None:
            if checkable:
                act.toggled.connect(slot)
            else:
                act.triggered.connect(slot)
        return act

    def _bind_keys(self) -> None:
        """
        اختصارات لوحة المفاتيح على مستوى النافذة.
        نستخدم اختصارات QAction بدل keyPressEvent حتى تعمل مع كل العناصر.
        """
        def act(key: str, slot, name: str, checkable: bool = False) -> QAction:
            a = self._make_action("", slot, checkable=checkable)
            a.setShortcut(QKeySequence(key))
            # QAction لا يملك accessibleDescription، نستخدم التلميحات
            a.setToolTip(f"{key} — {name}")
            a.setStatusTip(name)
            self.addAction(a)
            return a

        # ---- عام ----
        act("Ctrl+,", self.open_preferences, self.tr("menu.preferences"))
        act("Ctrl+O", self.open_file_dialog, self.tr("menu.open_file"))
        act("Ctrl+D", self.add_folder_dialog, self.tr("menu.open_folder"))
        act("F10", self._show_main_menu, self.tr("menu.file"))
        act("F11", self.toggle_fullscreen, self.tr("fullscreen"))
        act("F1", self.open_shortcuts, self.tr("menu.tips"))
        act("Ctrl+Shift+L", self.toggle_language, self.tr("prefs.language"))
        act("Esc", lambda: self._escape(), self.tr("close"))

        # ---- التشغيل ----
        act("Space", self.toggle_play, self.tr("play"))
        act("Ctrl+S", self._on_stop, self.tr("stop"))
        act("Ctrl+PgUp", self.play_prev, self.tr("prev"))
        act("Ctrl+PgDown", self.play_next, self.tr("next"))
        act("F9", self._toggle_panel, self.tr("show_subtitle_panel"))
        act("Ctrl+C", self._copy_current_line, self.tr("sub.copy_line"))
        act("Right", lambda: self._seek(10000), self.tr("seek_forward"))
        act("Left", lambda: self._seek(-10000), self.tr("seek_backward"))
        act("Shift+Right", lambda: self._seek(60000), self.tr("seek_forward_long"))
        act("Shift+Left", lambda: self._seek(-60000), self.tr("seek_backward_long"))
        act("Up", lambda: self._nudge_volume(5), self.tr("volume_up"))
        act("Down", lambda: self._nudge_volume(-5), self.tr("volume_down"))
        act("M", self._toggle_mute, self.tr("mute_toggle"))
        act("=", lambda: self._nudge_rate(0.25), self.tr("speed_up"))
        act("+", lambda: self._nudge_rate(0.25), self.tr("speed_up"))
        act("-", lambda: self._nudge_rate(-0.25), self.tr("speed_down"))
        act("Backspace", self._reset_rate, self.tr("speed_reset"))

        # ---- الترجمة والوصولية ----
        act("S", self._read_current_aloud, self.tr("read_aloud_current"))
        act("X", self.speech.stop, self.tr("read_aloud_stop"))
        act("Ctrl+Right", lambda: self._cue_step(1), self.tr("next_subtitle"))
        act("Ctrl+Left", lambda: self._cue_step(-1), self.tr("prev_subtitle"))
        act("Ctrl+Shift+Right", lambda: self._shift_subtitle(0.5),
            self.tr("subtitle_delay_less"))
        act("Ctrl+Shift+Left", lambda: self._shift_subtitle(-0.5),
            self.tr("subtitle_delay_more"))
        act("R", self.open_search_dialog, self.tr("sub.search_online"))
        act("B", self.open_merge_dialog, self.tr("merge.title"))
        act("F8", self.open_audio_diagnostics, self.tr("diag.title"))

    def _build_menus(self) -> None:
        from .menu_bar import AccessibleMenuBar
        self.setMenuBar(AccessibleMenuBar(self))
        mb = self.menuBar()
        # self._menus: القوائم الرئيسية والقوائم الفرعية
        # self._act: الإجراءات فقط (QAction)
        self._menus: dict[str, QMenu] = {}
        self._act: dict[str, QAction] = {}

        # ----- ملف -----
        m_file = mb.addMenu("")
        self._menus["file"] = m_file
        # ملاحظة: لا نضع اختصارات على إجراءات القوائم إطلاقاً؛ كل الاختصارات
        # مربوطة مرة واحدة فقط في _bind_keys على مستوى النافذة، لأن Qt يُعطّل
        # الاختصار المكرّر ويحوّله إلى عنصر القائمة (فلا يعمل مع كل العناصر).
        a_file = m_file.addAction("", self.open_file_dialog)
        self._act["open_file"] = a_file
        self._act["open_folder"] = m_file.addAction("", self.add_folder_dialog)
        self._act["open_url"] = m_file.addAction("", self.add_url_dialog)
        self._menus["recent"] = m_file.addMenu("")
        m_file.addSeparator()
        a_exit = m_file.addAction("", self.close, QKeySequence.Quit)
        self._act["exit"] = a_exit

        # ----- تحرير -----
        m_edit = mb.addMenu("")
        self._menus["edit"] = m_edit
        self._act["copy_line"] = m_edit.addAction("", self._copy_current_line)

        # ----- عرض -----
        m_view = mb.addMenu("")
        self._menus["view"] = m_view
        self._act["show_panel"] = self._make_action("", self._on_panel_toggled,
                                                   checkable=True)
        # نقرأ من الإعدادات وليس من readout.isVisible(): الأخيرة تُرجع False
        # قبل عرض النافذة، فيبدأ الإجراء «غير محدد» واللوحة ظاهرة فعلاً،
        # فتبتلع أول ضغطة على F9. الإجراء هو المصدر الوحيد للحقيقة.
        panel_on = bool(self.cfg.get("sub_panel_visible"))
        self._act["show_panel"].setChecked(panel_on)
        self.readout.setVisible(panel_on)
        m_view.addAction(self._act["show_panel"])
        self._act["toggle_playlist"] = self._make_action("", self._on_playlist_toggled,
                                                        checkable=True)
        self._act["toggle_playlist"].setChecked(True)
        m_view.addAction(self._act["toggle_playlist"])
        m_view.addSeparator()
        self._act["fullscreen"] = m_view.addAction("", self.toggle_fullscreen)

        # ----- الترجمة -----
        m_sub = mb.addMenu("")
        self._menus["subtitles"] = m_sub
        self._act["sub_external"] = m_sub.addAction("", self.load_external_subtitle)
        self._act["sub_search"] = m_sub.addAction("", self.open_search_dialog)
        self._act["sub_merge"] = m_sub.addAction("", self.open_merge_dialog)
        m_sub.addSeparator()
        self._act["sub_offset_reset"] = m_sub.addAction("", self.reset_sub_offset)
        m_sub.addSeparator()
        self._act["sub_read_now"] = m_sub.addAction("", self._read_current_aloud)
        self._act["sub_stop_tts"] = m_sub.addAction("", self.speech.stop)
        self._act["auto_read"] = self._make_action("", self._toggle_auto_read,
                                                   checkable=True)
        self._act["auto_read"].setCheckable(True)
        self._act["auto_read"].setChecked(bool(self.cfg.get("tts_announce_subtitle")))
        m_sub.addAction(self._act["auto_read"])
        self._act["sub_next"] = m_sub.addAction("", lambda: self._cue_step(1))
        self._act["sub_prev"] = m_sub.addAction("", lambda: self._cue_step(-1))
        m_sub.addSeparator()
        # مصدر الترجمة الموحّد (تلقائي/يدوي + قائمة المصادر المتاحة)
        self._menus["source"] = m_sub.addMenu("")
        # مسار الترجمة المدمجة داخل الفيديو (تلقائي أو اختيار يدوي)
        self._menus["emb_tracks"] = m_sub.addMenu("")
        self._act["read_last"] = m_sub.addAction("", self._read_last_aloud)
        self._act["yt_fetch"] = m_sub.addAction("", self._fetch_youtube_subtitles)

        # ----- أدوات -----
        m_tools = mb.addMenu("")
        self._menus["tools"] = m_tools
        self._act["prefs"] = m_tools.addAction("", self.open_preferences)
        self._act["manage_sites"] = m_tools.addAction("", self.open_search_dialog)
        self._act["deps"] = m_tools.addAction("", self.open_requirements)
        self._act["audio_diag"] = m_tools.addAction("", self.open_audio_diagnostics)
        self._act["toggle_lang"] = m_tools.addAction("", self.toggle_language)
        m_tools.addSeparator()
        self._act["tts_enabled"] = self._make_action("", self._toggle_tts,
                                                     checkable=True)
        m_tools.addAction(self._act["tts_enabled"])

        # ----- مساعدة -----
        m_help = mb.addMenu("")
        self._menus["help"] = m_help
        self._act["shortcuts"] = m_help.addAction("", self.open_shortcuts)
        self._act["about"] = m_help.addAction("", self.open_about)
        for menu in self._menus.values():
            menu.installEventFilter(mb)

    def _build_statusbar(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_msg = QLabel("")
        self.status_msg.setAccessibleName("Status")
        self.status_msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sb.addWidget(self.status_msg, 1)
        self.lbl_media = QLabel("")
        self.lbl_media.setAccessibleName("Media information")
        sb.addPermanentWidget(self.lbl_media)

    # ==================================================================
    # التهيئة
    # ==================================================================
    def _init_video_surface(self) -> None:
        """يربط عنصر الفيديو بالمحرّك: الإطارات وحجم التصغير."""
        self.player.set_frame_sink(self.video.set_frame)
        self.video.resized.connect(self._on_video_resized)
        self._apply_subtitle_style()

    def _apply_subtitle_style(self) -> None:
        """
        ينقل إعدادات شكل الترجمة إلى ما يرسمها.

        الترجمة تُرسم فوق الصورة بعد فك الترميز، لا محترقة داخلها. لذلك هذه
        الإعدادات تطبّقها الواجهة عند الرسم.
        """
        self.video.set_subtitle_enabled(bool(self.cfg.get("sub_show_on_screen")))
        self.video.set_subtitle_base_pt(int(self.cfg.get("sub_font_size") or 34))
        self.video.set_subtitle_position(str(self.cfg.get("sub_position") or "bottom"))

    def _on_video_resized(self) -> None:
        """نُبلغ المحرّكم بأقصى مقاس نرسمه لتصغير ما هو أكبر قبل نسخه."""
        self.player.set_render_max(self.video.width(), self.video.height())

    def _sync_overlay(self, cue) -> None:
        """يعرض سطر الترجمة النشط فوق الصورة."""
        self.video.set_subtitle(cue.text if cue is not None else "")

    def _init_player(self) -> None:
        self._init_video_surface()
        ok, err = self.player.initialize()
        if not ok:
            self.status_msg.setText(f"FFmpeg: {err}")
            self.live_region.announce(
                "The FFmpeg media engine is not available. "
                "Open Tools then Check requirements."
            )
            return
        self.player.set_decode_threads(int(self.cfg.get("decode_threads") or 0))
        self.player.set_output_device(int(self.cfg.get("audio_device") or -1))
        self.player.time_changed.connect(self._on_time_changed)
        self.player.duration_changed.connect(self._on_duration_changed)
        self.player.state_changed.connect(self._on_state_changed)
        self.player.media_ended.connect(self._on_media_ended)
        self.player.media_error.connect(self._on_media_error)
        self.player.media_opened.connect(self._on_media_opened)

    def _init_speech(self) -> None:
        available = self.speech.available
        if not available:
            self._act["auto_read"].setEnabled(False)
            self._act["tts_enabled"].setEnabled(False)
            return
        self.speech.configure(
            enabled=bool(self.cfg.get("tts_enabled")),
            rate=int(self.cfg.get("tts_rate") or 175),
            volume=int(self.cfg.get("tts_volume") or 100),
            voice=str(self.cfg.get("tts_voice") or ""),
            choice=str(self.cfg.get("tts_engine") or "auto"),
            hold_ms=int(self.cfg.get("tts_duck_hold_ms") or 600),
        )

    def _restore_geometry(self) -> None:
        geo = self.cfg.get("window_geometry") or ""
        state = self.cfg.get("window_state") or ""
        try:
            if geo:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
            if state:
                self.restoreState(QByteArray.fromBase64(state.encode("ascii")))
        except Exception:
            pass

    def _save_geometry(self) -> None:
        try:
            self.cfg.set("window_geometry",
                         bytes(self.saveGeometry().toBase64()).decode("ascii"))
            self.cfg.set("window_state",
                         bytes(self.saveState().toBase64()).decode("ascii"))
        except Exception:
            pass

    def _sync_toggle_states(self) -> None:
        """
        يواءم حالة الإجراءات القابلة للتحديد مع رؤية الودجتات.

        لازم أن تُستدعى بعد عرض النافذة فقط، لأن `isVisible()` يُرجع False قبل
        ذلك. بدونها قد تبدأ القائمة على «قائمة التشغيل ظاهرة» بينما استُعيدت
        النافذة بحالة مخزّنة تخفيها.
        """
        for key, widget in (("show_panel", self.readout),
                            ("toggle_playlist", self.playlist_dock)):
            act = self._act.get(key)
            if act is None:
                continue
            act.blockSignals(True)
            act.setChecked(widget.isVisible())
            act.blockSignals(False)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not getattr(self, "_toggle_state_synced", False):
            self._toggle_state_synced = True
            self._sync_toggle_states()

    # ==================================================================
    # اللغة
    # ==================================================================
    def _apply_language(self) -> None:
        tr = self.tr
        self.setWindowTitle(tr("app.title"))
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if tr.is_rtl()
            else Qt.LayoutDirection.LeftToRight
        )

        titles = {
            "file": "menu.file", "edit": "menu.edit", "view": "menu.view",
            "subtitles": "menu.subtitles", "tools": "menu.tools", "help": "menu.help",
            "recent": "menu.recent", "source": "sub.source",
            "emb_tracks": "sub.embedded_tracks",
        }
        for key, ikey in titles.items():
            self._menus[key].setTitle(tr(ikey))

        labels = {
            "open_file": "menu.open_file", "open_folder": "menu.open_folder",
            "open_url": "menu.open_url",
            "exit": "menu.exit", "prefs": "menu.preferences",
            "copy_line": "sub.copy_line",
            "show_panel": "show_subtitle_panel", "toggle_playlist": "playlist.title",
            "fullscreen": "fullscreen", "sub_external": "sub.load_external",
            "sub_search": "sub.search_online", "sub_merge": "merge.title",
            "sub_offset_reset": "sub.reset_offset",
            "sub_read_now": "read_aloud_current", "sub_stop_tts": "read_aloud_stop",
            "auto_read": "auto_read_subtitle", "sub_next": "next_subtitle",
            "sub_prev": "prev_subtitle",             "manage_sites": "menu.manage_subtitle_sites",
            "deps": "menu.dependencies", "tts_enabled": "menu.voice_tts",
            "toggle_lang": "menu.toggle_lang", "audio_diag": "diag.title",
            "shortcuts": "menu.tips", "about": "menu.about",
            "read_last": "sub.read_last", "yt_fetch": "ytdlp.action",
        }
        for key, ikey in labels.items():
            act = self._act.get(key)
            if act is not None:
                act.setText(tr(ikey))

        btn_labels = {
            self.btn_open: "menu.open_file", self.btn_play: "play",
            self.btn_stop: "stop", self.btn_prev: "prev", self.btn_next: "next",
            self.btn_fullscreen: "fullscreen", self.btn_menu: "menu.file",
        }
        for btn, ikey in btn_labels.items():
            btn.setText(tr(ikey))
            btn.setAccessibleName(tr(ikey))
            btn.setToolTip(tr(ikey))

        self.readout.retranslate(tr)
        self.playlist_dock.setWindowTitle(tr("playlist.title"))
        self.playlist_list.setAccessibleName(tr("playlist.title"))
        self.seek.setAccessibleName(tr("playback.seek_slider"))
        self.volume.setAccessibleName(tr("playback.volume_slider"))
        self._load_recent_menu()
        self._update_source_menu()

    def toggle_language(self) -> None:
        """تبديل لغة الواجهة بين العربية والإنجليزية."""
        lang = self.cfg.toggle_lang()
        self.tr.set_language(lang)
        self._apply_language()
        self.live_region.announce(
            "تم تبديل اللغة إلى العربية" if lang == i18n.AR else "Language switched to English"
        )

    # ==================================================================
    # الفتح والتشغيل
    # ==================================================================
    def _start_dir(self) -> str:
        """
        مجلد البداية لنوافذ "فتح ملف".

        نبدأ من آخر مجلد استعمله المستخدم، وإلا من مجلد التنزيلات، وإلا من
        المجلد الشخصي. البداية من "" كانت تجعل النافذة تنطلق من مجلد عمل
        البرنامج (System32 عند التشغيل من قائمة ابتداء) فيضيع المستخدم.
        """
        last = str(self.cfg.get("last_open_dir") or "")
        if last and Path(last).is_dir():
            return last
        downloads = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        if downloads and Path(downloads).is_dir():
            return downloads
        return str(Path.home())

    def _remember_dir(self, path: str) -> None:
        """يحفظ مجلد الاختيار ليستفتحه المرة القادمة في نفس المكان."""
        p = Path(path)
        folder = p if p.is_dir() else p.parent
        if folder.is_dir():
            self.cfg.set("last_open_dir", str(folder))
            self.cfg.sync()

    def open_file_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.tr("menu.open_file"), self._start_dir(), MEDIA_FILTER
        )
        if paths:
            self._remember_dir(paths[0])
            self.open_paths(paths, play_first=True)

    def add_files_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.tr("playlist.add_file"), self._start_dir(), MEDIA_FILTER
        )
        if paths:
            self._remember_dir(paths[0])
            self.open_paths(paths, play_first=False)

    def add_folder_dialog(self, play_first: bool = True) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("menu.open_folder"), self._start_dir()
        )
        if not folder:
            return
        self._remember_dir(folder)
        p = Path(folder)
        exts = {e.lower().lstrip(".") for e in MEDIA_EXTENSIONS}
        files: list[str] = []
        try:
            # بحث متكرر داخل المجلد وكل ما تحته (أفلام في مجلدات فرعية)
            for f in p.rglob("*"):
                if f.is_file() and f.suffix.lower().lstrip(".") in exts:
                    files.append(str(f))
        except OSError:
            files = []
        if files:
            files.sort()
            self.open_paths(files, play_first=play_first)
            self.live_region.announce(self.tr("playlist.added_folder") + f": {len(files)}")
        else:
            self.live_region.announce(self.tr("folder.no_media"))
            self.status_msg.setText(self.tr("folder.no_media"))

    def add_url_dialog(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        url, ok = QInputDialog.getText(self, self.tr("menu.open_url"), "URL:")
        if ok and url.strip():
            self.open_paths([url.strip()], play_first=True)

    def open_paths(self, paths: list[str], play_first: bool = True) -> None:
        """يضيف ملفات (أو روابط) إلى قائمة التشغيل."""
        added: list[int] = []
        for raw in paths:
            is_url = raw.lower().startswith(("http://", "https://", "rtsp://", "mms://", "ftp://"))
            if not is_url and not Path(raw).exists():
                continue
            item = PlaylistItem(raw, title=raw if is_url else Path(raw).stem, is_url=is_url)
            self.playlist.append(item)
            idx = len(self.playlist) - 1
            added.append(idx)
            row = QListWidgetItem(f"{idx + 1}. {item.title}")
            row.setToolTip(raw)
            self.playlist_list.addItem(row)
        self.status_msg.setText(
            f"{self.tr('playlist.count')}: {len(self.playlist)}"
        )
        if play_first and added:
            self.play_index(added[0])

    def open_recent(self, path: str) -> None:
        if Path(path).exists():
            self.open_paths([path], play_first=True)
        else:
            self.cfg.add_recent("")  # no-op guard
            self._load_recent_menu()

    def play_index(self, index: int) -> None:
        if not (0 <= index < len(self.playlist)):
            return
        self.current_index = index
        item = self.playlist[index]
        self.playlist_list.setCurrentRow(index)
        self.current_path = item.path
        # ملف جديد: لا ملف ترجمة خارجي بعد
        self._sidecar_loaded = False
        self._last_live_sub = ""
        # مسح آثار ملف الترجمة السابق
        self._text_cues = []
        self._text_name = ""
        self._text_path = ""
        self._text_origin = None
        self.speak_policy.reset()
        self._reset_embedded_state()
        # أسطر الملف السابق لا تنتقل إلى الملف الجديد
        self.engine.unload()

        if item.is_url:
            ok, err = self.player.load_url(item.path)
        else:
            ok, err = self.player.load(self.current_path)
        if not ok:
            self.live_region.announce(
                self.tr("error.cannot_open") + " " + str(err)
            )
            self.status_msg.setText(f"{self.tr('error.cannot_open')}: {err}")
            return

        if not item.is_url:
            self.cfg.add_recent(self.current_path)
            self._load_recent_menu()
        self.player.play()
        self.btn_play.setText(self.tr("pause"))
        self._auto_load_subtitle()
        self._detect_embedded_tracks()
        self._update_source_availability()
        self._sync_active_source(force=True)
        self._maybe_auto_search_subtitle()

    def play_next(self) -> None:
        if not self.playlist:
            return
        nxt = self.current_index + 1
        if nxt >= len(self.playlist):
            if self.cfg.get("loop_playlist"):
                nxt = 0
            else:
                self.live_region.announce(self.tr("playlist.title") + ": " + self.tr("none"))
                return
        self.play_index(nxt)

    def play_prev(self) -> None:
        if not self.playlist:
            return
        prv = self.current_index - 1
        if prv < 0:
            prv = 0
        self.play_index(prv)

    def toggle_play(self) -> None:
        if not self.player.ready:
            self.open_requirements()
            return
        if not self.current_path:
            self.open_file_dialog()
            return
        self.player.toggle_pause()
        self.btn_play.setText(self.tr("pause") if self.player.is_paused() else self.tr("play"))
        self.live_region.announce(
            self.tr("playback.state.paused") if self.player.is_paused()
            else self.tr("playback.state.playing")
        )

    def _on_stop(self) -> None:
        self.player.stop()
        self.engine.unload()
        self._last_live_sub = ""
        self._reset_embedded_state()
        self.player.select_subtitle_stream(None)
        self._update_source_availability()
        self.readout.set_placeholder()
        self.btn_play.setText(self.tr("play"))
        self.live_region.announce(self.tr("stop"))

    # ==================================================================
    # الترجمة
    # ==================================================================
    def _auto_load_subtitle(self) -> None:
        """يبحث عن ملف ترجمة خارجي مرافق تلقائياً."""
        if not self.current_path or self.current_path.lower().startswith(("http", "rtsp", "mms")):
            return
        if not self.cfg.get("sub_auto_load_sidecar"):
            return
        found = sidecar_candidates(self.current_path)
        if not found:
            # الاسم غير مطابق: ملف ترجمة وحيد في نفس المجلد يصلح أيضاً
            found = self._fallback_sidecar_candidates()
        if found:
            ok, _, _ = self.engine.load_file(found[0])
            if ok:
                self._sidecar_loaded = True
                self._text_cues = list(self.engine.cues)
                self._text_name = found[0].stem
                self._text_path = str(found[0])
                self._text_origin = SourceKind.EXTERNAL
                self.readout.clear_placeholder()
                self._notify("sub.external_loaded", extra=found[0].name)
                # المصدر الفعّال يقرّر ما يقرأه mpv (خارجي أو مدمج)
                self._update_source_availability()
                self._sync_active_source(force=True)
                return
        # لا يوجد ملف ترجمة مرافق
        self.readout.set_placeholder(self.tr("sub.no_external"))
        self.status_msg.setText(self.tr("sub.no_external"))

    # ------------------------------------------------------------------
    # الترجمة المدمجة داخل الفيديو
    # ------------------------------------------------------------------
    def _reset_embedded_state(self) -> None:
        self._emb_tracks = []
        self._emb_selected_index = None
        self._emb_auto = True
        self._emb_cues = []
        self._emb_name = ""
        self._emb_job = None
        self._update_embedded_menu()

    def _selected_embedded_track(self) -> Optional[embedded_subs.EmbeddedTrack]:
        if self._emb_selected_index is None:
            return None
        return next((t for t in self._emb_tracks
                     if t.index == self._emb_selected_index and t.is_text), None)

    def _detect_embedded_tracks(self) -> None:
        """يكتشف مسارات الترجمة داخل الملف ويختار الأنسب ويبدأ استخراج أسطره."""
        if not self.current_path or self.current_path.lower().startswith(("http", "rtsp", "mms")):
            return
        self._emb_tracks = embedded_subs.list_embedded_tracks(self.current_path)
        pick = embedded_subs.pick_default_track(
            self._emb_tracks, str(self.cfg.get("sub_default_lang") or "ara"))
        if pick is not None:
            self._emb_selected_index = pick.index
            self._emb_auto = True
            self._emb_name = f"{Path(self.current_path).stem} [{self.tr('src.embedded')}]"
            self._start_embedded_extract(pick.index)
            self._notify("sub.embedded_found", extra=self._track_display(pick))
        elif any(t.is_image for t in self._emb_tracks):
            self._notify("sub.embedded_unsupported_image")
        elif not self._sidecar_loaded:
            self._notify("sub.embedded_none")
        self._update_embedded_menu()

    def _start_embedded_extract(self, stream_index: int) -> None:
        if not self.current_path:
            return
        job = (self.current_path, int(stream_index))
        if self._emb_job == job:
            return
        self._emb_job = job
        thread = QThread(self)
        worker = _EmbeddedCuesWorker(self.current_path, stream_index)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(
            lambda p, i, c: self._on_embedded_cues_ready(p, i, c, thread, worker)
        )
        self._emb_thread = thread
        thread.start()

    def _on_embedded_cues_ready(self, path: str, index: int, cues: object,
                                thread: QThread, worker: QObject) -> None:
        """أسطر المسار المدمج وصلت من الخيط الخلفي (تُهمَل إن تغيّر الملف/المسار)."""
        try:
            if self._emb_job == (path, index):
                self._emb_job = None
            if path != self.current_path or index != self._emb_selected_index:
                return
            self._emb_cues = list(cues or [])
            self._update_source_availability()
            if self.sub_mgr.active_kind() == SourceKind.EMBEDDED:
                self._reload_for_active_source(SourceKind.EMBEDDED)
                if self._emb_cues:
                    self.readout.clear_placeholder()
            if not self._emb_cues:
                self._notify("sub.embedded_extract_failed")
        finally:
            thread.quit()
            thread.wait(3000)
            worker.deleteLater()
            thread.deleteLater()
            if self._emb_thread is thread:
                self._emb_thread = None

    def _select_embedded_track(self, stream_index: Optional[int]) -> None:
        """اختيار المستخدم من قائمة المسارات: None = تلقائي، وإلا فهرس المسار."""
        if stream_index is None:
            self._emb_auto = True
            pick = embedded_subs.pick_default_track(
                self._emb_tracks, str(self.cfg.get("sub_default_lang") or "ara"))
            stream_index = pick.index if pick is not None else None
        else:
            self._emb_auto = False
        if stream_index != self._emb_selected_index:
            self._emb_selected_index = stream_index
            self._emb_cues = []
            if stream_index is not None and self.current_path:
                self._emb_name = f"{Path(self.current_path).stem} [{self.tr('src.embedded')}]"
                self._start_embedded_extract(stream_index)
        self._update_source_availability()
        if stream_index is not None and not self._emb_auto:
            # اختيار مسار صراحةً يعني: اقرأ المدمجة الآن
            self._select_source(SourceKind.EMBEDDED)
        else:
            self._sync_active_source(force=True)
            self._announce_current_source()
        self._update_embedded_menu()

    def _track_display(self, t: embedded_subs.EmbeddedTrack) -> str:
        """وصف مسار مدمج يفهمه قارئ الشاشة: الرقم، اللغة، العنوان، الترميز."""
        try:
            ordinal = self._emb_tracks.index(t) + 1
        except ValueError:
            ordinal = t.index
        code = embedded_subs.normalize_lang(t.language)
        name = self.tr(f"lang.{code}") if code else ""
        if not code or name == f"lang.{code}":
            name = t.language or self.tr("lang.und")
        bits = [f"{ordinal}. {name}"]
        if t.title:
            bits.append(t.title)
        if t.codec:
            bits.append(f"({t.codec})")
        if t.is_default:
            bits.append(self.tr("sub.track_default"))
        return " ".join(bits)

    def _update_embedded_menu(self) -> None:
        menu = self._menus.get("emb_tracks")
        if menu is None:
            return
        menu.clear()
        if not self._emb_tracks:
            a = menu.addAction(self.tr("sub.embedded_none"))
            a.setEnabled(False)
            return
        group = QActionGroup(menu)
        group.setExclusive(True)
        self._emb_group = group
        auto = menu.addAction(self.tr("sub.embedded_track_auto"))
        auto.setCheckable(True)
        auto.setChecked(self._emb_auto)
        auto.triggered.connect(lambda _=False: self._select_embedded_track(None))
        group.addAction(auto)
        menu.addSeparator()
        for t in self._emb_tracks:
            label = self._track_display(t)
            if t.is_image:
                label = f"{label} — {self.tr('sub.embedded_unsupported_image')}"
            act = menu.addAction(label)
            act.setCheckable(True)
            if t.is_image or not t.is_text:
                act.setEnabled(False)
                continue
            act.setChecked(not self._emb_auto and t.index == self._emb_selected_index)
            act.triggered.connect(lambda _=False, i=t.index: self._select_embedded_track(i))
            group.addAction(act)

    def _fallback_sidecar_candidates(self) -> list:
        """
        بديل لملف الترجمة غير المطابق للاسم: إن كان في المجلد ملفُ ترجمةٍ
        وحيد فقط نعتمده (غالباً هو نفسه مرافق هذا الفيلم).
        """
        if not self.current_path:
            return []
        try:
            folder = Path(self.current_path).parent
            subs = [
                f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower().lstrip(".") in SUB_EXTENSIONS
            ]
        except OSError:
            return []
        if len(subs) == 1:
            return subs
        return []

    def _maybe_auto_search_subtitle(self) -> None:
        """
        بحث تلقائي عن ترجمة عبر الإنترنت عند فتح فيلم بلا ترجمة.

        يحترم إعداد «البحث التلقائي إذا لم توجد ترجمة» ولا يبحث إلا إذا
        لم تكن هناك ترجمة مرافقة ولا مدمجة، ومرة واحدة لكل ملف.
        """
        if self._auto_search_busy:
            return
        if not self.cfg.get("sub_auto_search_if_missing"):
            return
        if not self.current_path or self.current_path.lower().startswith(("http", "rtsp", "mms")):
            return
        if self._sidecar_loaded or self.engine.has_cues or self._emb_selected_index is not None:
            return
        self._auto_search_busy = True
        self._notify("search.auto_searching")
        lang = str(self.cfg.get("search_language") or "ara")
        self._auto_search_path = self.current_path
        thread = QThread(self)
        worker = _AutoSubtitleWorker(self.current_path, lang)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(
            lambda res: self._on_auto_sub_done(res, thread, worker)
        )
        self._auto_thread = thread
        thread.start()

    def _on_auto_sub_done(self, res: str, thread: QThread, worker: _AutoSubtitleWorker) -> None:
        """نتيجة البحث التلقائي: تحميل الترجمة إن وُجدت وتُطابق الملف الحالي."""
        try:
            if self._auto_search_busy and not res:
                self.status_msg.setText(self.tr("search.auto_none"))
                self.live_region.announce(self.tr("search.auto_none"))
            if res and self.current_path == self._auto_search_path:
                if not self.engine.has_cues:
                    self.load_subtitle_path(res)
                self._notify("search.auto_found", extra=Path(res).name)
            self._auto_search_busy = False
        finally:
            thread.quit()
            thread.wait(3000)
            worker.deleteLater()
            thread.deleteLater()
            if self._auto_thread is thread:
                self._auto_thread = None

    def load_external_subtitle(self) -> None:
        if not self.current_path:
            QMessageBox.information(self, self.tr("sub.title"), self.tr("playback.nothing"))
            return
        start = str(Path(self.current_path).parent)
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("sub.load_external"), start, SUB_FILTER
        )
        if not path:
            return
        self.load_subtitle_path(path)

    def load_subtitle_path(self, path: str,
                           origin: SourceKind = SourceKind.EXTERNAL) -> bool:
        ok, count, err = self.engine.load_file(path)
        if not ok:
            self.live_region.announce(self.tr("sub.load_external") + ": " + err)
            return False
        self._sidecar_loaded = True
        self._text_cues = list(self.engine.cues)
        self._text_name = Path(path).stem
        self._text_path = path
        self._text_origin = origin
        self.readout.clear_placeholder()
        self._notify("sub.external_loaded", extra=Path(path).name)
        # المصدر الفعّال يقرّر ما يقرأه mpv (خارجي أو مدمج)
        self._update_source_availability()
        self._sync_active_source(force=True)
        return True

    def reset_sub_offset(self) -> None:
        self.engine.reset_offset()
        self.player.set_sub_delay(0)
        self.readout.index_label.setText(self.tr("sub.delay_offset") + ": 0.0s")
        self._notify("speed_reset")

    def _shift_subtitle(self, delta: float) -> None:
        """يقدّم (+) أو يؤخّر (-) الترجمة بمقدار half ثانية."""
        new = self.engine.adjust_offset(delta)
        self.player.set_sub_delay(int(new * 1_000_000))
        self.readout.index_label.setText(
            f"{self.tr('sub.delay_offset')}: {new:+.1f}s"
        )
        self.live_region.announce(
            self.tr("subtitle_delay_less") if delta > 0
            else self.tr("subtitle_delay_more")
        )

    def _seek(self, delta_ms: int) -> None:
        if not self.player.ready or not self.current_path:
            return
        self.speech.stop()
        self.player.seek_relative(delta_ms)
        pos = self.player.get_time()
        self.engine.update(pos)
        self.engine.reset_announce()

    def _toggle_panel(self) -> None:
        act = self._act.get("show_panel")
        if act is not None:
            act.setChecked(not act.isChecked())

    def _copy_current_line(self) -> None:
        self.readout._on_copy()
        cue = self.engine.current_cue()
        text = cue.text if cue else self.engine.log_text()
        if text:
            self.live_region.announce(self.tr("sub.copy_line"))

    def _escape(self) -> None:
        """إغلاق النافذة الفرعية إن وُجدت، وإلا الخروج من ملء الشاشة."""
        for w in self.findChildren(QWidget):
            if w.isVisible() and w is not self and isinstance(w, QDialog):
                w.close()
                return
        if self._fullscreen:
            self.toggle_fullscreen()

    def _seek_to_cue(self, ms: int) -> None:
        self.player.set_time(ms)
        self.engine.update(ms)
        cue = self.engine.current_cue()
        if cue is not None:
            self.engine.mark_announced(cue)

    def _cue_step(self, direction: int) -> None:
        c = self.engine.next_cue() if direction > 0 else self.engine.prev_cue()
        if c is not None:
            self._seek_to_cue(c.start_ms)
            self._read_text_aloud(c.text)

    def _read_current_aloud(self) -> None:
        cue = self.engine.current_cue()
        if cue is not None:
            self._read_text_aloud(cue.text)
        else:
            self.live_region.announce(self.tr("sub.no_subtitles"))

    def _read_text_aloud(self, text: str) -> None:
        if not text:
            return
        self._last_spoken_text = text
        self.engine.mark_announced(self.engine.current_cue())
        # نطق الترجمة يذهب إلى القارئ مباشرة (NVDA Controller Client عندما
        # يعمل) ولا يتقيد بمفتاح النطق العام: القراءة التلقائية للترجمة
        # مفتاحها المستقل (tts_announce_subtitle).
        if self.speech.available:
            self.speech.say(text, force=True)
        else:
            self.live_region.announce(text)

    def _read_last_aloud(self) -> None:
        """يعيد نطق آخر ترجمة سُمعت (ميزة الوصول المطلوبة)."""
        text = self._last_spoken_text or self.speak_policy.last_text
        if not text:
            cue = self.engine.current_cue()
            text = cue.text if cue is not None else ""
        if text:
            self._read_text_aloud(text)
        else:
            self.live_region.announce(self.tr("sub.read_last_none"))

    def _toggle_auto_read(self, on: bool) -> None:
        self.cfg.set("tts_announce_subtitle", on)
        self.cfg.sync()
        self.live_region.announce(
            self.tr("auto_read_subtitle") + ": " + ("on" if on else "off")
        )

    def _toggle_tts(self) -> None:
        cur = bool(self.cfg.get("tts_enabled"))
        new = not cur
        self.cfg.set("tts_enabled", new)
        self.cfg.sync()
        self._init_speech()
        self._act["tts_enabled"].setText(
            self.tr("menu.voice_off") if new else self.tr("menu.voice_tts")
        )
        if new:
            self._read_current_aloud()

    # ==================================================================
    # مدير مصادر الترجمة الخارجية + يوتيوب
    # ==================================================================
    def _update_source_availability(self) -> None:
        """يحدّث حالة كل مصدر في المدير ثم يعيد بناء قائمة المصادر."""
        external = bool(
            self._sidecar_loaded and self._text_cues
            and self._text_origin in (SourceKind.EXTERNAL, None)
        )
        remote = bool(self._text_origin == SourceKind.REMOTE and self._text_cues)
        # المدمجة متاحة فور اكتشاف مسار نصي: mpv يقرأ نصّه الحي مباشرة،
        # والأسطر المستخرجة (للوحة والمحرك الاحتياطي) تلحق من الخيط الخلفي.
        emb_track = self._selected_embedded_track()
        embedded = emb_track is not None
        self.sub_mgr.set_source(SourceKind.EXTERNAL, external)
        self.sub_mgr.set_source(SourceKind.EMBEDDED, embedded,
                                self._track_display(emb_track) if emb_track else "")
        self.sub_mgr.set_source(SourceKind.REMOTE, remote)
        self._update_source_menu()
        self._update_embedded_menu()

    def _update_source_menu(self) -> None:
        menu = self._menus.get("source")
        if menu is None:
            return
        menu.clear()
        for mode, label in (("auto", "src.mode_auto"), ("manual", "src.mode_manual")):
            act = menu.addAction(self.tr(label))
            act.setCheckable(True)
            act.setChecked(self.sub_mgr.mode == mode)
            act.triggered.connect(lambda _=False, m=mode: self._set_source_mode(m))
        menu.addSeparator()
        active = self.sub_mgr.active_kind()
        avail = self.sub_mgr.available_sources()
        if not avail:
            a = menu.addAction(self.tr("src.none"))
            a.setEnabled(False)
            return
        for st in avail:
            label = self.tr(subtitle_manager.LABEL_KEY[st.kind])
            if st.detail:
                label = f"{label} — {st.detail}"
            if st.kind == active:
                label = f"● {label}"
            act = menu.addAction(label)
            act.triggered.connect(lambda _=False, k=st.kind: self._select_source(k))
            if st.kind == active:
                act.setEnabled(False)

    def _set_source_mode(self, mode: str) -> None:
        self.cfg.set("sub_source_mode", mode)
        self.cfg.sync()
        self.sub_mgr.set_mode(mode)
        if mode == "auto":
            self.sub_mgr.select(None)
        self._sync_active_source(force=True)
        self._announce_current_source()

    def _select_source(self, kind: SourceKind) -> None:
        self.cfg.set("sub_source_mode", "manual")
        self.cfg.sync()
        self.sub_mgr.select(kind)
        self._sync_active_source(force=True)
        self._announce_current_source()

    def _announce_current_source(self) -> None:
        kind = self.sub_mgr.active_kind()
        label = (self.tr(subtitle_manager.LABEL_KEY[kind]) if kind is not None
                 else self.tr("src.none"))
        detail = next((st.detail for st in self.sub_mgr.available_sources()
                       if st.kind == kind and st.detail), "")
        if detail:
            label = f"{label} — {detail}"
        self._notify("src.current", extra=label)

    def _sync_active_source(self, force: bool = False) -> None:
        """يضمن أن المحرّك يحمل أسطر المصدر الفعّال وحده."""
        kind = self.sub_mgr.active_kind()
        if not force and kind == self._active_kind:
            return
        self._active_kind = kind
        self._reload_for_active_source(kind)
        self._update_source_menu()

    def _reload_for_active_source(self, kind: Optional[SourceKind]) -> None:
        """يحمّل في المحرّك أسطر المصدر الفعّال وحده ويُخبر mpv بما يقرأه."""
        self._apply_engine_subtitle_selection(kind)
        if kind is None:
            return
        cues, name, path = self._cues_for_kind(kind)
        if not cues:
            # المدمجة ما زالت تُستخرج: لا نُبقي أسطر مصدر آخر في المحرك
            if self.engine.has_cues:
                self.engine.unload()
                self.speak_policy.reset()
                self._last_live_sub = ""
            return
        if self.engine.source_name != name:
            self.engine.load_cues(list(cues), name=name, source_path=path)
            self.engine.reset_announce()
            self.speak_policy.reset()
            self._last_live_sub = ""

    def _cues_for_kind(self, kind: SourceKind) -> tuple:
        """(الأسطر، الاسم، المسار) للمصدر المطلوب، أو قوائم فارغة."""
        if kind == SourceKind.EMBEDDED:
            return list(self._emb_cues), self._emb_name, ""
        if kind == SourceKind.EXTERNAL and self._text_origin in (SourceKind.EXTERNAL, None):
            return list(self._text_cues), self._text_name, self._text_path
        if kind == SourceKind.REMOTE and self._text_origin == SourceKind.REMOTE:
            return list(self._text_cues), self._text_name, self._text_path
        return [], "", ""

    def _apply_engine_subtitle_selection(self, kind: Optional[SourceKind]) -> None:
        """يجعل mpv يتابع نص المصدر الفعّال: ملف خارجي، مسار مدمج، أو لا شيء."""
        if kind == SourceKind.EMBEDDED:
            self.player.select_subtitle_stream(self._emb_selected_index)
        elif kind in (SourceKind.EXTERNAL, SourceKind.REMOTE):
            if self._text_path:
                self.player.attach_subtitle(self._text_path)
        else:
            self.player.select_subtitle_stream(None)

    def _fetch_youtube_subtitles(self) -> None:
        """يجلب ترجمة يوتيوب عبر yt-dlp (اختياري) ويحمّلها كمصدر بعيد."""
        from PySide6.QtWidgets import QInputDialog

        if self._yt_busy:
            self._notify("ytdlp.fetching")
            return
        ok, _backend, detail = youtube_subs.ytdlp_available()
        if not ok:
            self.live_region.announce(self.tr("ytdlp.missing"))
            return
        url, accepted = QInputDialog.getText(
            self, self.tr("ytdlp.action"), self.tr("ytdlp.url"),
            text=str(self.cfg.get("yt_source_url") or self.current_path or ""),
        )
        url = (url or "").strip()
        if not accepted or not url:
            return
        self.cfg.set("yt_source_url", url)
        self.cfg.sync()
        langs = youtube_subs.normalize_langs(
            str(self.cfg.get("sub_default_lang") or "ara"))
        out_dir = config.subtitles_cache_dir() / "youtube"
        self._yt_busy = True
        self._notify("ytdlp.fetching")

        import threading

        def work() -> None:
            res = youtube_subs.fetch_subtitles(url, langs, out_dir)
            QTimer.singleShot(0, lambda: self._on_yt_done(*res))

        threading.Thread(target=work, daemon=True).start()

    def _on_yt_done(self, ok: bool, files: list, mkey: str, detail: str) -> None:
        self._yt_busy = False
        if not ok:
            msg = self.tr(mkey) + (f" {detail}" if detail else "")
            self.live_region.announce(msg)
            return
        self._notify(mkey, extra=Path(files[0]).name)
        self.load_subtitle_path(files[0], origin=SourceKind.REMOTE)

    # ==================================================================
    # المزامنة والحالة
    # ==================================================================
    def _on_sync_tick(self) -> None:
        pos = self.player.get_time()
        if pos <= 0:
            self._sync_overlay(None)
            return
        self._sync_active_source()
        cue = self.engine.update(pos)
        self._sync_overlay(cue)
        if not self.cfg.get("tts_announce_subtitle"):
            return
        kind = self.sub_mgr.active_kind()
        # النصّ الحيّ من mpv (ملف خارجي أو مسار مدمج)؛ على محرك PyAV يعود
        # فارغاً فتُقرأ الأسطر المحلّلة/المستخرجة أدناه.
        live = ""
        if kind in (SourceKind.EXTERNAL, SourceKind.REMOTE, SourceKind.EMBEDDED):
            live = subtitle_text.clean_subtitle_text(
                self.player.current_subtitle_text())
        if live:
            self._last_live_sub = live
            out = self.speak_policy.offer(live, pos)
            if out is not None:
                self._read_text_aloud(out)
        elif cue is not None and self.engine.should_announce(cue):
            out = self.speak_policy.offer(cue.text, pos)
            self.engine.mark_announced(cue)
            if out is not None:
                self._read_text_aloud(out)

    def _on_ui_tick(self) -> None:
        dur = self.player.get_duration()
        pos = self.player.get_time()
        # خفض صوت الفيلم أثناء نطق القارئ (ducking) حتى لا يتراكب الصوتان
        try:
            if self.cfg.get("tts_duck_while_speaking") and self.speech.available:
                self.player.set_duck(self.speech.is_busy())
        except Exception:
            pass
        self.lbl_time.setText(f"{format_duration(pos/1000)} / {format_duration(dur/1000)}")
        self.lbl_time.setAccessibleDescription(
            f"{self.tr('playback.position')} {format_duration(pos/1000)} "
            f"من {self.tr('playback.time_total')} {format_duration(dur/1000)}"
        )
        if not self._seeking and dur > 0:
            self.seek.setValue(int(self.player.get_position() * 1000))

    def _on_time_changed(self, ms: int) -> None:
        if not self._seeking:
            dur = self.player.get_duration()
            if dur > 0:
                self.seek.setValue(int(ms / dur * 1000))

    def _on_duration_changed(self, ms: int) -> None:
        self.seek.setToolTip(f"{format_duration(ms/1000)}")

    def _on_state_changed(self, state: str) -> None:
        if state == "playing":
            self.btn_play.setText(self.tr("pause"))
        elif state == "paused":
            self.btn_play.setText(self.tr("play"))
        elif state == "ended":
            self.btn_play.setText(self.tr("play"))

    def _on_media_opened(self, path: str) -> None:
        self.status_msg.setText(f"{self.tr('playback.now_playing')}: {Path(path).name}")
        self.setWindowTitle(f"{Path(path).stem} - {self.tr('app.short_title')}")
        self._start_probe(path)

    def _on_media_ended(self) -> None:
        self.live_region.announce(self.tr("playback.state.ended"))
        if self.cfg.get("autoplay_next"):
            self.play_next()

    def _on_media_error(self, err: str) -> None:
        self.live_region.announce(self.tr("playback.state.error"))
        self.status_msg.setText(f"{self.tr('playback.state.error')}: {err}")

    def _start_probe(self, path: str) -> None:
        """يفحص ملف الوسائط في خلفية لإظهار الجودة والمسارات."""
        def work() -> None:
            info = media_probe.probe(path)
            QTimer.singleShot(0, lambda: self._on_probe_done(info))

        import threading

        threading.Thread(target=work, daemon=True).start()

    def _on_probe_done(self, info: media_probe.MediaInfo) -> None:
        self.media_info = info
        if not info.path:
            return
        parts = [info.display_title]
        q = info.quality_label
        if q:
            parts.append(q)
        d = format_duration(info.duration)
        if d != "0:00":
            parts.append(d)
        self.lbl_media.setText(" | ".join(parts))
        self.lbl_media.setAccessibleDescription(
            f"{info.display_title}, {q}, {d}, "
            f"{len(info.subtitles)} subtitle tracks, {len(info.audios)} audio tracks"
        )
        self._update_source_availability()

    # ==================================================================
    # شريط التقدّم والصوت
    # ==================================================================
    def _on_seek_start(self) -> None:
        self._seeking = True
        self.speech.stop()

    def _on_seek_move(self, value: int) -> None:
        dur = self.player.get_duration()
        if dur > 0:
            ms = int(value / 1000 * dur)
            self.lbl_time.setText(
                f"{format_duration(ms/1000)} / {format_duration(dur/1000)}"
            )

    def _on_seek_end(self) -> None:
        self._seeking = False
        val = self.seek.value()
        self.player.set_position(val / 1000.0)
        pos = self.player.get_time()
        self.engine.update(pos)
        self.engine.reset_announce()
        # بعد القفز ننسى آخر سطر حيّ حتى يُعاد نطق سطر الموضع الجديد ولو
        # كان نصّه مطابقاً لسطر سابق.
        self._last_live_sub = ""
        self.speak_policy.reset()

    def _on_volume(self, value: int) -> None:
        self.player.set_volume(value)
        if value > 0 and self.player.is_muted():
            self.player.set_muted(False)
        self.volume.blockSignals(True)
        self.volume.setValue(self.player.get_volume())
        self.volume.blockSignals(False)
        self.volume.setAccessibleDescription(f"{self.tr('playback.volume_slider')}: {value}%")
        if self.cfg.get("tts_announce_volume"):
            self.live_region.announce(f"{self.tr('playback.volume_slider')} {value}%")

    # ---------------------------------------------------------- السرعة
    def _set_rate(self, rate: float) -> None:
        self.player.set_rate(rate)
        r = self.player.get_rate()
        self.lbl_speed.setText(f"{r:.2f}x")
        self.lbl_speed.setAccessibleDescription(
            f"{self.tr('playback.speed_label')} {r:.2f}"
        )
        self.live_region.announce(f"{self.tr('playback.speed_label')} {r:.2f}")

    def _nudge_rate(self, delta: float) -> None:
        self._set_rate(self.player.get_rate() + delta)

    def _reset_rate(self) -> None:
        self._set_rate(1.0)

    def _nudge_volume(self, delta: int) -> None:
        self._on_volume(self.player.get_volume() + delta)

    def _toggle_mute(self) -> None:
        muted = self.player.toggle_mute()
        self.live_region.announce(
            self.tr("mute_toggle") + ": " + ("on" if muted else "off")
        )

    # ==================================================================
    # العرض
    # ==================================================================
    def toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self.video.setFullScreen(True)
            self.player.set_fullscreen(True)
            self.readout.setVisible(True)
        else:
            self.video.setFullScreen(False)
            self.player.set_fullscreen(False)
        self.live_region.announce(
            self.tr("fullscreen") if self._fullscreen else self.tr("exit_fullscreen")
        )

    def _on_panel_toggled(self, on: bool) -> None:
        self.readout.setVisible(on)

    def _on_playlist_toggled(self, on: bool) -> None:
        self.playlist_dock.setVisible(on)

    def _toggle_playlist(self) -> None:
        """يبدّل حالة قائمة التشغيل دون التكرار عبر إشارات QAction."""
        act = self._act["toggle_playlist"]
        act.setChecked(not act.isChecked())

    def _show_main_menu(self) -> None:
        self.menuBar().activate()

    # ==================================================================
    # القوائم الأخيرة
    # ==================================================================
    def _load_recent_menu(self) -> None:
        menu = self._menus.get("recent")
        if menu is None:
            return
        menu.clear()
        files = self.cfg.recent_files()
        if not files:
            a = menu.addAction(self.tr("none"))
            a.setEnabled(False)
            return
        for f in files:
            a = menu.addAction(Path(f).name)
            a.setToolTip(f)
            a.triggered.connect(lambda _=False, p=f: self.open_recent(p))
        menu.addSeparator()
        menu.addAction(self.tr("menu.clear_recent"), self.cfg.clear_recent)

    # ==================================================================
    # قائمة التشغيل
    # ==================================================================
    def _on_playlist_activate(self, item: QListWidgetItem) -> None:
        row = self.playlist_list.row(item)
        if row >= 0:
            self.play_index(row)

    def _on_playlist_row(self, row: int) -> None:
        pass  # التفعيل بالنقر المزدوج أو Enter

    def _remove_selected(self) -> None:
        for row in sorted((self.playlist_list.selectedItems()), reverse=True,
                          key=lambda it: self.playlist_list.row(it)):
            idx = self.playlist_list.row(row)
            if 0 <= idx < len(self.playlist):
                del self.playlist[idx]
                self.playlist_list.takeItem(row)
        self._reindex()

    def _clear_playlist(self) -> None:
        self.playlist.clear()
        self.playlist_list.clear()
        self.current_index = -1
        self.status_msg.setText(self.tr("playlist.count") + ": 0")

    def _reindex(self) -> None:
        for i, item in enumerate(self.playlist):
            if i < self.playlist_list.count():
                self.playlist_list.item(i).setText(f"{i + 1}. {item.title}")

    # ==================================================================
    # النوافذ
    # ==================================================================
    def open_search_dialog(self) -> None:
        from .search_dialog import SubtitleSearchDialog

        dlg = SubtitleSearchDialog(self, self.tr, self.cfg)
        dlg.subtitle_chosen.connect(self.load_subtitle_path)
        dlg.open_site_requested.connect(self._open_site)
        dlg.exec()

    def open_merge_dialog(self) -> None:
        from .merge_dialog import MergeDialog

        video = self.current_path if self.current_path else ""
        dlg = MergeDialog(self, self.tr, self.cfg, video)
        dlg.exec()

    def open_preferences(self) -> None:
        from .prefs_dialog import PreferencesDialog

        dlg = PreferencesDialog(self, self.tr, self.cfg)
        if dlg.exec() == PreferencesDialog.DialogCode.Accepted:
            self.tr.set_language(self.cfg.lang)
            self._apply_language()
            self._init_speech()
            self.readout.setVisible(bool(self.cfg.get("sub_panel_visible")))
            self._apply_subtitle_style()
            self.player.set_decode_threads(
                int(self.cfg.get("decode_threads") or 0)
            )
            self.player.set_output_device(int(self.cfg.get("audio_device") or -1))
            self.sync_timer.start(100)
            self.sub_mgr.set_mode(str(self.cfg.get("sub_source_mode") or "auto"))
            self._update_source_availability()
            self._sync_active_source(force=True)
            self.live_region.announce(self.tr("prefs.title"))

    def open_audio_diagnostics(self) -> None:
        """
        يقرأ بصوت مسموع أرقام جودة الصوت الحالية مع أثناء التشغيل،
        ليتبيّن مصدر التقطيع: الجهاز أم المخزن.
        """
        try:
            d = self.player.audio_diagnostics()
        except Exception:
            d = {}
        name = self.tr("prefs.audio_default")
        try:
            for idx, nm in self.player.audio_devices():
                if idx == d.get("device", -1):
                    name = nm
                    break
        except Exception:
            pass
        rate = int(d.get("out_rate", 0) or 0)
        parts = [
            f"{self.tr('diag.device')}: {name}",
            f"{self.tr('diag.rate')}: {rate}Hz",
            f"{self.tr('diag.callbacks')}: {d.get('callbacks', 0)}",
            f"{self.tr('diag.underruns')}: {d.get('underruns', 0)}",
            f"{self.tr('diag.late')}: {d.get('late_callbacks', 0)}",
            f"{self.tr('diag.queue')}: {d.get('queue', 0)}/{d.get('queue_max', 0)}",
        ]
        if d.get("sd_error"):
            parts.append(str(d.get("sd_error")))
        msg = "، ".join(parts)
        self.status_msg.setText(msg)
        self.live_region.announce(msg)

    def open_requirements(self) -> None:
        from .requirements_dialog import RequirementsDialog

        dlg = RequirementsDialog(self, self.tr, self.cfg)
        if dlg.exec():
            self._init_player()
            self._init_speech()

    def open_shortcuts(self) -> None:
        from .shortcuts_dialog import ShortcutsDialog

        ShortcutsDialog(self, self.tr).exec()

    def open_about(self) -> None:
        """
        نافذة «حول» قابلة للوصول: تُعرَض في نافذة مخصّصة لا في QMessageBox،
        ويُعلن قارئ الشاشة محتواها، وتتضمّن بيانات التواصل مع المطوّر.
        """
        from .about_dialog import AboutDialog, build_info_html, qt_version_str

        ok, err = av_engine.av_available()
        ff_ok = bool(media_probe.has_ffmpeg())
        kind = getattr(self.player, "engine_kind", "pyav")
        eng_ver = getattr(self.player, "engine_version", "") or ""
        engine_line = (
            self.tr("deps.engine_ok") if ok else self.tr("deps.engine_missing")
        )
        engine_line += f" ({self.tr(f'engine.{kind}')}, {eng_ver})" if eng_ver else ""
        if not ok and err:
            engine_line += f": {err}"
        html = build_info_html(
            self.tr, version=__version__, engine_line=engine_line,
            ffmpeg_ok=ff_ok, qt_version=qt_version_str(),
        )
        dlg = AboutDialog(self, self.tr, html)
        self.live_region.announce(
            self.tr("about") + ". " + self.tr("about.contact") + ": "
            + contact.contact_text().replace("\n", ", ")
        )
        dlg.exec()

    # ==================================================================
    # أدوات
    # ==================================================================
    def _notify(self, key: str, extra: str = "") -> None:
        msg = self.tr(key)
        if extra:
            msg = f"{msg}: {extra}"
        self.status_msg.setText(msg)
        self.live_region.announce(msg)

    def _open_site(self, site: str, query: str) -> None:
        from ..providers import manager

        url = manager.manual_search_url(site, query)
        if url:
            webbrowser.open(url)

    # ==================================================================
    # السحب والإفلات
    # ==================================================================
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        if paths:
            self.open_paths(paths, play_first=True)
            event.acceptProposedAction()

    # ==================================================================
    # الإغلاق
    # ==================================================================
    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self._save_geometry()
            self.cfg.set("sub_panel_visible", self.readout.isVisible())
            self.cfg.sync()
        except Exception:
            pass
        self.sync_timer.stop()
        self.ui_timer.stop()
        self.speech.shutdown()
        self.player.release()
        super().closeEvent(event)