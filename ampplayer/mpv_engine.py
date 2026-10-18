"""
محرك تشغيل مبني على libmpv (python-mpv) — بديل اختياري لمحرك PyAV.

لماذا mpv؟
- مسؤولية الصوت والفيديو والتزامنهما كلها داخل mpv نفسه (مخرج WASAPI)،
  فلا وجود لعيوب تزامن المحرك القديم، ولا تقطيع ناتج عن تعارض خيوط الصوت.
- mpv يتقن الشبكات والفهارس والتشكيلات كلها، والبحث يدوياً أفضل.

كيف نرسم الفيديو؟
- نستعمل محلل البرمجيات (SW renderer) في libmpv: يملأ mpv مخزن RGB لدينا
  ونرفعه بالكامل (لا نسخ طويل) إلى الواجهة عبر on_frame تماماً كالمحرك
  القديم، فنحتفظ بمسار العرض الحالي والترجمة المرسومة فوق الصورة من غير
  تغيير. الإطار يُنسخ نسخاً محكماً إلى QImage في الواجهة فلا تبقى الشاشة
  سوداء (لا نعتمد على winId/wid ولا نمرّر مقبض النافذة إلى mpv).

الترجمة الخارجية تُقرأ عبر «sub-text» أثناء التشغيل، ويحمّل محرّك الواجهة
ملف الترجمة الخارجي لعرض الأسطر والتنقل بينها.

الكرسي (fallback): إن تعذّر تحميل libmpv أو فشل بدء mpv، يبقى محرك
PyAV القديم كاملاً في الخدمة (تراه في player.py).
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from typing import Callable, List, Optional, Tuple

import numpy as np

from . import av_engine, config
from .subtitle_parser import Cue

# ---------------------------------------------------------------------------
# تحميل libmpv-2.dll قبل استيراد python-mpv
# ---------------------------------------------------------------------------

_DLL_NAME = "libmpv-2.dll"
_SW_FORMAT = "rgb0"          # 4 بايت لكل بكسل: R,G,B,0
_PIXEL = 4
_RENDER_SLOTS = 10
_RENDER_MAX_DEF = (1280, 720)

def _mpv_lib_dir() -> Optional[str]:
    """المجلد الذي يحتوي libmpv-2.dll (الحزمة المجمّدة أو vendor في المصدر)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
        return base if os.path.exists(os.path.join(base, _DLL_NAME)) else None
    pkg = os.path.dirname(os.path.abspath(__file__))
    cands = [
        os.path.join(pkg, "..", "vendor", "mpv"),
        os.path.join(pkg, "vendor"),
        os.path.join(pkg, "..", "vendor"),
    ]
    for c in cands:
        if os.path.exists(os.path.join(c, _DLL_NAME)):
            return os.path.abspath(c)
    return None


_MPV_LIB_DIR = _mpv_lib_dir()
if _MPV_LIB_DIR:
    os.environ["PATH"] = _MPV_LIB_DIR + os.pathsep + os.environ.get("PATH", "")

try:
    import mpv as _mpv_mod  # type: ignore

    _HAS_MPV = True
except Exception:
    _mpv_mod = None  # type: ignore
    _HAS_MPV = False

if _HAS_MPV:
    # python-mpv لا يعرف معاملات محلل البرمجيات (SW) بعد؛ نضيفها بنفس
    # الأرقام المعرّفة في libmpv/render.h (17..20).
    class _SwSize(ctypes.Structure):
        _fields_ = [("w", ctypes.c_int), ("h", ctypes.c_int)]

    class _SwStride(ctypes.Structure):
        _fields_ = [("v", ctypes.c_size_t)]

    _mpv_mod.MpvRenderParam.TYPES.setdefault("sw_size", (17, _SwSize))
    _mpv_mod.MpvRenderParam.TYPES.setdefault("sw_format", (18, str))
    _mpv_mod.MpvRenderParam.TYPES.setdefault("sw_stride", (19, _SwStride))
    _mpv_mod.MpvRenderParam.TYPES.setdefault("sw_pointer", (20, ctypes.c_void_p))


