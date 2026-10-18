"""
محرّك تشغيل الوسائط — مبني على FFmpeg عبر PyAV، بلا أي مشغّل خارجي.

لماذا PyAV؟ حزمة `av` في بايثون تحتوي مكتبات FFmpeg (libavcodec,
libavformat, libswscale, libswresample) **داخلها**، فيعمل البرنامج بعد
تثبيت `av` وحده، بلا تثبيت أي مشغّل أو أدوات على النظام.

المبدأ:
  - خيط واحد «يزيل التغليف» (demux) ويزعّم الحزم على قوائم لكل مسار، لأن
    حاوية PyAV ليست آمنة للاستخدام المتزامن من عدة خيوط.
  - خيط فيديو: يفك الترميز، يحوّل الإطار إلى RGB، ويسلّمه للواجهة.
  - خيط صوت: يفك الترميز، يعيد التشكيل، ويكتب في جهاز الصوت. الكتابة
    تحجب الخيط، فتُصلح الإيقاع تلقائياً. والكتابة تُعطي ساعة الجهاز.
  - يقتصر دعم الترجمة على الملفات الخارجية، وتُقرأ عبر SubtitleEngine.
"""

from __future__ import annotations

import fractions
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

import numpy as np

from . import config
from .subtitle_parser import Cue, find_cue

try:  # PyAV مطلوب للتشغيل
    import av  # type: ignore

    _AV_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover
    av = None  # type: ignore
    _AV_IMPORT_ERROR = str(exc)

# ------------------------------------------------------------------ ثوابت
OUT_CHANNELS = 2
OUT_BLOCK = 1024         # مقاس كتلة الكتابة للجهاز
# عمق مخزن الصوت: نحتاج هامشاً لتفادي النقص في التشغيل، لكن كلما زاد تأخّر
# نهاية الملف وزاد الفارق بين زمن الضغط والقفزة. نصف ثانية تكفي والملفات
# المحلية لا تتلعثم عندها.
AUDIO_BLOCKS = 32
DEMUX_QUEUE = 24         # عمق قائمة الحزم بين الخيوط
MIN_RATE = 0.25
MAX_RATE = 4.0
BASE_RATE = 48000
SYNC_AHEAD = 0.06        # مقدار التقدّم المسموح للإطار قبل عرضه
SYNC_DROP = 1.00         # الإطار الأقدم من هذا يُهمل

# نعيد التشكيل إلى عيّنات_planar من نوع float32: يُسهّل تطبيق الصوت بلا
# قصّ، ويدعمه PortAudio أصلاً بلا تحويل.
_RESAMPLE_OPTS = {"layout": "stereo", "format": "fltp"}


def av_available() -> Tuple[bool, str]:
    """هل مكتبة PyAV جاهزة؟ يعيد (متاح، سبب الفشل)."""
    if av is None:
        return False, _AV_IMPORT_ERROR or "pyav_not_installed"
    return True, ""


def av_version() -> str:
    """نسخة FFmpeg المدمجة، للعرض في نافذة «حول البرنامج»."""
    if av is None:
        return ""
    try:
        parts = []
        for lib in ("libavcodec", "libavformat"):
            ver = av.library_versions.get(lib)
            if ver:
                parts.append(f"{lib.replace('libav', '')} "
                             f"{'.'.join(str(x) for x in ver)}")
        return "FFmpeg " + ", ".join(parts) if parts else ""
    except Exception:
        return ""


def _default_output_index(sd) -> int:
    """
    الفهرس العالمي لجهاز الإخراج الافتراضي الفعلي:
    - مخرج WASAPI الافتراضي إن وُجد (هو ما يفتحه المحرّك الآن تلقائياً)،
    - وإلا افتراضي PortAudio.
    """
    try:
        for ha in sd.query_hostapis():
            if "wasapi" in str(ha.get("name", "")).lower():
                d = int(ha.get("default_output_device") or -1)
                if d >= 0:
                    return d
    except Exception:
        pass
    try:
        default = sd.default.device
        return default[1] if isinstance(default, (tuple, list)) else int(default)
    except Exception:
        return -1


def output_devices() -> List[Tuple[int, str]]:
    """أجهزة الإخراج الصوتية المتاحة: (الفهرس، الاسم). بلا إنشاء محرّك."""
    sd, _ = _import_sounddevice()
    if sd is None:
        return []
    try:
        out = _default_output_index(sd)
        result: List[Tuple[int, str]] = []
        for i, d in enumerate(sd.query_devices()):
            if int(d.get("max_output_channels", 0) or 0) > 0:
                name = str(d.get("name", "")).strip()
                if name:
                    result.append((i, name + (" (default)" if i == out else "")))
        return result
    except Exception:
        return []


def _import_sounddevice():
    """يستورد sounddevice بشكل مؤجل (قد لا يكون مثبتاً)."""
    try:
        import sounddevice as sd  # type: ignore

        return sd, ""
    except Exception as exc:
        return None, str(exc)


# ------------------------------------------------------------------ الأنواع
@dataclass
class TrackInfo:
    index: int
    kind: str          # audio | video | subtitle
    language: str = ""
    title: str = ""
    codec: str = ""
    channels: int = 0
    sample_rate: int = 0
    width: int = 0
    height: int = 0
    @property
    def label(self) -> str:
        """وصف مقروء لقارئ الشاشة."""
        bits = [f"{self.kind} #{self.index + 1}"]
        if self.language:
            bits.append(self.language)
        if self.title:
            bits.append(self.title)
        if self.codec:
            bits.append(self.codec)
        extra = []
        if self.channels:
            extra.append(f"{self.channels}ch")
        if self.sample_rate:
            extra.append(f"{self.sample_rate}Hz")
        if self.width:
            extra.append(f"{self.width}x{self.height}")
        if extra:
            bits.append(" ".join(extra))
        return " - ".join(bits)


