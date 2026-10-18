"""فحص ذاتي: يتحقق أن كل مكوّن يعمل داخل النسخة المُجمَّعة.

يُستدعى بـ::

    Amp Player.exe --selftest

لأن النسخة المُجمَّعة بلا وحدة تحكم، لا يظهر الناتج على الشاشة أبداً؛
لذلك يُكتب في ملف ``selftest.txt`` بجانب البرنامج (أو في مجلد بيانات
التطبيق إن كان مجلد البرنامج غير قابل للكتابة).

رمز الخروج: 0 = كل الفحوصات ناجحة، 1 = هناك فشل.
"""

from __future__ import annotations

import os
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable, List, Tuple

# التشغيل المباشر (`python ampplayer/selftest.py` أو زر التشغيل في المحرّر):
# يضع بايثون مجلد ampplayer في المسار فيفشل `import ampplayer`.
# نضيف جذر المشروع حتى يقتدي بالمشروع كاملاً.
_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, "") and str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ------------------------------------------------------------- أدوات فحص
def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _write_report(lines: List[str]) -> Path:
    where: List[Path] = []
    if _frozen():
        where.append(Path(sys.executable).resolve().parent / "selftest.txt")
    where.append(Path.cwd() / "selftest.txt")
    from ampplayer import config

    where.append(config.app_data_dir() / "selftest.txt")
    for p in where:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return p
        except Exception:
            continue
    return Path("?")


def _check(name: str, fn: Callable[[], str]) -> Tuple[bool, str]:
    t0 = time.time()
    try:
        detail = fn() or "OK"
        return True, f"[ OK ] {name}: {detail} ({time.time() - t0:.2f}s)"
    except Exception as exc:  # noqa: BLE001 - الفحص يجب ألّا يسقط
        msg = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc().strip().splitlines()[-1]
        return False, f"[FAIL] {name}: {msg} | {tb} ({time.time() - t0:.2f}s)"


# ------------------------------------------------------------- الفحوصات
def _check_interpreter() -> str:
    mode = "frozen" if _frozen() else "source"
    return (f"{platform.python_version()} ({mode}) on {platform.system()} "
            f"{platform.release()}")


def _check_pyside() -> str:
    from PySide6 import QtCore, QtGui, QtWidgets

    # الثلاثة مجتمعة = قلب الواجهة كاملة، ولذا نستوردها جميعاً هنا.
    loaded = ", ".join(m.__name__.rsplit(".", 1)[-1] for m in (QtCore, QtGui, QtWidgets))
    return (f"Qt {QtCore.qVersion()}, PySide6 {getattr(QtCore, '__version__', '?')} "
            f"[{loaded}]")


def _check_av() -> str:
    """استيراد av وحده لا يكفي: نفتح مشغّلاً لتأكيد تحميل DLLات FFmpeg."""
    import av
    from av.codec import Codec

    Codec("h264", "r")
    Codec("aac", "r")
    return f"PyAV {av.__version__}"


def _check_numpy() -> str:
    import numpy

    return f"numpy {numpy.__version__} ({numpy.zeros(4).dtype})"


def _check_sounddevice() -> str:
    import sounddevice as sd

    devices = sd.query_devices()
    count = len(devices) if devices else 0
    if not count:
        raise RuntimeError("no audio devices found")
    return f"sounddevice {sd.__version__}, {count} devices"


