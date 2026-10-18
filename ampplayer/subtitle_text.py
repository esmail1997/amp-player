"""
تنظيف نصوص الترجمة وتوحيدها.

تُطبّق هذه الدوال على نصوص الترجمة الخارجية قبل النطق أو العرض:

- إزالة وسوم ASS/SSA مثل ``{\\an8}{\\pos(..)}`` و``{\\i1}``.
- إزالة وسوم HTML مثل ``<i>`` و``<font ...>``.
- تحويل ``\\N`` و``\\n`` و``\\h`` إلى فواصل أسطر/مسافات.
- توحيد المسافات وعلامات الاتجاه.
- مفتاح توحيد (dedup key) لكشف تكرار السطر نفسه، مع تجاهل التشكيل
  العربي وعلامات الترقيم وفروق الحالة، حتى لا يُقرأ السطر نفسه مرتين.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# وسوم ASS/SSA: كل ما بين قوسين معقوفين
_ASS_TAG = re.compile(r"\{[^}]*\}")
# وسوم HTML/XML البسيطة الشائعة في SRT/VTT
_HTML_TAG = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(\s[^>]*)?/?>")
# رموز html للكيانات الشائعة
_ENTITIES = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&#39;": "'", "&apos;": "'",
}
_ENTITY_RE = re.compile(r"&[a-zA-Z#0-9]+;")
# مسافات رأسية أفقيّة غير مرئية
_SPACES = re.compile(r"[ \t\u00a0\u200b\u200e\u200f\ufeff]+")
_BLANKS = re.compile(r"[ \t]*\n[ \t]*")
_MULTI_NL = re.compile(r"\n{2,}")

# علامات ترقيم تُتجاهل عند مقارنة التكرار
_PUNCT = re.compile(
    r"[.,;:!?…،؛؟\"'«»„“”‘’()\[\]{}<>/\\|*_~^`+=—-]"
)
# تشكيل عربي + تطويل + رموز صفرية العرض
_AR_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")


def strip_formatting(text: str) -> str:
    """يزيل وسوم ASS/HTML دون المساس بالكلام."""
    if not text:
        return ""
    text = _ASS_TAG.sub("", text)
    text = _HTML_TAG.sub("", text)
    for ent, ch in _ENTITIES.items():
        if ent in text:
            text = text.replace(ent, ch)
    text = _ENTITY_RE.sub("", text)
    return text


def normalize_breaks(text: str) -> str:
    """يحوّل ``\\N`` و``\\n`` و``\\h`` إلى فواصل حقيقية."""
    if not text:
        return ""
    text = text.replace("\\N", "\n").replace("\\n", "\n")
    text = text.replace("\\h", " ")
    return text


def clean_subtitle_text(text: str) -> str:
    """التنظيف الكامل: وسوم + فواصل + مسافات، مع الحفاظ على المعنى."""
    if not text:
        return ""
    text = normalize_breaks(text)
    text = strip_formatting(text)
    text = _SPACES.sub(" ", text)
    text = _BLANKS.sub("\n", text)
    text = _MULTI_NL.sub("\n", text)
    return text.strip()


def dedup_key(text: str) -> str:
    """
    مفتاح مقارنة يتحمّل الفروق غير المعنوية.

    نزيل التشكيل العربي والتطويل وعلامات الترقيم، ونوحّد المسافات، ونطبع
    ألا والحروف إلى صورة واحدة. يُستعمل لمنع نطق السطر نفسه مرتين.
    """
    if not text:
        return ""
    key = strip_formatting(text).casefold()
    key = _AR_DIACRITICS.sub("", key)
    key = unicodedata.normalize("NFKC", key)
    # توحيد الألف والهمزات والياء/التاء المربوطة لتسهيل مقارنة الأسطر
    key = (key.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
              .replace("ى", "ي").replace("ة", "ه"))
    key = _PUNCT.sub(" ", key)
    key = _SPACES.sub(" ", key)
    return key.strip()


def is_similar(a: str, b: str, threshold: float = 0.86) -> bool:
    """
    هل النصّان متشابهان بما يكفي لاعتبارهما السطر نفسه؟

    حين يتساوى الطولان نكتفي بتشابه 0.72، بينما نطلب تشابهاً أعلى
    (0.86) حين يختلف الطولان لتفادي دمج أسطر مختلفة.
    """
    ka, kb = dedup_key(a), dedup_key(b)
    if not ka or not kb:
        return ka == kb
    if ka == kb:
        return True
    la, lb = len(ka), len(kb)
    # المقارنة باهظة على النصوص الطويلة: نكتفي بالطول أولاً
    if abs(la - lb) > max(6, int(0.5 * max(la, lb))):
        return False
    ratio = SequenceMatcher(None, ka, kb).ratio()
    if ratio >= threshold:
        return True
    if la == lb and ratio >= 0.72:
        return True
    return False


def split_lines(text: str) -> list[str]:
    """يقسّم السطر إلى أسطره مع تجاهل الفوارغ."""
    return [ln for ln in clean_subtitle_text(text).split("\n") if ln.strip()]


def merge_lines(text: str, joiner: str = " ") -> str:
    """يدمج أسطر الترجمة في سطر واحد للنطق."""
    return joiner.join(split_lines(text))
