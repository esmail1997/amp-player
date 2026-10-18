"""بيانات التواصل مع مطوّر البرنامج (تظهر في نافذة «حول»)."""

from __future__ import annotations

EMAIL = "emalmh.2016@gmail.com"
TWITTER_HANDLE = "esmail1211"
TWITTER_URL = "https://twitter.com/esmail1211"

# يظهر في قائمة النسخ ولصق البيانات دفعةً واحدة
CONTACT_LINES = (
    f"Email: {EMAIL}",
    f"Twitter/X: @{TWITTER_HANDLE}",
    TWITTER_URL,
)


def contact_text() -> str:
    """نصّ التواصل جاهزاً للنسخ أو النطق."""
    return "\n".join(CONTACT_LINES)


def mailto_url(subject: str = "Amp Player") -> str:
    from urllib.parse import quote

    return f"mailto:{EMAIL}?subject={quote(subject)}"
