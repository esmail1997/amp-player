"""حزمة اختبارات Amp Player.

وجود هذا الملف ضروري حتى يعمل الأمر:
    python -m unittest discover -s tests -t .

نوجّه الإعدادات إلى ملف مؤقت قبل أي استيراد، فالاختبارات تكتب إعدادات
كثيرة (إزاحة الترجمة، الصوت، اللغة). من دون هذا التوجيه كانت تكتب في
سجل المستخدم الحقيقي، فتنقل الحالة بين الجولات ويفشل اختبار لأنه لم
يبدأ من نقطة معروفة.
"""

import atexit
import os
import tempfile

_fd, _path = tempfile.mkstemp(prefix="ampplayer-tests-", suffix=".ini")
os.close(_fd)
os.environ["AMP_CONFIG_FILE"] = _path


@atexit.register
def _drop_temp_config() -> None:
    """يحذف ملف الإعدادات المؤقت عند انتهاء العملية."""
    try:
        os.unlink(_path)
    except OSError:
        pass