@dataclass
class MediaInfo:
    path: str = ""
    duration: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    video_size: str = ""
    tracks: List[TrackInfo] = field(default_factory=list)


# ------------------------------------------------------------------ أدوات
def _safe_seconds(value: Any, tb: Optional[fractions.Fraction]) -> Optional[float]:
    """يحوّل pts إلى ثوانٍ بأمان."""
    if value is None:
        return None
    try:
        if tb is None:
            return float(value)
        return float(value * tb)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


# ------------------------------------------------------------------ المحرّك
class MediaEngine:
    """
    محرّك تشغيل مستقل عن Qt ليسهل اختباره.

    الأحداث تُبلَّغ عبر دوال تُسند إلى الخصائص التالية بعد الإنشاء:
        on_frame(ndarray_rgb, width, height)
        on_state(str)
        on_end()
        on_error(str)
        on_loaded(MediaInfo)
    """

    def __init__(self, cfg: Optional[config.Config] = None) -> None:
        self.cfg = cfg or config.Config()

        # ----- خصائص الاستجابة -----
        self.on_frame: Optional[Callable[[np.ndarray, int, int], None]] = None
        self.on_state: Optional[Callable[[str], None]] = None
        self.on_end: Optional[Callable[[], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_loaded: Optional[Callable[[MediaInfo], None]] = None

        # ----- الحاوية والمسارات -----
        self._container: Any = None
        self._video_codec: Any = None
        self._audio_codec: Any = None
        self._video_stream: Any = None
        self._audio_stream: Any = None
        self._info = MediaInfo()

        # ----- الخيوط -----
        self._lock = threading.RLock()
        self._seek_lock = threading.RLock()
        self._playing = threading.Event()
        self._stop_flag = threading.Event()
        self._threads: List[threading.Thread] = []
        self._video_q: "queue.Queue" = queue.Queue(maxsize=DEMUX_QUEUE)
        self._audio_q: "queue.Queue" = queue.Queue(maxsize=DEMUX_QUEUE)
        self._eos = False
        self._decoders_done = 0
        self._decoders_total = 0
        # جيل التشغيل: كل مجموعة خيوط تأخذ رقماً. بدون هذا، خيوط المجموعة
        # السابقة قد تُنهي خيوطَ المجموعة الجديدة عند القفز في الزمن
        # (increment بعد إعادة الضبط) فيتوقف التشغيل بعد أول قفزة.
        self._generation = 0
        self._state = "stopped"

        # ----- الصوت -----
        self._sd: Any = None
        self._sd_error = ""
        self._out: Any = None
        self._resampler: Any = None
        self._volume = 100
        self._muted = False
        self._rate = 1.0
        self._out_rate = BASE_RATE
        # نستعمل واجهة callback في PortAudio بدل write المحجوبة: خيط فك
        # الترجمة لا يتجمّد أبداً على الجهاز، وهذا ما يجعل الإيقاف وإغلاق
        # التدفّق من خيط آخر آمناً (كان يغلق تحت حجز الجهاز ويعلّقها).
        self._audio_blocks: "queue.Queue" = queue.Queue(maxsize=AUDIO_BLOCKS)
        self._written_samples = 0      # عينات سلّمناها ل PortAudio
        self._played_samples = 0       # عينات استهلكها الجهاز فعلياً
        self._media_cursor = 0.0       # زمن الوسائط عند أول عيّنة لم تُكتب
        self._use_device_clock = False
        self._rate_change = threading.Event()   # يطلب خيط الصوت إعادة الفتح

        # ----- الساعة (احتياطية بلا صوت) -----
        self._clock_media = 0.0
        self._clock_anchor = time.perf_counter()
        self._paused_at = 0.0

        # ----- الترجمة -----
        self._cues: List[Cue] = []
        self._sub_delay_ms = 0

        self._render_max = (0, 0)
        self._prefer_audio_index = -1      # المسار الصوتي المطلوب عند الفتح
        # 0 = يقرّر FFmpeg بنفسه. نقرأ من الإعدادات مباشرةً بدل setter،
        # حتى لا نحتاج كل من يغيّره أن يتذكّر استدعاءً إضافياً.
        try:
            self._decode_threads = int(
                self.cfg.get("decode_threads") or 0)
        except Exception:
            self._decode_threads = 0
        # فهرس جهاز الإخراج الصوتي: 1- يعني جهاز النظام الافتراضي
        try:
            self._device_index = int(self.cfg.get("audio_device") or -1)
        except Exception:
            self._device_index = -1
        # عدادات تشخيص الصوت: تُقرأ من أداة «تشخيص الصوت» في قائمة أدوات
        self._audio_callbacks = 0
        self._underruns = 0
        self._late_callbacks = 0
        self._last_callback_t = 0.0
        # خفض مؤقت لمستوى الصوت أثناء نطق قارئ الترجمة حتى لا يتراكب
        # صوت الفيلم مع صوت النطق فيصبح الكلام غير مفهوم.
        self._duck = False
        self._duck_gain = 0.45

    # ==================================================================
    # التهيئة
    # ==================================================================
    def initialize(self) -> Tuple[bool, str]:
        """
        يجهّز محرّك الصوت.

        لا يفشل إن لم يوجد جهاز صوت: سيعمل الفيديو فقط ويُبطأ بالساعة.
        """
        ok, err = av_available()
        if not ok:
            return False, err
        # غياب sounddevice ليس خطأ: نعمل بلا صوت ونتابع الزمن بالساعة.
        self._sd, self._sd_error = _import_sounddevice()
        return True, ""

    @property
    def audio_output_available(self) -> bool:
        return self._sd is not None

    @property
    def audio_output_error(self) -> str:
        return self._sd_error

    @property
    def info(self) -> MediaInfo:
        return self._info

    @property
    def cues(self) -> List[Cue]:
        return list(self._cues)

    def cue_at(self, pos_ms: int) -> Optional[Cue]:
        """
        السطر الذي يغطي الزمن المعطى (بالميلي ثانية)، مع الإزاحة.

        نستدعي المحلّل نفسه الذي تستعمله واجهة القراءة، لا بحثاً ثانياً
        خاصاً بنا. حين كان لكل منهما بحث ثنائي خاص به أظهر أحدهما سطراً
        والآخر لا، فقرأ المستخدم سطراً على الشاشة ونطق غيره.
        """
        if not self._cues:
            return None
        return find_cue(self._cues, pos_ms - self._sub_delay_ms)

    def set_render_max(self, width: int, height: int) -> None:
        """أكبر مقاس نرسم عنده: تُصغَّر الإطارات الأكبر لتقليل النسخ."""
        self._render_max = (int(width or 0), int(height or 0))

    def set_output_device(self, index: int) -> None:
        """
        يغيّر جهاز الإخراج الصوتي (1- = افتراضي النظام).

        إن كان الصوت يعمل نعيد فتح التدفّق فوراً على الجهاز الجديد، فلا
        نحتاج لإيقاف التشغيل. هذا مهم لمستخدم اختار جهازاً غير الافتراضي
        (مثل بلوتوث) ثم ظهرت أجهزة أخرى.
        """
        self._device_index = int(index or -1)
        if self._sd is None or self._out is None or not self._playing.is_set():
            return
        try:
            self._reopen_audio_for_rate()
        except Exception:
            pass

    def list_output_devices(self) -> List[Tuple[int, str]]:
        """أجهزة الإخراج المتاحة: (فهرس، اسم). يُعلَّم الجهاز الافتراضي."""
        if self._sd is None:
            return []
        try:
            out = _default_output_index(self._sd)
            result: List[Tuple[int, str]] = []
            for i, d in enumerate(self._sd.query_devices()):
                if int(d.get("max_output_channels", 0) or 0) > 0:
                    name = str(d.get("name", "")).strip()
                    if name:
                        result.append((i, name + (" (default)" if i == out else "")))
            return result
        except Exception:
            return []

    def set_duck(self, on: bool) -> None:
        """
        يخفض مستوى صوت الفيديو مؤقتاً أثناء نطق قارئ الترجمة.

        بدون هذا يتراكب صوتا الفيلم والقارئ على الجهاز نفسه فيصبح الكلام
        متشابكاً غير مفهوم، وتتأثر استدعاءات الجهاز كما أظهر القياس.
        """
        self._duck = bool(on)

    def audio_diagnostics(self) -> dict:
        """
        أرقام جودة الصوت أثناء التشغيل، لتعرف من القراءة الصوتية هل
        التقطيع قادم من الجهاز (تأخّر استدعاء) أم من المحرّك (فراغ المخزن).
        """
        return {
            "device": self._device_index,
            "out_rate": self._out_rate,
            "callbacks": self._audio_callbacks,
            "underruns": self._underruns,
            "late_callbacks": self._late_callbacks,
            "queue": self._audio_blocks.qsize() if self._audio_blocks else 0,
            "queue_max": AUDIO_BLOCKS,
            "sd_error": self._sd_error or "",
        }

    def set_decode_threads(self, count: int) -> None:
        """عدد خيوط فك الترميز. صفر يعني ترك FFmpeg يقرّر."""
        self._decode_threads = max(0, int(count or 0))
        self._apply_decode_threads()

    # ==================================================================
    # الفتح
    # ==================================================================
    def open(self, path: str) -> Tuple[bool, str]:
        """يفتح ملفاً محلياً أو رابطاً. يعيد (نجاح، سبب الفشل)."""
        if av is None:
            return False, "pyav_not_installed"
        self.close()

        remote = "://" in path
        if not remote and not Path(path).exists():
            return False, f"file_not_found: {path}"

        try:
            if remote:
                self._container = av.open(path, options={"rw_timeout": "20000000"})
            else:
                self._container = av.open(str(Path(path).resolve()))
        except Exception as exc:
            self._container = None
            return False, f"open_failed: {exc}"

        try:
            self._analyse()
        except Exception as exc:
            self.close()
            return False, f"analyse_failed: {exc}"

        self._stop_flag.clear()
        self._set_state("stopped")
        if self.on_loaded is not None:
            try:
                self.on_loaded(self._info)
            except Exception:
                pass
        return True, ""

    def _analyse(self) -> None:
        """يقرأ معلومات المسارات والمدة."""
        c = self._container
        if c is None:
            raise RuntimeError("no_container")
        if not c.streams.video and not c.streams.audio:
            raise RuntimeError("no_playable_streams")

        dur = 0.0
        if c.duration:
            dur = float(c.duration) / 1_000_000.0

        info = MediaInfo(path=str(getattr(c, "name", "") or ""), duration=dur)
        audio_candidates: List[Any] = []
        video_stream = None
        for st in c.streams:
            cc = st.codec_context
            meta = dict(st.metadata or {})
            info.tracks.append(
                TrackInfo(
                    index=st.index,
                    kind=st.type,
                    language=str(meta.get("language") or "").strip(),
                    title=str(meta.get("title") or "").strip(),
                    codec=cc.name or "",
                    channels=int(getattr(cc, "channels", 0) or 0),
                    sample_rate=int(getattr(cc, "sample_rate", 0) or 0),
                    width=int(getattr(cc, "width", 0) or 0),
                    height=int(getattr(cc, "height", 0) or 0),
                )
            )
            if st.type == "video" and video_stream is None:
                video_stream = st
                info.has_video = True
                info.video_size = f"{int(cc.width)}x{int(cc.height)}"
            elif st.type == "audio":
                audio_candidates.append(st)

        # نختار المسار الصوتي المطلوب إن حُدّد، وإلا أول مسار
        audio_stream = None
        if audio_candidates:
            if self._prefer_audio_index >= 0:
                audio_stream = next(
                    (s for s in audio_candidates
                     if s.index == self._prefer_audio_index),
                    None,
                )
            if audio_stream is None:
                audio_stream = audio_candidates[0]
            info.has_audio = True
        self._prefer_audio_index = -1

        self._video_stream = video_stream
        self._audio_stream = audio_stream
        # نستعمل سياق الترميز نفسه الذي احتواه الملف: يحمل البيانات التمهيدية
        # (extradata) اللازمة لفك ترميز بعض الصيغ مثل HEVC وAAC.
        self._video_codec = getattr(video_stream, "codec_context", None)
        self._audio_codec = getattr(audio_stream, "codec_context", None)
        self._apply_decode_threads()

        if info.duration <= 0 and video_stream is not None:
            if video_stream.duration and video_stream.time_base:
                info.duration = float(video_stream.duration * video_stream.time_base)
        if info.duration <= 0 and audio_stream is not None:
            if audio_stream.duration and audio_stream.time_base:
                info.duration = float(audio_stream.duration * audio_stream.time_base)
        self._info = info

        # مسارات الترجمة المدمجة لا تُفكّ هنا أثناء التشغيل؛ استخراجها إلى
        # أسطر يجري في embedded_subs.extract_embedded_cues (خيط خلفي).
        self._cues = []

    def _apply_decode_threads(self) -> None:
        """
        يضبط عدد خيوط فك ترجمة الفيديو.

        FFmpeg يوزّع إطار الفيديو على عدة خيوط، وهذا ما يجعل 4K سلساً على
        معالج متعدد النواة. صفر يعني «قرّر أنت»، وهو الافتراضي المناسب.
        """
        cc = self._video_codec
        if cc is None or self._decode_threads <= 0:
            return
        try:
            cc.thread_count = int(self._decode_threads)
            cc.thread_type = "AUTO"
        except Exception:
            pass

    # ==================================================================
    # التشغيل
    # ==================================================================
    def play(self) -> None:
        if self._container is None:
            return
        alive = [t for t in self._threads if t.is_alive()]
        if alive:
            if self._playing.is_set():
                return
            self._resume_audio()
            self._clock_media = self._paused_at
            self._clock_anchor = time.perf_counter()
            self._playing.set()
            self._set_state("playing")
            return
        self._stop_flag.clear()
        self._playing.set()
        self._clock_media = self._paused_at
        self._clock_anchor = time.perf_counter()
        self._start_threads()
        self._set_state("playing")

    def pause(self) -> None:
        if not self._playing.is_set():
            return
        self._paused_at = self.get_time()
        self._playing.clear()
        self._suspend_audio()
        self._set_state("paused")

    def toggle_pause(self) -> None:
        self.pause() if self._playing.is_set() else self.play()

    def is_playing(self) -> bool:
        return self._playing.is_set()

    def is_paused(self) -> bool:
        return self._state == "paused"

    def stop(self) -> None:
        self._teardown_threads()
        self._close_audio()
        with self._lock:
            self._state = "stopped"
            self._eos = False
            self._clock_media = 0.0
            self._paused_at = 0.0
        self._playing.clear()
        self._set_state("stopped")

    def close(self) -> None:
        self.stop()
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
        self._container = None
        self._video_stream = None
        self._audio_stream = None
        self._video_codec = None
        self._audio_codec = None
        self._cues = []
        self._info = MediaInfo()

    # ---------------------------------------------------------- الخيوط
    def _start_threads(self) -> None:
        self._stop_flag.clear()
        self._video_q = queue.Queue(maxsize=DEMUX_QUEUE)
        self._audio_q = queue.Queue(maxsize=DEMUX_QUEUE)
        self._generation += 1
        gen = self._generation
        with self._lock:
            self._eos = False
        self._decoders_done = 0
        self._decoders_total = 0
        if self._video_stream is not None:
            self._decoders_total += 1
        if self._audio_stream is not None:
            self._decoders_total += 1
        self._clock_anchor = time.perf_counter()

        jobs: List[threading.Thread] = [
            threading.Thread(target=self._demux_loop, name="amp-demux",
                             args=(gen,), daemon=True)
        ]
        if self._video_stream is not None:
            jobs.append(threading.Thread(
                target=self._video_loop, name="amp-video", args=(gen,), daemon=True))
        if self._audio_stream is not None:
            jobs.append(threading.Thread(
                target=self._audio_loop, name="amp-audio", args=(gen,), daemon=True))
        self._threads = jobs
        for t in jobs:
            t.start()

    def _teardown_threads(self) -> None:
        self._stop_flag.set()
        for q in (self._video_q, self._audio_q):
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                break
        for t in self._threads:
            try:
                if t.is_alive():
                    t.join(timeout=1.0)
            except Exception:
                pass
        self._threads = []

    def _decoder_done(self, gen: int) -> None:
        """خيط فك ترجمة انتهى. نتجاهل الخيوط المنتهية من جيل أقدم."""
        with self._lock:
            if gen != self._generation:
                return
            self._decoders_done += 1
            done = self._decoders_done >= self._decoders_total
            eos = self._eos
        if done and eos:
            self._finish()

    def _finish(self) -> None:
        """نهاية الوسائط: تُستدعى مرة واحدة."""
        with self._lock:
            if self._state in ("stopped", "ended"):
                return
            self._state = "ended"
            self._paused_at = self._info.duration
        self._playing.clear()
        self._set_state("stopped")
        if self._out is not None:
            # نُبقي ما تبقّى في مخزن الصوت ليُسمع الذيل كاملاً، ثم نُطفئ
            # الجهاز حتى لا يطنّ في صمت إلى ما بعد نهاية الملف.
            threading.Thread(target=self._drain_then_stop,
                             name="amp-drain", daemon=True).start()
        if self.on_end is not None:
            try:
                self.on_end()
            except Exception:
                pass

    def _drain_then_stop(self) -> None:
        for _ in range(400):          # مهلة تسامحية: 8 ثوانٍ
            if self._stop_flag.is_set() or self._audio_blocks.empty():
                break
            time.sleep(0.02)
        self._suspend_audio()

    def _wait_if_paused(self) -> None:
        """
        يوقف خيط فك الترميز أثناء الإيقاف المؤقت.

        بدون هذا يستمر الخيط في استيعاب الحزم والتخلص منها، فيسبق الصوت
        بكثير، ثم تُهمل كل الإطارات لأن وقتها أقدم من الزمن بكثير.
        """
        while not self._playing.is_set() and not self._stop_flag.is_set():
            time.sleep(0.05)

    # ---------------------------------------------------------- Demux
    def _demux_loop(self, gen: int) -> None:
        c = self._container
        if c is None:
            return
        streams = [s for s in (self._video_stream, self._audio_stream) if s is not None]
        vidx = self._video_stream.index if self._video_stream is not None else -1
        aidx = self._audio_stream.index if self._audio_stream is not None else -1
        vthread = self._threads[1] if len(self._threads) > 1 else None
        athread = self._threads[2] if len(self._threads) > 2 else None
        try:
            for pkt in c.demux(streams):
                if self._stop_flag.is_set():
                    return
                if pkt.stream is None or pkt.size == 0:
                    continue
                if pkt.stream.index == vidx:
                    target, owner = self._video_q, vthread
                elif pkt.stream.index == aidx:
                    target, owner = self._audio_q, athread
                else:
                    continue
                waited = 0.0
                while True:
                    if self._stop_flag.is_set():
                        return
                    try:
                        target.put(pkt, timeout=0.2)
                        break
                    except queue.Full:
                        # لو مات خيط الاستهلاك فلا ننتظر: نُسقط الحزمة،
                        # وإلا تكدّست الحزم ووقف مسار الطرف الآخر أيضاً.
                        if owner is not None and not owner.is_alive():
                            break
                        waited += 0.2
                        if waited > 5.0:
                            break
        except Exception as exc:
            if not self._stop_flag.is_set():
                self._emit_error(f"demux_error: {exc}")
        finally:
            with self._lock:
                if gen == self._generation:
                    self._eos = True
            for q in (self._video_q, self._audio_q):
                try:
                    q.put(None, timeout=0.2)
                except queue.Full:
                    pass

    # ---------------------------------------------------------- الفيديو
    def _video_loop(self, gen: int) -> None:
        codec = self._video_codec
        try:
            if codec is not None:
                while not self._stop_flag.is_set():
                    try:
                        pkt = self._video_q.get(timeout=0.2)
                    except queue.Empty:
                        if self._eos:
                            break
                        continue
                    if pkt is None:
                        break
                    self._wait_if_paused()
                    try:
                        for frame in codec.decode(pkt):
                            if self._stop_flag.is_set():
                                return
                            self._present_frame(frame)
                    except Exception as exc:
                        self._emit_error(f"video_decode_error: {exc}")
                        return
                if not self._stop_flag.is_set():
                    for frame in codec.decode(None):
                        self._present_frame(frame)
        except Exception:
            pass
        finally:
            self._decoder_done(gen)

    def _present_frame(self, frame) -> None:
        """يزامن الإطار مع الصوت ثم يسلّمه للواجهة."""
        if not self._playing.is_set():
            return                      # متوقف مؤقتاً: نتجاهل ما يسمعه
        t = _safe_seconds(frame.pts, frame.time_base)
        if t is not None:
            ahead = t - self.get_time()
            if ahead > SYNC_DROP:
                return                  # تجاوز الزمن: يُهمل
            if ahead > SYNC_AHEAD:
                time.sleep(min(ahead - SYNC_AHEAD, 0.20))
        mw, mh = self._render_max
        try:
            if mw and mh and (frame.width > mw or frame.height > mh):
                scale = min(mw / frame.width, mh / frame.height)
                frame = frame.reformat(
                    width=max(2, int(frame.width * scale)),
                    height=max(2, int(frame.height * scale)),
                    format="rgb24",
                )
            else:
                frame = frame.reformat(format="rgb24")
        except Exception:
            return
        if self.on_frame is None:
            return
        try:
            self.on_frame(frame.to_ndarray(), frame.width, frame.height)
        except Exception:
            pass

    # ---------------------------------------------------------- الصوت
    def _audio_loop(self, gen: int) -> None:
        codec = self._audio_codec
        try:
            self._open_audio()
            if not self._ensure_resampler():
                return
            while not self._stop_flag.is_set():
                try:
                    pkt = self._audio_q.get(timeout=0.2)
                except queue.Empty:
                    if self._eos:
                        break
                    continue
                if pkt is None:
                    break
                self._wait_if_paused()
                try:
                    for frame in codec.decode(pkt):
                        if self._stop_flag.is_set():
                            return
                        self._write_frames(frame)
                except Exception as exc:
                    self._emit_error(f"audio_decode_error: {exc}")
                    return
            if not self._stop_flag.is_set():
                for frame in codec.decode(None):
                    self._write_frames(frame)
        except Exception:
            pass
        finally:
            self._decoder_done(gen)

    def _ensure_resampler(self) -> bool:
        try:
            want = self._out_rate
            if self._resampler is None or getattr(self._resampler, "rate", 0) != want:
                self._resampler = av.AudioResampler(rate=want, **_RESAMPLE_OPTS)
            return True
        except Exception:
            self._resampler = None
            return False

    # ------------------------------------------------------- جهاز الصوت
    def _open_audio(self) -> None:
        """يفتح تدفّق الإخراج إن أمكن، وإلا نعمل بلا صوت."""
        if self._out is not None or self._sd is None:
            return
        self._out_rate = max(8000, int(BASE_RATE * self._rate))
        self._reset_audio_counters(self._media_cursor)
        try:
            self._open_stream()
        except Exception as exc:
            self._out = None
            self._sd_error = str(exc)
            self._use_device_clock = False

    def _resolve_device(self):
        """
        يحدد جهاز الإخراج المطلوب:
        - إن اختار المستخدم جهازاً فنعيده كما هو.
        - وإلا نفضّل مخرج WASAPI الافتراضي (منفذ ويندوز الحديث). القياس
          أظهر أن MME يتقطّع تحت نطق القارئ بينما WASAPI مستقر تماماً.
        - القيمة None تعني «دع PortAudio يختار» (دفاع أخير).
        """
        if self._device_index >= 0:
            return self._device_index
        if self._sd is None:
            return None
        try:
            for ha in self._sd.query_hostapis():
                if "wasapi" in str(ha.get("name", "")).lower():
                    d = int(ha.get("default_output_device") or -1)
                    if d >= 0:
                        return d
        except Exception:
            pass
        return None

    def _open_stream(self) -> None:
        """يفتح تدفّق الصوت مفضّلاً WASAPI، مع تراجعٍ تلقائي آمن."""
        if self._sd is None:
            return
        kwargs = dict(samplerate=self._out_rate, channels=OUT_CHANNELS,
                      dtype="float32", blocksize=OUT_BLOCK,
                      callback=self._pa_callback)
        dev = self._resolve_device()
        try:
            self._out = self._sd.OutputStream(device=dev, **kwargs)
        except Exception:
            if dev is not None:
                try:
                    self._out = self._sd.OutputStream(device=None, **kwargs)
                except Exception:
                    raise
            else:
                raise
        self._out.start()
        self._use_device_clock = True

    def _pa_callback(self, outdata, frames, time_info, status) -> None:
        """
        يعبّئ مخزن PortAudio. يجري في خيط PortAudio لا خيطنا.

        لا يحجب أبداً: يأخذ ما ساعة من قائمة الكتل ويملأ الباقي صفراً.
        يقيس أيضاً جودة التسليم: إذا تأخّر استدعاء الجهاز أو اجتاحنا مخزننا،
        فهذا ما يسمعه المستخدم «تقطيعاً» فنسجّله في عداد التشخيص.
        """
        now = time.perf_counter()
        if self._last_callback_t:
            if (now - self._last_callback_t) * 1000.0 > 60.0:
                self._late_callbacks += 1
        self._last_callback_t = now
        self._audio_callbacks += 1
        need = frames * OUT_CHANNELS
        parts: List[np.ndarray] = []
        got = 0
        try:
            while got < need:
                try:
                    blk = self._audio_blocks.get_nowait()
                except queue.Empty:
                    break
                parts.append(blk.reshape(-1))
                got += blk.size
            if got < need:
                self._underruns += 1
            self._played_samples += frames
            if not parts:
                self._underruns += 0  # سبق احتسابه أعلاه
                outdata[:] = 0.0
            elif got >= need:
                buf = np.concatenate(parts)
                outdata[:, :] = buf[:need].reshape(frames, OUT_CHANNELS)
            else:
                buf = np.concatenate(parts)
                rows = buf.size // OUT_CHANNELS
                outdata[:] = 0.0
                if rows:
                    outdata[:rows, :] = buf[:rows * OUT_CHANNELS].reshape(
                        rows, OUT_CHANNELS)
            if self._duck:
                outdata[:] = np.clip(outdata * self._duck_gain, -1.0, 1.0)
        except Exception:
            try:
                outdata[:] = 0.0
            except Exception:
                pass

    def _reset_audio_counters(self, media_at_next_sample: float) -> None:
        """يضبط عدّادات الساعة على نقطة زمنية معروفة."""
        self._written_samples = 0
        self._played_samples = 0
        self._media_cursor = float(media_at_next_sample)
        # عدادات التشخيص أيضاً: تصف جودة التشغيل الجاري فقط
        self._audio_callbacks = 0
        self._underruns = 0
        self._late_callbacks = 0
        self._last_callback_t = 0.0

    def _drain_audio_blocks(self) -> None:
        try:
            while True:
                self._audio_blocks.get_nowait()
        except queue.Empty:
            pass

    def _suspend_audio(self) -> None:
        if self._out is not None:
            try:
                self._out.stop()
            except Exception:
                pass
        self._use_device_clock = False

    def _resume_audio(self) -> None:
        """يُعيد تشغيل تدفّق الصوت من موضع الإيقاف بالضبط."""
        if self._out is None or self._sd is None:
            self._use_device_clock = False
            return
        self._drain_audio_blocks()
        self._reset_audio_counters(self._paused_at)
        try:
            self._out.start()
            self._use_device_clock = True
        except Exception:
            self._use_device_clock = False

    def _close_audio(self) -> None:
        """
        يغلق تدفّق الصوت.

        آمن من أي خيط الآن: خيط فك الترجمة لا ينتظر الجهاز أبداً، فلا
        يبقى حجزٌ من طرفنا يمنع الإغلاق.
        """
        if self._out is not None:
            try:
                self._out.stop()
            except Exception:
                pass
            try:
                self._out.close()
            except Exception:
                pass
            self._out = None
        self._resampler = None
        self._use_device_clock = False
        self._drain_audio_blocks()

    def _reopen_audio_for_rate(self) -> None:
        """يعيد فتح تدفّق الصوت بالتردد الجديد (بعد تغيير السرعة)."""
        self._close_audio()
        self._out_rate = max(8000, int(BASE_RATE * self._rate))
        self._media_cursor = self.get_time()
        if self._sd is None or not self._playing.is_set():
            self._use_device_clock = False
            return
        try:
            self._open_stream()
            self._reset_audio_counters(self._media_cursor)
        except Exception as exc:
            self._out = None
            self._sd_error = str(exc)
            self._use_device_clock = False

    def _write_frames(self, frame) -> None:
        """يحوّل إطار الصوت إلى عيّنات ويضعها في قائمة كتل ثابتة."""
        if self._rate_change.is_set():
            self._rate_change.clear()
            self._reopen_audio_for_rate()
        if self._resampler is None and not self._ensure_resampler():
            return
        try:
            chunks = self._resampler.resample(frame)
        except Exception:
            return
        for out_frame in chunks:
            if self._stop_flag.is_set():
                return
            arr = out_frame.to_ndarray()
            if arr.ndim == 2:
                arr = arr.T            # من (قنوات، عينات) إلى (عينات، قنوات)
            if self._muted or self._volume != 100:
                gain = 0.0 if self._muted else max(0.0, min(2.0, self._volume / 100.0))
                arr = np.clip(arr * gain, -1.0, 1.0)
            if not self._playing.is_set():
                continue               # مؤقت: نستهلك دون صوت
            if self._out is None:
                # بلا جهاز صوت: نُبطئ الفيديو بمقدار مدة الإطار المشغول
                time.sleep(len(arr) / float(self._out_rate)
                           / max(0.05, self._rate))
                self._media_cursor += (len(arr) / float(self._out_rate)) * self._rate
                continue
            self._push_blocks(arr)

    def _push_blocks(self, arr: np.ndarray) -> None:
        """يقسّم العيّنات إلى كتل يطلبها PortAudio بالضبط."""
        n = len(arr)
        pos = 0
        while pos < n:
            take = min(OUT_BLOCK, n - pos)
            blk = arr[pos:pos + take]
            if take < OUT_BLOCK:
                pad = np.zeros((OUT_BLOCK - take, OUT_CHANNELS), dtype=np.float32)
                blk = np.vstack((blk, pad))
            else:
                blk = np.ascontiguousarray(blk, dtype=np.float32)
            if not self._queue_audio_block(blk):
                return
            self._written_samples += OUT_BLOCK
            self._media_cursor += (OUT_BLOCK / float(self._out_rate)) * self._rate
            pos += take

    def _queue_audio_block(self, blk: np.ndarray) -> bool:
        """يضع كتلة في الطابور، ويقبل الإيقاف أثناء الانتظار."""
        while True:
            if self._stop_flag.is_set():
                return False
            try:
                self._audio_blocks.put(blk, timeout=0.1)
                return True
            except queue.Full:
                continue

    # ---------------------------------------------------------- الحالة
    def _set_state(self, state: str) -> None:
        with self._lock:
            if self._state == state:
                return
            self._state = state
        if self.on_state is not None:
            try:
                self.on_state(state)
            except Exception:
                pass

    def _emit_error(self, msg: str) -> None:
        if self.on_error is not None:
            try:
                self.on_error(msg)
            except Exception:
                pass

    # ==================================================================
    # الساعة
    # ==================================================================
    def _device_time(self) -> Optional[float]:
        """
        زمن الوسائط حسب ما استهلكه جهاز الصوت فعلاً.

        الفرق بين ما سلّمناه للجهاز وما استهلكه هو ما يقبع في مخازنه، فنطرح
        قيمته من نهاية ما كتبناه. هذا يصحّح أي انجراف بين ساعة الحاسب وساعة
        الجهاز الصوتي، وهو ما يجعل الترجمة تظل متزامنة في الأفلام الطويلة.
        """
        if self._out is None or not self._use_device_clock:
            return None
        if self._written_samples <= 0:
            return max(0.0, self._media_cursor)
        buffered = self._written_samples - self._played_samples
        if buffered < 0:
            buffered = 0
        pending = (buffered / float(self._out_rate)) * self._rate
        return max(0.0, self._media_cursor - pending)

    def get_time(self) -> float:
        """الزمن الحالي بالثواني. لا يتجاوز مدة الملف أبداً."""
        if self._container is None:
            return 0.0
        if not self._playing.is_set():
            return self._paused_at
        t = self._device_time()
        if t is None:
            elapsed = time.perf_counter() - self._clock_anchor
            t = self._clock_media + elapsed * self._rate
        dur = self._info.duration
        if dur > 0:
            return max(0.0, min(t, dur))
        return max(0.0, t)

    def get_duration(self) -> float:
        return self._info.duration

    def get_position(self) -> float:
        dur = self._info.duration
        return 0.0 if dur <= 0 else max(0.0, min(1.0, self.get_time() / dur))

    def set_time(self, seconds: float) -> None:
        """يقفز إلى زمن معيّن، ويعيد بناء مخازن فك الترميز."""
        if self._container is None:
            return
        dur = self._info.duration
        target = max(0.0, float(seconds))
        if dur > 0:
            target = min(target, max(0.0, dur - 0.05))
        was_playing = self._playing.is_set()

        with self._seek_lock:
            self._teardown_threads()
            if not self._seek_container(target):
                if was_playing:
                    self._playing.set()
                    self._start_threads()
                return
            for codec in (self._video_codec, self._audio_codec):
                if codec is not None:
                    try:
                        codec.flush_buffers()
                    except Exception:
                        pass
            self._close_audio()
            self._paused_at = target
            self._clock_media = target
            self._clock_anchor = time.perf_counter()
            self._reset_audio_counters(target)
            if was_playing:
                self._playing.set()
                self._start_threads()
            else:
                self._playing.clear()
                self._set_state("paused" if self._state != "stopped" else "stopped")

    def _seek_container(self, target: float) -> bool:
        """
        يقفز في الحاوية إلى الزمن المطلوب.

        مهم: PyAV يفسر المُزاح بـ units « time_base du المسار عند تمرير مسار،
        وبـ AV_TIME_BASE (أجزاء من المليون من الثانية) عند عدم تمريره. الخلط
        بينهما يرسلنا إلى نهاية الملف مباشرة، فنحسب ونحوّل بأنفسنا ونُبقي
        المحاولة الثانية كشبكة أمان.
        """
        c = self._container
        if c is None:
            return False
        anchor = self._video_stream or self._audio_stream
        tb = getattr(anchor, "time_base", None) if anchor is not None else None
        if tb is not None:
            try:
                offset = int(round(float(target) / float(tb)))
                c.seek(offset, backward=True, any_frame=False, stream=anchor)
                return True
            except Exception:
                pass
        try:
            c.seek(int(round(float(target) * 1_000_000)),
                   backward=True, any_frame=False, stream=None)
            return True
        except Exception as exc:
            self._emit_error(f"seek_failed: {exc}")
            return False

    def seek_relative(self, delta_seconds: float) -> None:
        self.set_time(self.get_time() + float(delta_seconds))

    def set_position(self, ratio: float) -> None:
        dur = self._info.duration
        if dur > 0:
            self.set_time(max(0.0, min(1.0, float(ratio))) * dur)

    # ==================================================================
    # الصوت والسرعة
    # ==================================================================
    def set_volume(self, volume: int) -> int:
        self._volume = max(0, min(200, int(volume)))
        return self._volume

    def get_volume(self) -> int:
        return self._volume

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)

    def is_muted(self) -> bool:
        return self._muted

    def set_rate(self, rate: float) -> float:
        """
        يغيّر سرعة التشغيل.

        نُعيد التشكيل إلى تردد أعلى ونشغّل الجهاز على ذلك التردد، فتتسارع
        الإيقاع ويبقى مستوى النغمة ثابتاً.

        مهم: لا نغلق تدفّق الصوت من هنا. خيط الصوت يكون محجوباً داخل
        الكتابة، وإغلاق التدفّق تحته يقتل الخيط ويتوقف الصوت mids-playback
        ويتكدّس الحزم فيوقف الفيديو أيضاً. نترك الخيط نفسه هو من يُعيد
        الفتح عند الإشارة.
        """
        new = max(MIN_RATE, min(MAX_RATE, float(rate)))
        if abs(new - self._rate) < 1e-6:
            return self._rate
        self._rate = new
        self._rate_change.set()
        return self._rate

    def get_rate(self) -> float:
        return self._rate

    # ==================================================================
    # الترجمة
    # ==================================================================
    def set_sub_delay(self, seconds: float) -> None:
        """
        إزاحة توقيت الترجمة بالثواني. الموجب = تأخير.

        نفس إشارة SubtitleEngine.set_offset_seconds بلا استثناء: الموجب
        يعني أن السطر يظهر متأخراً. حين اختلفت الإشارتان غيّرت كل واحدة
        منها مظهر الترجمة في اتجاهين، فاختفت الإزاحة كلياً.

        ملاحظة: الواجهة تملك الإزاحة فعلياً في SubtitleEngine، وهذه
        نسخة للمحرّك وحده.
        """
        self._sub_delay_ms = int(round(float(seconds) * 1000))

    def get_sub_delay(self) -> float:
        return self._sub_delay_ms / 1000.0

    # ==================================================================
    # المسارات
    # ==================================================================
    def get_tracks(self, kind: str) -> List[TrackInfo]:
        return [t for t in self._info.tracks if t.kind == kind]

    def select_audio_stream(self, stream_index: int) -> bool:
        """
        ينتقل إلى مسار صوتي آخر.

        يفكّ الترميز مساراً واحداً في كل مرة، فالتبديل يستلزم فتح الحاوية
        من جديد على المسار المطلوب. نحفظ موضع التشغيل ونستأنف بعد الفتح.
        """
        target = next(
            (t for t in self._info.tracks
             if t.index == stream_index and t.kind == "audio"), None)
        if target is None:
            return False
        if self._audio_stream is not None and self._audio_stream.index == stream_index:
            return True
        path = self._info.path
        if not path:
            return False
        pos = self.get_time()
        was_playing = self._playing.is_set()
        self._prefer_audio_index = stream_index
        ok, _ = self.open(path)
        if not ok:
            self._prefer_audio_index = -1
            return False
        if pos > 0:
            self.set_time(pos)
        if was_playing:
            self.play()
        return True
