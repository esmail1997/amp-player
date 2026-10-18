"""
Amp Player - مشغّل وسائط متوافق مع المكفوفين
Accessible audio/video player built with PySide6 + a bundled FFmpeg.

المحرّك كله داخل الحزمة: حزمة `av` تحمل مكتبات FFmpeg معها، فلا يحتاج
المستخدم إلى تثبيت أي مشغّل خارجي.

Author  : Amp Player Project
Version : 1.1.0
License : MIT
"""

__app_name__ = "Amp Player"
__version__ = "1.1.0"
__author__ = "Amp Player Project"
__license__ = "MIT"

# متغيّرات بيئة اختيارية لمسارات الأدوات الخارجية
FFMPEG_PATH_ENV = "AMP_FFMPEG_PATH"        # ffmpeg.exe للدمج الاختياري
FFMPEG_LIB_ENV = "AMP_FFMPEG_LIB"          # مجلد مكتبات FFmpeg، عند الحاجة
