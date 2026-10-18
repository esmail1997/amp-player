"""ترقيع عطب معروف في pyttsx3 على ويندوز (محرّك SAPI).

**المشكلة:** بعض أصوات SAPI تعيد أكثر من لغة مفصولة بفاصلة منقوطة، مثل
``401;1`` (‏0x401 = العربية السعودية). يمرّر pyttsx3 القيمة كما هي إلى
``int(value, 16)`` في ``SAPI5Driver._toVoice`` فتسقط بـ ``ValueError``،
وتبقى قائمة الأصوات فارغة في البرنامج كله: قائمة الأصوات في التفضيلات
فارغة، واختيار الصوت يُتجاهل بصمت.

**الحل:** لا نستبدل منطق pyttsx3 ولا نعدّل حزمته. نلفّ كائن الصوت الصوتي
بكائن رقيق يعيد قيمة لغة واحدة صالحة فقط عند تعرّض القيمة للمشكلة، فيمرّ
التنفيذ الأصلي كما هو تماماً. إن صحّح pyttsx3 عطبه مستقبلاً يصبح الترقيع
غير مؤثّر لأنه يعالج الحالة فقط.

التسمية: ``apply()`` آمنة للتكرار وتُستدعى من محركي النطق (speech و
speech_worker) بعد نجاح استيراد pyttsx3.
"""

from __future__ import annotations

_APPLIED = False


class _SingleLanguage:
    """يمرّر كل شيء إلى الصوت الأصلي، ما عدا «Language» المكسور."""

    __slots__ = ("_attr",)

    def __init__(self, attr) -> None:
        object.__setattr__(self, "_attr", attr)

    def __getattr__(self, name: str):
        return getattr(self._attr, name)

    def __setattr__(self, name: str, value) -> None:
        setattr(self._attr, name, value)

    def GetAttribute(self, name: str):
        value = self._attr.GetAttribute(name)
        if name != "Language" or not isinstance(value, str):
            return value
        # نقبل القيمة الأصلية إن كانت صحيحة وحدها
        for part in value.split(";"):
            part = part.strip()
            if not part:
                continue
            try:
                int(part, 16)
            except ValueError:
                continue
            return part if part != value.strip() else value
        return value


def apply() -> bool:
    """يطبّق الترقيع مرة واحدة. يعيد True إن طُبّق أو كان غير مطلوب."""
    global _APPLIED
    if _APPLIED:
        return True
    try:
        from pyttsx3.drivers import sapi5
    except Exception:
        # ليس على ويندوز أو pyttsx3 غير مثبت: لا حاجة للترقيع
        _APPLIED = True
        return True

    try:
        original = sapi5.SAPI5Driver._toVoice
        if getattr(original, "_amp_wrapped", False):
            _APPLIED = True
            return True

        def _wrapped(attr):
            return original(_SingleLanguage(attr))

        _wrapped._amp_wrapped = True  # type: ignore[attr-defined]
        sapi5.SAPI5Driver._toVoice = staticmethod(_wrapped)  # type: ignore[assignment]
        _APPLIED = True
        return True
    except Exception:
        # إن عطّلنا شيئاً تركنا الوضع كما هو؛ النطق يبقى متاحاً بلا قائمة أصوات
        return False


if __name__ == "__main__":
    raise SystemExit(0 if apply() else 1)