def _check_gui() -> str:
    """يبني النافذة كاملة، مفضّلاً على المنصّة الحقيقية (تجريب إضافة Qt)."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    try:
        app = QApplication.instance() or QApplication(["amp-selftest"])
        platform_name = app.platformName()
    except Exception:
        # المنصّة الحقيقية غير متاحة (بيئة بلا شاشة أو إضافة ناقصة)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        app = QApplication.instance() or QApplication(["amp-selftest"])
        platform_name = app.platformName() + " (fallback)"

    from ampplayer.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    app.processEvents()
    size = win.size()
    win.close()
    QTimer.singleShot(0, app.quit)
    return f"MainWindow {size.width()}x{size.height()} on platform '{platform_name}'"


def _check_subtitle_parser() -> str:
    from ampplayer.subtitle_parser import parse_srt_vtt

    sample = "1\n00:00:01,000 --> 00:00:03,000\nمرحبا بالعالم\n"
    cues = parse_srt_vtt(sample)
    if len(cues) != 1:
        raise RuntimeError(f"expected 1 cue, got {len(cues)}")
    return f"1 cue parsed, text={cues[0].text[:20]!r}"


def _check_config() -> str:
    from ampplayer import config

    with tempfile.TemporaryDirectory(prefix="amp_selftest_") as td:
        cfg = config.Config(path=str(Path(td) / "t.ini"))
        cfg.set("tts_rate", 250)
        cfg.sync()
        if int(cfg.get("tts_rate")) != 250:
            raise RuntimeError("config round-trip failed")
    return f"{len(config.DEFAULTS)} settings"


def _check_providers() -> str:
    import requests

    from ampplayer.providers import manager, opensubtitles_provider

    url = opensubtitles_provider._legacy_url(query="matrix", lang="ara")
    if not url.startswith("https://rest.opensubtitles.org/search/"):
        raise RuntimeError("legacy url builder broken")
    return f"requests {requests.__version__}, {len(manager.PROVIDERS)} providers"


def _check_tts() -> str:
    """نمرّ عبر مسار البرنامج نفسه: الاستيراد وحده لا يكشف عطباً في الأصوات."""
    from ampplayer.speech import Speaker

    sp = Speaker()
    if not sp.init():
        raise RuntimeError("engine init failed (pyttsx3/SAPI unavailable)")
    voices = sp.voices()
    if not voices:
        raise RuntimeError("voice list empty - SAPI enumeration failed")
    return f"{len(voices)} voices, first={voices[0][1][:32]!r}"


def _check_ffmpeg_optional() -> str:
    """ffmpeg.exe اختياري (للدمج فقط) — نذكره ولا نفشل بسببه."""
    from ampplayer import media_probe

    p = media_probe.ffmpeg_path()
    if p:
        return f"found: {p}"
    return "not found (optional: only needed for subtitle merging)"


def _check_availability_surface() -> str:
    """يؤكد أن محرّك الصوت والفيديو متاح فعلاً كما وعد التطبيق."""
    from ampplayer import av_engine

    if not av_engine.av_available():
        raise RuntimeError("av engine reported unavailable")
    return f"engine={av_engine.av_version()}"


def _check_nvda() -> str:
    """جسر NVDA Controller Client: متاح أم لا، ويعمل الآن أم لا."""
    from ampplayer import nvda_bridge

    if not nvda_bridge.dll_available():
        return "dll bundled; NVDA not detected"
    if nvda_bridge.is_running():
        return f"NVDA running (pid={nvda_bridge.nvda_pid()})"
    return "NVDA install found but not running"


def _check_mpv() -> str:
    """محرك التشغيل mpv (libmpv): هل صار هو الفعلي، أم التراجع إلى FFmpeg؟"""
    from ampplayer.mpv_engine import mpv_ready

    ok, note = mpv_ready()
    if not ok:
        return f"mpv unavailable ({note}) - will use FFmpeg"
    return f"mpv OK ({note})"


def _check_source_manager() -> str:
    """مدير مصادر الترجمة الخارجية: الأولوية ومنع النطق المكرّر."""
    from ampplayer import subtitle_manager as sm

    m = sm.SubtitleManager("auto")
    m.set_source(sm.SourceKind.REMOTE, True)
    m.set_source(sm.SourceKind.EMBEDDED, True)
    if m.active_kind() != sm.SourceKind.EMBEDDED:
        raise RuntimeError("source priority broken: embedded should beat remote")
    m.set_source(sm.SourceKind.EXTERNAL, True)
    if m.active_kind() != sm.SourceKind.EXTERNAL:
        raise RuntimeError("source priority broken: external should win")
    p = sm.SpeakPolicy()
    if p.offer("مرحبا", 0) is None or p.offer("مرحبا", 1) is not None:
        raise RuntimeError("speak dedup broken")
    return f"{len(sm.PRIORITY)} subtitle sources, priority+dedup OK"


CHECKS: List[Tuple[str, Callable[[], str]]] = [
    ("interpreter", _check_interpreter),
    ("PySide6/Qt", _check_pyside),
    ("FFmpeg engine (av)", _check_av),
    ("numpy", _check_numpy),
    ("audio output (sounddevice)", _check_sounddevice),
    ("engine availability", _check_availability_surface),
    ("subtitle parser", _check_subtitle_parser),
    ("settings", _check_config),
    ("download sites", _check_providers),
    ("speech (pyttsx3)", _check_tts),
    ("NVDA controller client", _check_nvda),
    ("mpv engine (libmpv)", _check_mpv),
    ("subtitle source manager", _check_source_manager),

    ("ffmpeg.exe (optional)", _check_ffmpeg_optional),
    ("main window", _check_gui),
]


def run() -> int:
    lines: List[str] = []
    lines.append("Amp Player self-test")
    lines.append(f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"exe : {sys.executable}")
    lines.append("-" * 70)

    failed = 0
    for name, fn in CHECKS:
        ok, line = _check(name, fn)
        if not ok:
            failed += 1
        lines.append(line)

    lines.append("-" * 70)
    total = len(CHECKS)
    verdict = "PASS" if failed == 0 else f"FAIL ({failed} of {total})"
    lines.append(f"result: {verdict}")

    report = _write_report(lines)
    text = "\n".join(lines)
    try:
        print(text)
    except Exception:
        pass
    try:
        print(f"report written to: {report}")
    except Exception:
        pass
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