def mpv_version() -> str:
    if not _HAS_MPV:
        return ""
    for attr in ("github_rev", "__version__", "mpv_version"):
        v = getattr(_mpv_mod, attr, None)
        if v:
            return str(v)
    return ""


def mpv_ready() -> Tuple[bool, str]:
    """هل يمكن تشغيل محرك mpv فعلاً في هذا البناء (مكتبة + DLL)؟"""
    if not _HAS_MPV:
        return False, "python-mpv not installed"
    if not _MPV_LIB_DIR:
        return False, "libmpv-2.dll not found"
    return True, f"libmpv {mpv_version()} ({_MPV_LIB_DIR})"


class _Slot:
    """مخزن RGB واحد (محاذى للذاكرة السريعة) مع منظر للواجهة."""

    __slots__ = ("raw", "buf", "addr", "stride", "rgb", "w", "h")

    def __init__(self, total: int, w: int, h: int) -> None:
        raw = np.zeros(total, dtype=np.uint8)
        addr = raw.ctypes.data
        off = (64 - (addr % 64)) % 64
        # صفوف متصلة تماماً: stride = العرض×4. كانت محاذاة الصفوف إلى 64 تحدث
        # stride أكبر من العرض×4 حين لا يكون العرض مضاعفاً لـ16، فيفشل
        # reshape(h, w, 4) في حلقة الرسم ويتجمّد العرض على آخر صورة (سوداء
        # قبل أول إطار). متصل ⇒ reshape صحيح دائماً، وتبقى محاذاة المؤشر.
        stride = w * _PIXEL
        buf = raw[off:off + h * stride]
        self.raw = raw
        self.buf = buf
        self.addr = addr + off
        self.stride = stride
        self.rgb = buf.reshape(h, w, _PIXEL)[:, :, :3]
        self.w = w
        self.h = h


