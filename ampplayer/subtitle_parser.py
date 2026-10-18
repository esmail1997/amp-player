"""محلل ملفات الترجمة: SRT / VTT / ASS / SSA / SUB."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# أنماط الوقت SRT/VTT: 00:00:12,500
_TS_RE = re.compile(
    r"(?P<h>\d{1,3}):(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:[.,](?P<ms>\d{1,3}))?"
)
_ARROW = "\u2192"      # →
_DASH = "\u2013"       # –
# أي سهم يفصل البداية عن النهاية في صيغ الترجمة المختلفة
_ARROW_SPLIT = re.compile(r"\s*(?:-->|->|—|–|―|→|\.{3,})\s*")
_HAS_ARROW = re.compile(r"-->|->|→|–|—")
_ASS_TAGS = re.compile(r"\{[^}]*\}")
_ASS_VOICE = re.compile(r"\\N|\\n|\\h", re.IGNORECASE)


@dataclass
class Cue:
    """سطر ترجمة واحد."""
    index: int
    start_ms: int
    end_ms: int
    text: str
    raw: str = ""

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    def start_time(self) -> float:
        return self.start_ms / 1000.0

    def end_time(self) -> float:
        return self.end_ms / 1000.0


def _parse_ts(value: str) -> Optional[int]:
    """يحوّل نصاً زمنياً إلى ميلي ثانية."""
    m = _TS_RE.search(value or "")
    if not m:
        return None
    ms = m.group("ms") or "0"
    ms = (ms + "000")[:3]  # توحيد الأرقام (5 -> 500)
    h, mi, s = int(m.group("h")), int(m.group("m")), int(m.group("s"))
    return ((h * 60 + mi) * 60 + s) * 1000 + int(ms)


def format_timestamp(ms: int) -> str:
    """ينسّق ميلي ثانية إلى شكل SRT."""
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    mi, rem = divmod(rem, 60_000)
    s, msec = divmod(rem, 1000)
    return f"{h:02d}:{mi:02d}:{s:02d},{msec:03d}"


def format_duration(seconds: float) -> str:
    """ينسّق ثواني إلى س:د أو س:د:س."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    mi, s = divmod(rem, 60)
    if h:
        return f"{h}:{mi:02d}:{s:02d}"
    return f"{mi}:{s:02d}"


def clean_ass_text(text: str) -> str:
    r"""ينظّف نصوص ASS/SSA من الوسوم ويحوّل \N إلى سطر جديد."""
    text = _ASS_TAGS.sub("", text)
    text = text.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    text = text.replace(r"{\an8}", "").replace(r"{\an9}", "")
    return text.strip()


