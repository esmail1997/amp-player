"""جسر NVDA Controller Client — نطق عبر قارئ الشاشة NVDA مباشرة.

يقوم على مكتبة ``nvdaControllerClient.dll`` الرسمية (رخصة LGPL 2.1) التي
نضمّنها في حزمة التطبيق، فترسل النص إلى NVDA عبر RPC فينطقه NVDA بصوته
وصياغته الخاصة. لا يلامس البرنامج جهاز الصوت عند النطق إطلاقاً، فليس هناك
أي تداخل ممكن مع صوت الفيلم (وهذا ما أنهى مشكلة التقطيع جذرياً).

الملف يعمل أيضاً عندما يُشغَّل البرنامج من المصدر ويجد DLLً بجانب مجلد
الحزمة.

الدوال المعرّفة بالنظام كلها تعيد رموز خطأ ويندوز القياسية: 0 = نجاح.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from typing import Optional

# اسم الملف الثنائي (نضمّنه في جذر الحزمة المجمّدة)
_DLL_NAME = "nvdaControllerClient.dll"


class _Loader(threading.local):
    """حمّال آمن للخيوط: يحمل DLL مرة واحدة لكل خيط."""

    dll = None


_loader = _Loader()


def _candidate_dirs() -> list[str]:
    """أماكن محتملة لملف DLL: الحزمة المجمّدة ثم مجلد الحزمة المصدرية."""
    dirs: list[str] = []
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", ""):
        dirs.append(str(sys._MEIPASS))  # type: ignore[attr-defined]
    pkg = os.path.dirname(os.path.abspath(__file__))
    dirs.insert(0, pkg)
    dirs.append(os.path.join(pkg, "vendor"))
    # مجلد NVDA المثبّت (إن وجد الملف فيه)
    probe = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "NVDA")
    dirs.append(probe)
    return list(dict.fromkeys(dirs))


def _load() -> Optional[ctypes.CDLL]:
    if _loader.dll is not None:
        return _loader.dll
    for d in _candidate_dirs():
        path = os.path.join(d, _DLL_NAME)
        if os.path.exists(path):
            try:
                dll = ctypes.WinDLL(path)
            except OSError:
                continue
            dll.nvdaController_testIfRunning.restype = ctypes.c_uint32
            dll.nvdaController_speakText.restype = ctypes.c_uint32
            dll.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
            dll.nvdaController_cancelSpeech.restype = ctypes.c_uint32
            dll.nvdaController_brailleMessage.restype = ctypes.c_uint32
            dll.nvdaController_brailleMessage.argtypes = [ctypes.c_wchar_p]
            dll.nvdaController_getProcessId.restype = ctypes.c_uint32
            dll.nvdaController_getProcessId.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
            _loader.dll = dll
            return dll
    _loader.dll = None
    return None


def dll_available() -> bool:
    """هل وُجد وتم تحميل DLL الجسر؟"""
    return _load() is not None


def is_running() -> bool:
    """هل NVDA يعمل الآن؟ (0 = يعمل)."""
    dll = _load()
    if dll is None:
        return False
    try:
        return dll.nvdaController_testIfRunning() == 0
    except Exception:
        return False


def speak_text(text: str) -> bool:
    """يطلب من NVDA نطق نص. يعيد النجاح."""
    if not text:
        return True
    dll = _load()
    if dll is None:
        return False
    try:
        return dll.nvdaController_speakText(text) == 0
    except Exception:
        return False


def cancel_speech() -> None:
    """يوقف نطق NVDA فوراً."""
    dll = _load()
    if dll is None:
        return
    try:
        dll.nvdaController_cancelSpeech()
    except Exception:
        pass


def nvda_pid() -> Optional[int]:
    """معرّف عملية NVDA، أو None إن لم يكن متاحاً."""
    dll = _load()
    if dll is None:
        return None
    try:
        pid = ctypes.c_uint32(0)
        res = dll.nvdaController_getProcessId(ctypes.byref(pid))
        return int(pid.value) if res == 0 else None
    except Exception:
        return None


def engine_summary() -> str:
    """وصف وجيز لحالة الجسر (يعرضه السلف-تجريبي)."""
    if not dll_available():
        return "dll missing"
    if is_running():
        return f"NVDA running (pid={nvda_pid()})"
    return "NVDA not running"