class MpvEngine:
    """
    محرك mpv بنفس واجهة av_engine.MediaEngine التي يفهمها PlayerController.

    الاستدعاءات تأتي من خيط الواجهة (تشغيل/إيقاف/تلميح...)؛ الرسم وحده
    يجري في خيط خاص لأن محلل البرمجيات يقتضي الاستدعاء من خيط واحد.
    """

    def __init__(self, cfg: "config.Config") -> None:
        self.cfg = cfg
        # الاستدعاءات التي يضعها PlayerController
        self.on_frame: Optional[Callable[[np.ndarray, int, int], None]] = None
        self.on_state: Optional[Callable[[str], None]] = None
        self.on_end: Optional[Callable[[], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_loaded: Optional[Callable[[object], None]] = None

        self._mpv = None
        self._ctx = None
        self._render_ok = False
        self._render_error = ""

        self._probe: Optional[av_engine.MediaEngine] = None
        self._info = av_engine.MediaInfo()
        self._tracks: List[av_engine.TrackInfo] = []
        self._cues: List[Cue] = []

        self._has_file = False
        self._paused = True
        self._play_requested = False
        self._duck = False
        self._base_volume = 100
        self._volume_max = 250
        self._render_max = _RENDER_MAX_DEF
        self._out_size = (0, 0)
        self._mpv_devices: List[str] = []

        self._slots: List[_Slot] = []
        self._seq = 0
        self._closed = True

        self._render_thread: Optional[threading.Thread] = None
        self._stop_render = threading.Event()
        self._stream_ok = True
        self._stream_error = ""
        # الترجمة المطلوبة في mpv: ("none"|"embedded"|"external", payload).
        # تُطبَّق عند file-loaded أيضاً حتى لا يضيع اختيار سبق تحميل الملف.
        self._sub_want: Tuple[str, object] = ("none", None)
        # ترجمة: هل اختار المستخدم مساراً صراحةً؟ (لا نتدخل في اختياره)

    # ------------------------------------------------------------------
    # المتاح
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return _HAS_MPV and _MPV_LIB_DIR is not None

    @property
    def engine_version(self) -> str:
        return f"libmpv {mpv_version()}".strip() or "libmpv"

    @property
    def audio_output_available(self) -> bool:
        return self.available and self._stream_ok

    @property
    def audio_output_error(self) -> str:
        return self._stream_error

    # ------------------------------------------------------------------
    # التهيئة
    # ------------------------------------------------------------------
    def initialize(self) -> Tuple[bool, str]:
        if not self.available:
            return False, "libmpv_not_found"
        if self._mpv is not None:
            return True, ""
        try:
            self._mpv = _mpv_mod.MPV(  # type: ignore[attr-defined]
                vo="libmpv",
                ao="wasapi",
                hwdec="no",
                pause=True,
                idle=True,
                keep_open=False,
                osc=False,
                load_scripts=False,
                input_default_bindings=False,
                sub_auto="no",
                audio_file_auto="no",
                sub_visibility=False,
                osd_level=0,
                volume_max=self._volume_max,
                terminal=False,
                loglevel="error",
            )
        except Exception as exc:
            self._mpv = None
            return False, f"mpv_init_failed: {exc}"

        self._mpv.register_event_callback(self._on_event)
        self._create_render_ctx()
        self._closed = False
        self._stop_render.clear()
        self._render_thread = threading.Thread(
            target=self._render_loop, name="ampplayer-mpv-render", daemon=True
        )
        self._render_thread.start()
        return True, ""

    def _create_render_ctx(self) -> None:
        if self._mpv is None or not _HAS_MPV:
            return
        try:
            ctx = _mpv_mod.MpvRenderContext(self._mpv, "sw")  # type: ignore[attr-defined]
            if getattr(ctx, "_handle", None) and bool(ctx._handle):  # noqa: SLF001
                self._ctx = ctx
                self._render_ok = True
                self._render_error = ""
            else:
                self._render_error = "sw_render_context_failed"
        except Exception as exc:
            self._ctx = None
            self._render_ok = False
            self._render_error = f"sw_render_context_failed: {exc}"

    # ------------------------------------------------------------------
    # الفتح
    # ------------------------------------------------------------------
    def open(self, path: str) -> Tuple[bool, str]:
        if self._mpv is None:
            return False, "mpv_not_initialized"
        self.stop(emit_end=False)

        # مسبار PyAV لمعلومات الملف ومسارات الصوت.
        self._probe = av_engine.MediaEngine(self.cfg)
        probe_ok = False
        try:
            probe_ok, _ = self._probe.open(path)
        except Exception:
            probe_ok = False
        if probe_ok:
            self._info = self._probe.info
            self._tracks = list(self._probe.info.tracks)
            self._cues = list(self._probe.cues)
            self._vsize = self._video_native_size()
        else:
            self._info = av_engine.MediaInfo(path=path)
            self._info.has_video = True
            self._tracks = []
            self._cues = []
            self._vsize = (0, 0)

        # تحميل الملف في mpv
        self._has_file = False
        self._paused = True
        self._play_requested = False
        self._sub_want = ("none", None)
        if self._mpv is not None:
            try:
                self._mpv.sid = "no"
            except Exception:
                pass
        try:
            self._mpv.command("loadfile", str(path), "replace")
        except Exception as exc:
            return False, f"mpv_load_failed: {exc}"
        return True, ""

    def _video_native_size(self) -> Tuple[int, int]:
        for t in self._tracks:
            if t.kind == "video" and t.width and t.height:
                return t.width, t.height
        return (0, 0)

    def _refresh_out_size(self) -> Tuple[int, int]:
        vw, vh = getattr(self, "_vsize", (0, 0))
        mw, mh = self._render_max
        if mw <= 0 or mh <= 0:
            mw, mh = _RENDER_MAX_DEF
        if vw <= 0 or vh <= 0:
            return (0, 0)
        scale = min(1.0, mw / vw, mh / vh)
        w = max(160, int(vw * scale) or 1)
        h = max(90, int(vh * scale) or 1)
        return (w, h)

    # ------------------------------------------------------------------
    # التشغيل
    # ------------------------------------------------------------------
    def play(self) -> None:
        if self._mpv is None:
            return
        self._play_requested = True
        if not self._has_file:
            # الملف ما زال يُحمَّل: يُستأنف عند وصول حدث file-loaded
            return
        try:
            self._mpv.pause = False
        except Exception:
            pass
        self._paused = False
        self._set_state("playing")

    def pause(self) -> None:
        if self._mpv is None:
            return
        self._play_requested = False
        try:
            self._mpv.pause = True
        except Exception:
            pass
        self._paused = True
        self._set_state("paused")

    def toggle_pause(self) -> None:
        if self._paused:
            self.play()
        else:
            self.pause()

    def is_playing(self) -> bool:
        return self._has_file and not self._paused

    def is_paused(self) -> bool:
        return bool(self._paused)

    def stop(self, emit_end: bool = False) -> None:
        """يوقف التشغيل. لا يبعث on_end حتى لا يتحول إيقاف المستخدم إلى
        انتقال تلقائي للملف التالي (كما في محرك PyAV)."""
        self._play_requested = False
        self._paused = True
        self._has_file = False
        self._slots = []
        self._seq = 0
        if self._mpv is not None:
            try:
                self._mpv.pause = True
                self._mpv.command("stop")
            except Exception:
                pass
        self._set_state("stopped")
        if emit_end and self.on_end is not None:
            try:
                self.on_end()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # الزمن
    # ------------------------------------------------------------------
    def get_time(self) -> float:
        if not self._has_file or self._mpv is None:
            return 0.0
        try:
            v = self._mpv.time_pos
            return float(v) if v is not None else 0.0
        except Exception:
            return 0.0

    def get_duration(self) -> float:
        if self._mpv is not None and self._has_file:
            try:
                v = self._mpv.duration
                if v:
                    return float(v)
            except Exception:
                pass
        return float(self._info.duration or 0.0)

    def set_time(self, seconds: float) -> None:
        if not self._has_file or self._mpv is None:
            return
        try:
            self._mpv.seek(max(0.0, float(seconds)), reference="absolute",
                           precision="exact")
        except Exception:
            pass

    def get_position(self) -> float:
        dur = self.get_duration()
        if dur <= 0:
            return 0.0
        t = self.get_time()
        return max(0.0, min(1.0, t / dur))

    def set_position(self, ratio: float) -> None:
        dur = self.get_duration()
        if dur > 0:
            self.set_time(max(0.0, min(1.0, float(ratio))) * dur)

    # ------------------------------------------------------------------
    # الصوت
    # ------------------------------------------------------------------
    def set_volume(self, volume: int) -> None:
        self._base_volume = max(0, min(self._volume_max, int(volume)))
        self._apply_volume()

    def set_muted(self, muted: bool) -> None:
        if self._mpv is not None:
            try:
                self._mpv.mute = bool(muted)
            except Exception:
                pass

    def set_rate(self, rate: float) -> None:
        if self._mpv is not None:
            try:
                self._mpv.speed = max(0.25, min(4.0, float(rate)))
            except Exception:
                pass

    def _apply_volume(self) -> None:
        if self._mpv is None:
            return
        target = self._base_volume
        if self._duck:
            target = max(5, int(self._base_volume * 0.45))
        if self._mpv is not None:
            try:
                self._mpv.volume = min(self._volume_max, target)
            except Exception:
                pass

    def set_duck(self, on: bool) -> None:
        self._duck = bool(on)
        self._apply_volume()

    def set_output_device(self, index: int) -> None:
        if self._mpv is None:
            return
        try:
            idx = int(index)
            if idx >= 0 and idx < len(self._mpv_devices):
                self._mpv.audio_device = self._mpv_devices[idx]
            else:
                self._mpv.audio_device = "auto"
        except Exception:
            pass

    def list_output_devices(self) -> List[Tuple[int, str]]:
        if self._mpv is None:
            return []
        result: List[Tuple[int, str]] = []
        try:
            devices = self._mpv.audio_device_list or []
            self._mpv_devices = []
            for i, d in enumerate(devices):
                name = d.get("name") or ""
                desc = d.get("description") or name
                if not name:
                    continue
                self._mpv_devices.append(name)
                result.append((i, desc + (" (default)" if d.get("current") else "")))
        except Exception:
            pass
        if not result:
            result = [(0, "")]  # لتفادي تعثر الواجهة
        return result

    def audio_diagnostics(self) -> dict:
        rate = 0
        name = ""
        try:
            if self._mpv is not None:
                p = self._mpv.audio_params or {}
                rate = int(p.get("samplerate") or 0)
                dev = self._mpv.audio_device or ""
                try:
                    for i, nm in enumerate(self._mpv_devices):
                        if nm == dev:
                            break
                except Exception:
                    pass
        except Exception:
            pass
        idx = -1
        try:
            cur = self._mpv.audio_device
            for i, nm in enumerate(self._mpv_devices):
                if nm == cur:
                    idx = i
                    break
        except Exception:
            pass
        return {
            "device": idx,
            "out_rate": rate,
            "callbacks": 0,
            "underruns": 0,
            "late_callbacks": 0,
            "queue": 100,
            "queue_max": 100,
            "sd_error": self._render_error,
            "engine": "mpv",
            "mpv_audio_device": name,
        }

    # ------------------------------------------------------------------
    # المسارات والترجمة
    # ------------------------------------------------------------------
    def get_tracks(self, kind: str) -> List[av_engine.TrackInfo]:
        return [t for t in self._tracks if t.kind == kind]

    def select_audio_stream(self, stream_index: int) -> bool:
        target = next(
            (t for t in self._tracks
             if t.index == stream_index and t.kind == "audio"), None)
        if target is None:
            return False
        # إعادة فتح المسبار على المسار المطلوب (يحافظ على موضع في mpv)
        pos = self.get_time()
        if self._probe is not None:
            try:
                if not self._probe.select_audio_stream(stream_index):
                    return False
                self._cues = list(self._probe.cues)
            except Exception:
                return False
        if self._mpv is not None:
            ids = self._mpv_audio_ids()
            ordinals = [t.index for t in self._tracks if t.kind == "audio"]
            try:
                ord_ = ordinals.index(stream_index)
                if ord_ < len(ids):
                    self._mpv.aid = ids[ord_]
            except Exception:
                pass
        if pos > 0:
            self.set_time(pos)
        return True

    def attach_subtitle(self, path: str) -> bool:
        """
        يُرفق ملف ترجمة خارجياً بـ mpv ويحدّده نشطاً (النص الحي لحظياً).

        إن لم يكتمل تحميل الملف بعد يُرجأ التطبيق إلى حدث file-loaded،
        فلا يضيع الاختيار (كان يُلغى سابقاً بتصفير sid عند التحميل).
        """
        if self._mpv is None or not path:
            return False
        self._sub_want = ("external", os.path.abspath(str(path)))
        if self._has_file:
            return self._apply_sub_want()
        return True

    def select_subtitle_stream(self, stream_index: Optional[int]) -> bool:
        """
        يختار مسار ترجمة مدمجاً (فهرس تيار FFmpeg) ليقرأ mpv نصّه الحي،
        أو ``None`` لإلغاء أي ترجمة. يعيد False قبل التهيئة أو لفهرس غير ترجمي.
        """
        if self._mpv is None:
            return False
        if stream_index is None:
            self._sub_want = ("none", None)
        else:
            target = next(
                (t for t in self._tracks
                 if t.index == int(stream_index) and t.kind == "subtitle"), None)
            if target is None:
                return False
            self._sub_want = ("embedded", int(stream_index))
        if self._has_file:
            return self._apply_sub_want()
        return True

    def list_subtitle_tracks(self) -> List[av_engine.TrackInfo]:
        return [t for t in self._tracks if t.kind == "subtitle"]

    def _sub_track_list(self) -> List[dict]:
        try:
            tracks = self._mpv.track_list or []
        except Exception:
            return []
        return [t for t in tracks if t.get("type") == "sub"]

    def _mpv_sub_id_for_ff_index(self, ff_index: int) -> Optional[int]:
        """معرّف mpv لمسار الترجمة المدمج الذي فهرسه في FFmpeg هو ``ff_index``."""
        subs = [t for t in self._sub_track_list() if not t.get("external")]
        for t in subs:
            try:
                if int(t.get("ff-index", -1)) == int(ff_index):
                    return int(t["id"])
            except Exception:
                continue
        # تراجع: مطابقة ترتيبية بين مسارات PyAV ومسارات mpv
        ours = [t for t in self._tracks if t.kind == "subtitle"]
        for pos, tr in enumerate(ours):
            if tr.index == ff_index and pos < len(subs):
                try:
                    return int(subs[pos]["id"])
                except Exception:
                    return None
        return None

    def _apply_sub_want(self) -> bool:
        """يطبّق ``_sub_want`` على mpv (آمن من أي خيط؛ لا يرفع استثناء)."""
        if self._mpv is None:
            return False
        mode, payload = self._sub_want
        try:
            if mode == "embedded":
                sid = self._mpv_sub_id_for_ff_index(int(payload))
                if sid is None:
                    self._mpv.sid = "no"
                    return False
                self._mpv.sid = sid
                return True
            if mode == "external":
                want = os.path.normcase(os.path.abspath(str(payload)))
                for t in self._sub_track_list():
                    if not t.get("external"):
                        continue
                    fn = str(t.get("external-filename") or "")
                    if fn and os.path.normcase(os.path.abspath(fn)) == want:
                        self._mpv.sid = int(t["id"])
                        return True
                self._mpv.command("sub-add", str(payload), "select")
                return True
            self._mpv.sid = "no"
            return True
        except Exception:
            return False

    def current_subtitle_text(self) -> str:
        """السطر النشط حالياً كما يتتبّعه mpv (sub-text)، أو نص فارغ."""
        if self._mpv is None or not self._has_file:
            return ""
        try:
            value = self._mpv.sub_text
            return str(value) if value else ""
        except Exception:
            return ""

    def _mpv_audio_ids(self) -> List[int]:
        try:
            tracks = self._mpv.track_list or []
        except Exception:
            return []
        return [int(t["id"]) for t in tracks if t.get("type") == "audio"]

    @property
    def cues(self) -> List[Cue]:
        return self._cues

    # ------------------------------------------------------------------
    # إعدادات ثانوية
    # ------------------------------------------------------------------
    def set_render_max(self, width: int, height: int) -> None:
        self._render_max = (max(0, int(width)), max(0, int(height)))
        self._out_size = (0, 0)

    def set_decode_threads(self, count: int) -> None:
        return  # mpv يدير خيوط فك الترميز بنفسه

    def set_sub_delay(self, seconds: float) -> None:
        """إزاحة توقيت الترجمة بالثواني داخل mpv (موجب = تأخير السطر)."""
        if self._mpv is None:
            return
        try:
            self._mpv.sub_delay = float(seconds or 0.0)
        except Exception:
            pass

    def close(self) -> None:
        self._closed = True
        self._stop_render.set()
        if self._render_thread is not None:
            try:
                self._render_thread.join(timeout=1.0)
            except Exception:
                pass
            self._render_thread = None
        if self._ctx is not None:
            try:
                self._ctx.free()
            except Exception:
                pass
            self._ctx = None
        if self._mpv is not None:
            try:
                self._mpv.command("stop")
            except Exception:
                pass
            try:
                self._mpv.terminate()
            except Exception:
                pass
            self._mpv = None
        if self._probe is not None:
            try:
                self._probe.close()
            except Exception:
                pass
            self._probe = None

    # ------------------------------------------------------------------
    # أحداث mpv (خيط أحداث المكتبة)
    # ------------------------------------------------------------------
    def _on_event(self, event) -> None:
        try:
            d = event.as_dict()
        except Exception:
            return
        ev = d.get("event")
        if isinstance(ev, bytes):
            ev = ev.decode("utf-8", "ignore")
        elif ev is not None:
            ev = str(ev)
        if ev == "file-loaded":
            self._has_file = True
            self._out_size = (0, 0)
            # نطبّق اختيار الترجمة الآن: ما اختير قبل التحميل كان سيُلغى هنا
            self._apply_sub_want()
            if self._play_requested:
                try:
                    self._mpv.pause = False
                except Exception:
                    pass
                self._paused = False
                self._set_state("playing")
            cb = self.on_loaded
            if cb is not None:
                try:
                    cb(self._info)
                except Exception:
                    pass
        elif ev == "end-file":
            reason = d.get("reason", "unknown")
            if isinstance(reason, bytes):
                reason = reason.decode("utf-8", "ignore")
            elif isinstance(reason, int):
                reason = {
                    0: "eof", 1: "restart", 2: "abort",
                    3: "quit", 4: "error", 5: "redirect",
                }.get(reason, "unknown")
            was_file = self._has_file
            self._has_file = False
            self._paused = True
            if reason == "eof" and was_file:
                self._play_requested = False
                self._set_state("stopped")
                cb = self.on_end
                if cb is not None:
                    try:
                        cb()
                    except Exception:
                        pass
            elif reason == "error":
                cb = self.on_error
                if cb is not None:
                    try:
                        cb("mpv playback error")
                    except Exception:
                        pass
            else:
                self._set_state("stopped")
        elif ev == "video-reconfig":
            self._out_size = (0, 0)

    def _set_state(self, state: str) -> None:
        cb = self.on_state
        if cb is not None:
            try:
                cb(state)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # الرسم: خيط مستقل للمحلل البرمجي
    # ------------------------------------------------------------------
    def _render_loop(self) -> None:
        while not self._stop_render.is_set():
            self._render_tick()
            self._stop_render.wait(0.012)

    def _render_tick(self) -> None:
        if self._ctx is None or self._closed:
            return
        try:
            fresh = self._ctx.update()
        except Exception:
            return
        if not fresh:
            return
        w, h = self._out_size
        if w <= 0 or h <= 0:
            w, h = self._refresh_out_size()
            if w <= 0 or h <= 0:
                return
            self._out_size = (w, h)
        slots = self._ensure_slots(w, h)
        if not slots:
            return
        slot = slots[self._seq % len(slots)]
        self._seq += 1
        try:
            self._ctx.render(
                sw_size={"w": w, "h": h},
                sw_format=_SW_FORMAT,
                sw_stride={"v": slot.stride},
                sw_pointer=ctypes.c_void_p(slot.addr),
            )
            self._ctx.report_swap()
        except Exception:
            return
        cb = self.on_frame
        if cb is not None:
            try:
                cb(slot.rgb, w, h)
            except Exception:
                pass

    def _buf_size(self) -> Tuple[int, int]:
        if self._slots:
            s = self._slots[0]
            return (s.w, s.h)
        return (0, 0)

    def _ensure_slots(self, w: int, h: int) -> List[_Slot]:
        total = h * w * _PIXEL + 64
        if self._slots and self._slots[0].w == w and self._slots[0].h == h:
            return self._slots
        self._slots = [_Slot(total, w, h) for _ in range(_RENDER_SLOTS)]
        self._seq = 0
        return self._slots