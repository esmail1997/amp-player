"""
وحدة تحكّم المشغّل — جسر رقيق بين محرّك FFmpeg (av_engine) وواجهة Qt.

هذا الجسر موجود لسبب واحد: محرّك الوسائط مكتوب بلا أي اعتماد على Qt ليسهل
اختباره وحده، بينما الواجهة تحتاج إشارات وطابور زمنياً. كل تحويل بين
العالميين يحدث هنا.

الواجهة العامة (methods و signals) لم تتغيّر عند تحويل المحرّك، فلا يحتاج
بقية البرنامج إلى تعديل.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QImage

from . import av_engine, config, mpv_engine


def _pick_engine(cfg: "config.Config") -> av_engine.MediaEngine:
    """
    يختار محرك التشغيل الفعلي.

    mpv هو الافتراضي الجديد (صوت mpv من داخل WASAPI المتقدّم، وهو ما أزال
    التقطيع)، مع تراجعٍ تلقائي كامل إلى محرك FFmpeg (PyAV) إن تعذّر تحميل
    libmpv على هذا النظام.
    """
    choice = str(cfg.get("player_engine") or "pyav")
    if choice == "mpv":
        eng = mpv_engine.MpvEngine(cfg)
        if eng.available:
            return eng
    return av_engine.MediaEngine(cfg)


class PlayerController(QObject):
    """غلاف Qt حول محرّك التشغيل."""

    # إشارات
    state_changed = Signal(str)            # playing/paused/stopped/ended
    time_changed = Signal(int)             # ميلي ثانية
    duration_changed = Signal(int)         # ميلي ثانية
    position_changed = Signal(float)       # نسبة 0..1
    volume_changed = Signal(int)
    muted_changed = Signal(bool)
    rate_changed = Signal(float)
    track_changed = Signal(str, int)       # النوع، الفهرس
    media_ended = Signal()
    media_opened = Signal(str)             # المسار
    media_error = Signal(str)
    buffered_changed = Signal(float)
    frame_available = Signal()             # هناك إطار جديد ينتظر الرسم

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.cfg = config.Config()
        self._engine = _pick_engine(self.cfg)
        self._ready = False

        self._duration = 0
        self._muted = False
        self._rate = 1.0
        self._volume = 100
        self._state = "stopped"
        self._last_time = -1
        self._sub_delay_us = 0
        self._sub_scale = 100
        self._fullscreen = False
        self._path = ""

        # المصنع الذي يستقبل الإطارات المرسومة (واجهة الفيديو)
        self._frame_sink: Optional[Callable[[QImage], None]] = None
        self._frame_lock = threading.Lock()
        self._frame_arr: Optional[np.ndarray] = None
        self._frame_size = (0, 0)
        self._last_frame: Optional[QImage] = None

        self._engine.on_frame = self._on_engine_frame
        self._engine.on_state = self._on_engine_state
        self._engine.on_end = self._on_engine_end
        self._engine.on_error = self._on_engine_error

        # مؤقت الواجهة: المحرّك لا يعرف Qt ولا يدفع إشارات. المؤقت يسأله
        # كل 100 ميلي ثانية، فسرعة التحديث ثابتة لا تتأثر بمحتوى الملف.
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        self.frame_available.connect(self._grab_frame)

    # ==================================================================
    # تهيئة
    # ==================================================================
    def initialize(self) -> Tuple[bool, str]:
        """يجهّز المحرّك. يعيد (نجاح، سبب الفشل)."""
        ok, err = self._engine.initialize()
        if not ok:
            return False, err
        self._ready = True
        self._timer.start()
        self.set_volume(self._volume)
        return True, ""

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def audio_output_available(self) -> bool:
        return self._engine.audio_output_available

    @property
    def audio_output_error(self) -> str:
        return self._engine.audio_output_error

    @property
    def engine_version(self) -> str:
        """نسخة محرك التشغيل الفعلي (mpv أو FFmpeg المدمج)، للعرض في النوافذ."""
        eng = getattr(self, "_engine", None)
        if eng is not None:
            v = getattr(eng, "engine_version", None)
            if v:
                return v
        return av_engine.av_version()

    @property
    def engine_kind(self) -> str:
        """mpv أم pyav — لرسائل الحالة ورسوم التشخيص."""
        return "mpv" if isinstance(self._engine, mpv_engine.MpvEngine) else "pyav"

    def set_frame_sink(self, sink: Optional[Callable[[QImage], None]]) -> None:
        self._frame_sink = sink

    def set_render_max(self, width: int, height: int) -> None:
        """يخبر المحرّكم بأقصى مقاس نعرضه، لتصغير الإطارات الأكبر قبل نسخها."""
        self._engine.set_render_max(width, height)

    def set_decode_threads(self, count: int) -> None:
        """عدد خيوط فك ترجمة الفيديو (0 = تلقائي)."""
        self._engine.set_decode_threads(count)

    def set_output_device(self, index: int) -> None:
        """يغيّر جهاز الإخراج الصوتي ويعيد فتح التدفّق فوراً إذا كان يعمل."""
        if self._ready:
            self._engine.set_output_device(index)

    def audio_devices(self) -> List[Tuple[int, str]]:
        """أجهزة الإخراج المتاحة: (الفهرس، الاسم)."""
        return self._engine.list_output_devices()

    def audio_diagnostics(self) -> dict:
        """أرقام جودة الصوت أثناء التشغيل (سياق قراءة صوتي)."""
        return self._engine.audio_diagnostics()

    def set_duck(self, on: bool) -> None:
        """خفض مؤقت لمستوى الصوت أثناء نطق القارئ (يمنع تراكب الصوتين)."""
        self._engine.set_duck(on)

    def clear_frame(self) -> None:
        with self._frame_lock:
            self._frame_arr = None
        self._last_frame = None

    @property
    def last_frame(self) -> Optional[QImage]:
        return self._last_frame

    # ==================================================================
    # الفتح
    # ==================================================================
    def load(self, path: str) -> Tuple[bool, str]:
        """يحمّل ملف وسائط محلياً. يعيد (نجاح، سبب الفشل)."""
        p = Path(path)
        if not p.exists():
            return False, f"file_not_found: {path}"
        return self._open(str(p))

    def load_url(self, url: str) -> Tuple[bool, str]:
        """يحمّل رابطاً شبكياً."""
        return self._open(url)

    def _open(self, path: str) -> Tuple[bool, str]:
        if not self._ready:
            return False, "player_not_ready"
        ok, err = self._engine.open(path)
        if not ok:
            self.media_error.emit(err)
            return False, err
        self._path = path
        self.clear_frame()
        self._duration = int(self._engine.get_duration() * 1000)
        self._last_time = -1
        self.duration_changed.emit(self._duration)
        self.buffered_changed.emit(1.0)
        self.track_changed.emit("es", 0)
        self.media_opened.emit(path)
        return True, ""

    @property
    def path(self) -> str:
        return self._path

    # ==================================================================
    # التشغيل
    # ==================================================================
    def play(self) -> None:
        if self._ready:
            self._engine.play()

    def pause(self) -> None:
        if self._ready:
            self._engine.pause()

    def toggle_pause(self) -> None:
        if self._ready:
            self._engine.toggle_pause()

    def stop(self) -> None:
        if not self._ready:
            return
        self._engine.stop()
        self._state = "stopped"
        self._duration = 0
        self._last_time = -1
        self.clear_frame()

    def is_playing(self) -> bool:
        return self._ready and self._engine.is_playing()

    def is_paused(self) -> bool:
        return self._ready and self._engine.is_paused()

    @property
    def state(self) -> str:
        return self._state

    # ==================================================================
    # التنقل
    # ==================================================================
    def get_time(self) -> int:
        if not self._ready:
            return 0
        return int(self._engine.get_time() * 1000)

    def get_duration(self) -> int:
        if not self._ready:
            return 0
        return int(self._engine.get_duration() * 1000)

    def set_time(self, ms: int) -> None:
        if self._ready:
            self._engine.set_time(max(0, int(ms)) / 1000.0)

    def get_position(self) -> float:
        if not self._ready:
            return 0.0
        return self._engine.get_position()

    def set_position(self, ratio: float) -> None:
        if self._ready:
            self._engine.set_position(max(0.0, min(1.0, float(ratio))))

    def seek_relative(self, delta_ms: int) -> None:
        cur = self.get_time()
        if cur <= 0:
            return
        dur = self.get_duration()
        target = cur + delta_ms
        if dur > 0:
            target = max(0, min(max(0, dur - 500), target))
        else:
            target = max(0, target)
        self.set_time(target)

    # ==================================================================
    # الصوت
    # ==================================================================
    def set_volume(self, vol: int) -> None:
        self._volume = max(0, min(200, int(vol)))
        if self._ready:
            self._engine.set_volume(self._volume)
        self.volume_changed.emit(self._volume)

    def get_volume(self) -> int:
        return self._volume

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self._ready:
            self._engine.set_muted(self._muted)
        self.muted_changed.emit(self._muted)

    def toggle_mute(self) -> bool:
        self.set_muted(not self._muted)
        return self._muted

    def is_muted(self) -> bool:
        return self._muted

    # ==================================================================
    # السرعة
    # ==================================================================
    def set_rate(self, rate: float) -> None:
        self._rate = max(0.25, min(4.0, float(rate)))
        if self._ready:
            self._engine.set_rate(self._rate)
        self.rate_changed.emit(self._rate)

    def get_rate(self) -> float:
        return self._rate

    # ==================================================================
    # المسارات
    # ==================================================================
    def get_audio_tracks(self) -> List[Tuple[int, str]]:
        """قائمة مسارات الصوت (الفهرس، الوصف)."""
        if not self._ready:
            return []
        return [(t.index, t.label) for t in self._engine.get_tracks("audio")]

    def set_audio_track(self, index: int) -> bool:
        """
        يختار مسار صوت.

        المحرك يفك ترميز مسار واحد فقط، فالتبديل يعيد فتح الملف على المسار
        الجديد مع الحفاظ على موضع التشغيل.
        """
        if not self._ready:
            return False
        if not self._engine.select_audio_stream(int(index)):
            return False
        self.track_changed.emit("audio", int(index))
        return True

    # ==================================================================
    # الترجمة الخارجية
    # ==================================================================
    def attach_subtitle(self, sub_path: str) -> bool:
        """يُرفق ملف ترجمة خارجياً بمحرك التشغيل (mpv) ليُقا فع نصّه لحظياً."""
        if not self._ready:
            return False
        fn = getattr(self._engine, "attach_subtitle", None)
        if fn is None:
            return False
        try:
            return bool(fn(sub_path))
        except Exception:
            return False

    def current_subtitle_text(self) -> str:
        """السطر النشط حالياً من محرك التشغيل (mpv sub-text)، أو نص فارغ."""
        if not self._ready:
            return ""
        fn = getattr(self._engine, "current_subtitle_text", None)
        if fn is None:
            return ""
        try:
            return str(fn() or "")
        except Exception:
            return ""

    def select_subtitle_stream(self, stream_index: Optional[int]) -> bool:
        """يختار مسار ترجمة مدمجاً في محرك التشغيل (mpv) أو يلغيه بـ None."""
        if not self._ready:
            return False
        fn = getattr(self._engine, "select_subtitle_stream", None)
        if fn is None:
            return False
        try:
            return bool(fn(stream_index))
        except Exception:
            return False

    def get_subtitle_tracks(self) -> List[av_engine.TrackInfo]:
        """مسارات الترجمة المدمجة كما يراها المحرك (كلا المحركين)."""
        if not self._ready:
            return []
        try:
            return list(self._engine.get_tracks("subtitle"))
        except Exception:
            return []

    def load_external_subtitle(self, sub_path: str) -> bool:
        """
        لم يعد للمحرّك ما يعمل به هنا.

        ملفات الترجمة الخارجية يقرأها محرّك الترجمة في الواجهة مباشرة،
        وهو مصدر واحد للحقيقة بدل تحميلها مرتين.
        """
        return Path(sub_path).exists()

    def set_sub_delay(self, microseconds: int) -> None:
        """يضبط إزاحة توقيت الترجمة (بالميكروثانية، موجب = تقديم)."""
        self._sub_delay_us = int(microseconds)
        if self._ready:
            self._engine.set_sub_delay(self._sub_delay_us / 1_000_000.0)

    def get_sub_delay(self) -> int:
        return self._sub_delay_us

    def set_sub_text_scale(self, percent: int) -> None:
        """يضبط حجم نص الترجمة المعروض على الشاشة (نسبة مئوية)."""
        self._sub_scale = max(25, min(500, int(percent)))

    def get_sub_text_scale(self) -> int:
        return self._sub_scale

    # ==================================================================
    # ملء الشاشة
    # ==================================================================
    def set_fullscreen(self, on: bool) -> None:
        """
        ملء الشاشة теперь شأن النافذة لا المحرّك.

        الصورة إلينا نحن، فالنافذة هي من يجب أن تكبر.
        """
        self._fullscreen = bool(on)

    def is_fullscreen(self) -> bool:
        return self._fullscreen

    # ==================================================================
    # الأحداث الداخلية
    # ==================================================================
    def _on_engine_frame(self, arr: np.ndarray, w: int, h: int) -> None:
        """
        يستقبل الإطار من خيط فك الترجمة.

        نكتظظ بالحيّز الواحد فقط: إن تأخّرت الواجهة، يُهمل الإطار القديم
        ويُعرض الأحدث. تخزين طابور كامل يعرض فيديو متأخراً ويأكل الذاكرة.
        """
        with self._frame_lock:
            self._frame_arr = arr
            self._frame_size = (w, h)
        # QImage غير آمن البناء من خارج خيط الرسم، فالتقاط يجري هناك.
        self.frame_available.emit()

    def _on_engine_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _on_engine_end(self) -> None:
        self._state = "stopped"
        self.media_ended.emit()

    def _on_engine_error(self, msg: str) -> None:
        self.media_error.emit(msg)

    @Slot()
    def _grab_frame(self) -> None:
        """يحوّل أحدث إطار إلى صورة Qt (يُستدعى في خيط الواجهة).

        لا نستخدم arr.data مباشرةً: عرض numpy هذا غير متصل (strides بأبعاد
        وسادة الصفوف) وقد يرفضه PySide6 (BufferError) أو يقرأ ذاكرة مُعاد
        استخدامها من خيط الرسم، فيبقى الشاشة سوداء. نقل محكم عبر tobytes().
        """
        with self._frame_lock:
            arr = self._frame_arr
            w, h = self._frame_size
        if arr is None or w <= 0 or h <= 0:
            return
        try:
            # tobytes() يحوّل العرض (ح، عرض، 3) إلى بايتات متجاورة بلا وسادة،
            # فتصير bytesPerLine = عرض*3 وتُعرض الصورة صحيحة دائماً.
            img = QImage(arr.tobytes(), w, h, w * 3,
                         QImage.Format.Format_RGB888).copy()
        except Exception:
            return
        self._last_frame = img
        if self._frame_sink is not None:
            try:
                self._frame_sink(img)
            except Exception:
                pass

    @Slot()
    def _poll(self) -> None:
        """يبدّل إشارات الزمن والمدة والمحلّات حسب حالة المحرّك."""
        if not self._ready:
            return
        dur_ms = int(self._engine.get_duration() * 1000)
        if dur_ms != self._duration:
            self._duration = dur_ms
            self.duration_changed.emit(dur_ms)
        t_ms = int(self._engine.get_time() * 1000)
        if t_ms != self._last_time:
            self._last_time = t_ms
            self.time_changed.emit(t_ms)
            if dur_ms > 0:
                self.position_changed.emit(max(0.0, min(1.0, t_ms / dur_ms)))

    # ==================================================================
    # إيقاف
    # ==================================================================
    def release(self) -> None:
        self._timer.stop()
        self._ready = False
        self._engine.on_frame = None
        self._engine.on_state = None
        self._engine.on_end = None
        self._engine.on_error = None
        try:
            self._engine.close()
        except Exception:
            pass
        self.clear_frame()