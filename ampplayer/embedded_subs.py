"""
الترجمة المدمجة داخل ملف الفيديو (بلا Qt).

يكتشف مسارات الترجمة النصية الموجودة داخل الحاوية (srt/ass/webvtt/mov_text)
ويستخرج أسطرها إلى قائمة ``Cue`` عبر PyAV، فتُقرأ بـ NVDA تماماً كملف
الترجمة الخارجي وتظهر في لوحة الترجمة مع التنقل سطراً بسطر. يُستعمل في
المحرّكين: مع mpv يُختار المسار نفسه ليُقرأ النص الحي، ومع PyAV تُقرأ
الأسطر المستخرجة هنا.

المسارات الصورية (PGS/VobSub/DVB) تُكتشف لكنها لا تُستخرج: لا نص فيها.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from .subtitle_parser import Cue
from .subtitle_text import clean_subtitle_text

# أسماء الترميزات كما تعطيها PyAV (وبعض أسماء mpv/ffprobe المرادفة)
TEXT_CODECS = {"srt", "subrip", "ass", "ssa", "webvtt", "mov_text", "text", "tx3g"}
IMAGE_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub",
                "dvb_teletext"}

# رموز ISO 639-1/639-2B → 639-2T (ما يُستعمل في الإعدادات: ara, eng ...)
_LANG_ALIASES = {
    "ar": "ara", "arb": "ara",
    "en": "eng",
    "fr": "fra", "fre": "fra",
    "de": "deu", "ger": "deu",
    "es": "spa",
    "tr": "tur",
    "fa": "fas", "per": "fas",
    "ur": "urd",
    "hi": "hin",
    "it": "ita",
    "ru": "rus",
    "pt": "por",
    "zh": "zho", "chi": "zho",
    "ja": "jpn",
    "ko": "kor",
    "nl": "nld", "dut": "nld",
}

# مدة افتراضية لسطر بلا مدة معلومة
_DEFAULT_DURATION_MS = 3000


def normalize_lang(code: str) -> str:
    """يوحّد رمز اللغة: ``ar-SA`` و``ar`` و``arb`` كلها → ``ara``."""
    c = (code or "").strip().lower().replace("_", "-").split("-")[0]
    return _LANG_ALIASES.get(c, c)


def lang_matches(track_lang: str, preferred: str) -> bool:
    a, b = normalize_lang(track_lang), normalize_lang(preferred)
    return bool(a) and bool(b) and a == b


@dataclass
class EmbeddedTrack:
    """مسار ترجمة داخل الحاوية (الفهرس هو فهرس تيار FFmpeg = ``ff-index`` في mpv)."""
    index: int
    codec: str
    language: str = ""
    title: str = ""
    is_default: bool = False
    is_forced: bool = False

    @property
    def is_text(self) -> bool:
        return (self.codec or "").lower() in TEXT_CODECS

    @property
    def is_image(self) -> bool:
        return (self.codec or "").lower() in IMAGE_CODECS

    def label(self, ordinal: int) -> str:
        """وصف مختصر: ``1. ara — title (subrip)``؛ الواجهة تترجم اللغة."""
        bits = [f"{ordinal}."]
        if self.language:
            bits.append(self.language)
        if self.title:
            bits.append(f"— {self.title}")
        if self.codec:
            bits.append(f"({self.codec})")
        return " ".join(bits)


def list_embedded_tracks(path: str) -> List[EmbeddedTrack]:
    """يقرأ ترويسة الملف ويعيد مسارات الترجمة؛ لا يرفع استثناء أبداً."""
    try:
        import av
    except Exception:
        return []
    try:
        container = av.open(str(path))
    except Exception:
        return []
    out: List[EmbeddedTrack] = []
    try:
        for st in container.streams.subtitles:
            meta = {}
            try:
                meta = dict(st.metadata or {})
            except Exception:
                pass
            language = str(meta.get("language") or getattr(st, "language", None) or "")
            codec = ""
            try:
                codec = str(st.codec_context.name or "")
            except Exception:
                codec = str(getattr(st, "name", "") or "")
            try:
                disp = int(getattr(st, "disposition", 0) or 0)
            except Exception:
                disp = 0
            out.append(EmbeddedTrack(
                index=int(st.index),
                codec=codec,
                language=language,
                title=str(meta.get("title") or ""),
                is_default=bool(disp & 1),
                is_forced=bool(disp & 2),
            ))
    except Exception:
        pass
    finally:
        try:
            container.close()
        except Exception:
            pass
    return out


def pick_default_track(tracks: List[EmbeddedTrack],
                       preferred_lang: str = "") -> Optional[EmbeddedTrack]:
    """
    يختار المسار النصي الأنسب: لغة المستخدم المفضلة (غير الإجباري أولاً)،
    ثم المسار الافتراضي في الملف، ثم أول مسار نصي. الصورية تُتجاهل.
    """
    text = [t for t in tracks if t.is_text]
    if not text:
        return None
    if preferred_lang:
        matched = [t for t in text if lang_matches(t.language, preferred_lang)]
        if matched:
            non_forced = [t for t in matched if not t.is_forced]
            return (non_forced or matched)[0]
    default = [t for t in text if t.is_default and not t.is_forced]
    if default:
        return default[0]
    non_forced = [t for t in text if not t.is_forced]
    return (non_forced or text)[0]


def ass_event_to_text(ass_fields: str) -> str:
    """
    يحوّل حقول حدث ASS (كما تعطيها PyAV بلا بادئة ``Dialogue:``) إلى نص نقي.

    الحقول: ReadOrder,Layer,Style,Name,MarginL,MarginR,MarginV,Effect,Text —
    النص هو ما بعد الفاصلة التاسعة، وقد يحوي فواصل بنفسه.
    """
    if not ass_fields:
        return ""
    text = ass_fields.split(",", 8)[-1] if ass_fields.count(",") >= 8 else ass_fields
    return clean_subtitle_text(text)


def _rect_text(rect) -> str:
    """نص مستطيل ترجمة واحد (PyAV): dialogue ← text ← ass."""
    rtype = getattr(rect, "type", b"")
    if isinstance(rtype, bytes):
        rtype = rtype.decode("ascii", "ignore")
    if rtype == "bitmap":
        return ""
    for attr in ("dialogue", "text"):
        raw = getattr(rect, attr, None)
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            cleaned = clean_subtitle_text(str(raw))
            if cleaned:
                return cleaned
    raw = getattr(rect, "ass", None)
    if raw:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        return ass_event_to_text(str(raw))
    return ""


def extract_embedded_cues(path: str, stream_index: int,
                          should_stop: Optional[Callable[[], bool]] = None) -> List[Cue]:
    """
    يستخرج أسطر مسار ترجمة نصي إلى قائمة ``Cue`` مرتبة ومرقّمة من 1.

    يعيد قائمة فارغة (أو جزئية) بدل رفع استثناء. ``should_stop`` تُستدعى
    دورياً لإلغاء الاستخراج من الخيط الخلفي.
    """
    try:
        import av
    except Exception:
        return []
    try:
        container = av.open(str(path))
    except Exception:
        return []
    found: List[tuple] = []
    seen = set()
    try:
        try:
            stream = container.streams[int(stream_index)]
        except Exception:
            return []
        if getattr(stream, "type", "") != "subtitle":
            return []
        try:
            codec = str(stream.codec_context.name or "").lower()
        except Exception:
            codec = ""
        if codec and codec not in TEXT_CODECS:
            return []
        n = 0
        for pkt in container.demux(stream):
            n += 1
            if should_stop is not None and n % 200 == 0 and should_stop():
                break
            if pkt.pts is None and pkt.dts is None:
                continue
            try:
                ss = stream.decode2(pkt)
            except Exception:
                continue
            if ss is None:
                continue
            try:
                rects = list(ss.rects)
            except Exception:
                rects = []
            if not rects:
                continue
            tb = pkt.time_base or stream.time_base
            pts = pkt.pts if pkt.pts is not None else pkt.dts
            try:
                start_ms = int(pts * tb * 1000) if tb else int(getattr(ss, "pts", 0) or 0) // 1000
            except Exception:
                continue
            sdt = int(getattr(ss, "start_display_time", 0) or 0)
            edt = int(getattr(ss, "end_display_time", 0) or 0)
            start_ms += sdt
            if pkt.duration and tb:
                end_ms = int((pts + pkt.duration) * tb * 1000)
            elif edt > sdt:
                end_ms = start_ms + (edt - sdt)
            else:
                end_ms = start_ms + _DEFAULT_DURATION_MS
            if end_ms <= start_ms:
                end_ms = start_ms + _DEFAULT_DURATION_MS
            parts = [t for t in (_rect_text(r) for r in rects) if t]
            if not parts:
                continue
            text = "\n".join(parts)
            key = (start_ms, text)
            if key in seen:
                continue
            seen.add(key)
            raw = ""
            try:
                raw0 = getattr(rects[0], "ass", b"") or b""
                raw = raw0.decode("utf-8", "replace") if isinstance(raw0, bytes) else str(raw0)
            except Exception:
                raw = ""
            found.append((start_ms, end_ms, text, raw))
    except Exception:
        pass
    finally:
        try:
            container.close()
        except Exception:
            pass
    found.sort(key=lambda t: (t[0], t[1]))
    return [Cue(index=i, start_ms=s, end_ms=e, text=txt, raw=raw)
            for i, (s, e, txt, raw) in enumerate(found, start=1)]
