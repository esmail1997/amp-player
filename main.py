#!/usr/bin/env python3
"""
Amp Player - مشغل صوت وفيديو للمكفوفين
Accessible audio/video player with subtitle reading.

الاستخدام:
    python main.py                    # تشغيل عادي
    python main.py movie.mkv          # فتح ملف
    python main.py movie.mkv --sub a.srt
"""

from __future__ import annotations

import sys
from pathlib import Path

# إضافة مجلد المشروع إلى المسار
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ampplayer.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())