def clean_vtt_text(text: str) -> str:
    """ينظّف نصوص WebVTT من الوسوم."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    return text.strip()


def _detect_encoding(data: bytes) -> str:
    """يكتشف ترميز ملف الترجمة heuristically."""
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return "utf-16"
    # BOM-less utf-8
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    # نحاول windows-1256 للعربية ثم latin-1
    for enc in ("cp1256", "windows-1256", "cp1252", "latin-1"):
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def read_text(path: str | Path) -> str:
    """يقرأ ملف ترجمة بترميز صحيح."""
    data = Path(path).read_bytes()
    enc = _detect_encoding(data)
    try:
        return data.decode(enc, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def parse_srt_vtt(content: str, vtt: bool = False) -> List[Cue]:
    """
    يحلل محتوى SRT أو WebVTT.
    يعمل مع الملفات التي تفصل بين الأسطر بسطر فارغ أو لا
    (بعض المصادر تُنتج عدة أسطر متلاصقة داخل فقرة واحدة).
    """
    cues: List[Cue] = []
    content = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if vtt or content.upper().lstrip().startswith("WEBVTT"):
        vtt = True

    lines = content.split("\n")
    idx = 0
    i = 0
    n = len(lines)
    # تخطي ترويسة WEBVTT
    if vtt and n and lines[0].strip().upper().startswith("WEBVTT"):
        i = 1

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # ترويسة/تعليمات VTT تُتجاهل
        if vtt and stripped and not _HAS_ARROW.search(stripped):
            up = stripped.upper()
            if up.startswith(("NOTE", "STYLE", "REGION", "WEBVTT", "KIND", "LANGUAGE")):
                i += 1
                continue

        if not _HAS_ARROW.search(stripped):
            i += 1
            continue

        parts = _ARROW_SPLIT.split(stripped)
        if len(parts) < 2:
            i += 1
            continue
        start = _parse_ts(parts[0])
        end = _parse_ts(parts[1])
        if start is None or end is None:
            i += 1
            continue
        if end < start:
            start, end = end, start

        # نجمع نص السطر حتى سطر فارغ أو سطر زمني جديد
        body: List[str] = []
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if nxt == "":
                # السطر الفارج ينهي السطر ما لم يكن هناك فاصل
                break
            if _HAS_ARROW.search(nxt):
                break
            # سطر عدد صحيح خالص يليه سطر زمني = فهرس السطر الـتالي،
            # لا يلتصق بنص السطر الحالي (ملفات SRT بلا أسطر فارغة فاصلة)
            if nxt.isdigit() and i + 1 < n and _HAS_ARROW.search(lines[i + 1].strip()):
                break
            body.append(lines[i])
            i += 1
        # تخطي الأسطر الفارغة الفاصلة
        while i < n and lines[i].strip() == "":
            i += 1

        text = "\n".join(body).strip()
        text = clean_vtt_text(text) if vtt else text
        if not text:
            continue
        idx += 1
        cues.append(Cue(index=idx, start_ms=start, end_ms=end, text=text,
                        raw="\n".join([stripped] + body)))
    return cues


def _ass_format_fields(content: str) -> List[str]:
    """
    يقرأ أسماء أعمدة سطر Format الخاص بقسم الأحداث.

    عدد الحقول يختلف بين الملفات: SSA القديم ثمانية، و ASS الحديث عشرة،
    وبعض الملفات المبسّطة أربعة. بدون هذا نُسقط كل سطر عند اختلاف واحد،
    فتضيع ترجمة كاملة بصمت.

    انتبه: في الملف الواحد أسطر Format كثيرة، منها واحد في [V4+ Styles]
    لأسماء الأنماط. الذي يهمنا هو الذي يلي [Events].
    """
    fallback: List[str] = []
    in_events = False
    for raw in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        low = line.lower()
        if low.startswith("[") and low.endswith("]"):
            in_events = low.startswith("[events")
            continue
        if not low.startswith("format:"):
            continue
        names = [f.strip().lower() for f in line[len("format:"):].split(",")]
        if in_events and "start" in names and "end" in names:
            return names
        if "start" in names and "end" in names and not fallback:
            fallback = names
    if fallback:
        return fallback
    # الافتراضي المعتمد في ASS v4+
    return ["layer", "start", "end", "style", "name",
            "marginl", "marginr", "marginv", "effect", "text"]


def parse_ass(content: str) -> List[Cue]:
    """يحلل محتوى ASS/SSA."""
    cues: List[Cue] = []
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    names = _ass_format_fields(content)
    i_start = names.index("start") if "start" in names else 1
    i_end = names.index("end") if "end" in names else 2
    i_text = len(names) - 1
    if not (0 <= i_start < i_end <= i_text):
        i_start, i_end, i_text = 1, 2, 9
    idx = 0
    # ASS time: H:MM:SS.cc
    for line in content.split("\n"):
        line = line.strip()
        if not line.lower().startswith("dialogue:"):
            continue
        payload = line[len("dialogue:"):]
        # النص قد يحوي فواصل، فنقسم عند عمود النص ولا بعده
        fields = payload.split(",", i_text)
        if len(fields) <= i_text:
            continue
        start, end, text = fields[i_start], fields[i_end], fields[i_text]
        # بعض الكتّاب يُخرجون عموداً فارغاً زيادة على ما تعلنه Format،
        # فيبدأ النص بفاصلة. نقصّها بدل أن نقرأها حرفاً في النص.
        text = text.lstrip(",")
        
        s_ms = _parse_ass_ts(start)
        e_ms = _parse_ass_ts(end)
        if s_ms is None or e_ms is None:
            continue
        body = clean_ass_text(text)
        if not body:
            continue
        idx += 1
        cues.append(Cue(index=idx, start_ms=s_ms, end_ms=e_ms, text=body, raw=line))
    return cues


def _parse_ass_ts(value: str) -> Optional[int]:
    m = re.match(r"(\d+):(\d{2}):(\d{2})[.,](\d{1,3})", value.strip())
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    ms = (m.group(4) + "00")[:3]
    return ((h * 60 + mi) * 60 + s) * 1000 + int(ms)


def parse_microdvd(content: str, fps: float = 25.0) -> List[Cue]:
    """يحلل صيغة MicroDVD (المبنية على الإطارات) مثل ملفات .sub."""
    cues: List[Cue] = []
    idx = 0
    rate = fps if fps > 0 else 25.0
    for line in content.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        # [start][end]text|text
        m = re.match(r"\[(\d+)\]\s*\[(\d+)\]\s*(.*)", line)
        if not m:
            continue
        try:
            start_f = int(m.group(1))
            end_f = int(m.group(2))
        except ValueError:
            continue
        text = m.group(3).replace("|", "\n").strip()
        if not text:
            continue
        idx += 1
        cues.append(
            Cue(
                index=idx,
                start_ms=int(start_f / rate * 1000),
                end_ms=int(end_f / rate * 1000),
                text=text,
            )
        )
    return cues


SUPPORTED_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa", ".sub", ".txt", ".sami"}


def parse_file(path: str | Path) -> List[Cue]:
    """يحلّل ملف ترجمة من أي صيغة مدعومة."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    ext = p.suffix.lower()
    content = read_text(p)
    if ext == ".ass" or ext == ".ssa":
        cues = parse_ass(content)
        if cues:
            return cues
        return parse_srt_vtt(content)
    if ext == ".vtt":
        return parse_srt_vtt(content, vtt=True)
    if ext == ".sub":
        return parse_microdvd(content)
    return parse_srt_vtt(content)


def parse_file_safe(path: str | Path) -> List[Cue]:
    """مثل parse_file لكن لا يرمي أخطاء."""
    try:
        return parse_file(path)
    except Exception:
        return []


def to_srt(cues: List[Cue]) -> str:
    """يحوّل قائمة أسطر إلى نص SRT."""
    out: List[str] = []
    for i, cue in enumerate(cues, 1):
        out.append(str(i))
        out.append(f"{format_timestamp(cue.start_ms)} {_ARROW} {format_timestamp(cue.end_ms)}")
        out.append(cue.text)
        out.append("")
    return "\n".join(out)


def find_cue(cues: List[Cue], pos_ms: int, tolerance_ms: int = 400) -> Optional[Cue]:
    """
    يجد السطر النشط عند زمن معيّن بالبحث الثنائي.
    نحتفظ بالسطر لـ tolerance_ms بعد نهايته كي لا يختفي فوراً.
    """
    if not cues:
        return None
    lo, hi = 0, len(cues) - 1
    best: Optional[Cue] = None
    while lo <= hi:
        mid = (lo + hi) // 2
        cue = cues[mid]
        if pos_ms < cue.start_ms:
            hi = mid - 1
        elif pos_ms > cue.end_ms + tolerance_ms:
            lo = mid + 1
        else:
            # ضمن النطاق: نبحث عن أحدث سطر بدأ قبل الوقت
            best = cue
            lo = mid + 1
    return best


def cues_in_range(cues: List[Cue], start_ms: int, end_ms: int) -> List[Cue]:
    """يرجّع الأسطر ضمن مدى زمني."""
    return [c for c in cues if c.start_ms < end_ms and c.end_ms > start_ms]


def sidecar_candidates(video_path: str | Path) -> List[Path]:
    """يبحث عن ملفات الترجمة المرافقة بنفس الاسم أو بلغة إضافية."""
    v = Path(video_path)
    stem, parent = v.stem, v.parent
    found: List[Path] = []
    if not parent.exists():
        return found
    try:
        for f in parent.iterdir():
            if not f.is_file():
                continue
            if f.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            fs = f.stem.lower()
            ls = stem.lower()
            if fs == ls or fs.startswith(ls + ".") or fs.startswith(ls + "_"):
                found.append(f)
    except OSError:
        pass
    found.sort(key=lambda p: (0 if p.stem.lower() == stem.lower() else 1, p.name))
    return found