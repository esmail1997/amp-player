"""النموذج المشترك لنتائج مواقع الترجمة."""

from __future__ import annotations

from dataclasses import dataclass, field


LANGUAGES: list[tuple[str, str, str]] = [
    # (iso639-1, iso639-2, الاسم العربي/الإنجليزي)
    ("ara", "ara", "العربية"),
    ("eng", "eng", "الإنجليزية"),
    ("fre", "fra", "الفرنسية"),
    ("ger", "deu", "الألمانية"),
    ("spa", "spa", "الإسبانية"),
    ("ita", "ita", "الإيطالية"),
    ("rus", "rus", "الروسية"),
    ("por", "por", "البرتغالية"),
    ("tur", "tur", "التركية"),
    ("pol", "pol", "البولندية"),
    ("nld", "nld", "الهولندية"),
    ("per", "fas", "الفارسية"),
    ("urd", "urd", "الأردية"),
    ("hin", "hin", "الهندية"),
    ("jpn", "jpn", "اليابانية"),
    ("kor", "kor", "الكورية"),
    ("chi", "zho", "الصينية"),
    ("heb", "heb", "العبرية"),
    ("swe", "swe", "السويدية"),
    ("nor", "nor", "النرويجية"),
    ("dan", "dan", "الدنماركية"),
    ("fin", "fin", "الفنلندية"),
    ("gre", "ell", "اليونانية"),
    ("cze", "ces", "التشيكية"),
    ("hun", "hun", "المجرية"),
    ("rum", "ron", "الرومانية"),
    ("ukr", "ukr", "الأوكرانية"),
    ("vie", "vie", "الفيتنامية"),
    ("tha", "tha", "التايلاندية"),
    ("ind", "ind", "الإندونيسية"),
    ("mal", "msa", "الملايوية"),
]

LANG_BY_CODE: dict[str, str] = {c: n for c, _c2, n in LANGUAGES}
LANG_BY_CODE.update({c2: n for _c, c2, n in LANGUAGES})

# أسماء اللغات كما تظهر في مواقع الترجمة
SITE_LANG_NAMES: dict[str, list[str]] = {
    "ara": ["arabic", "ar", "ara", "عربي", "arabic subtitles"],
    "eng": ["english", "en", "eng"],
    "fre": ["french", "fr", "fre"],
    "ger": ["german", "de", "ger"],
    "spa": ["spanish", "es", "spa", "spanish (latin america)", "spanish (spain)"],
    "ita": ["italian", "it", "ita"],
    "rus": ["russian", "ru", "rus"],
    "por": ["portuguese", "pt", "por", "brazilian portuguese"],
    "tur": ["turkish", "tr", "tur"],
    "pol": ["polish", "pl", "pol"],
    "nld": ["dutch", "nl", "nld"],
    "per": ["farsi/persian", "farsi", "fa", "per", "persian"],
    "urd": ["urdu", "ur", "urd"],
    "hin": ["hindi", "hi", "hin"],
    "jpn": ["japanese", "ja", "jpn"],
    "kor": ["korean", "ko", "kor"],
    "chi": ["chinese", "zh", "chi", "zho"],
    "heb": ["hebrew", "he", "heb"],
    "swe": ["swedish", "sv", "swe"],
    "nor": ["norwegian", "no", "nor"],
    "dan": ["danish", "da", "dan"],
    "fin": ["finnish", "fi", "fin"],
    "gre": ["greek", "el", "gre"],
    "cze": ["czech", "cs", "cze", "ces"],
    "hun": ["hungarian", "hu", "hun"],
    "rum": ["romanian", "ro", "rum", "ron"],
    "ukr": ["ukrainian", "uk", "ukr"],
    "vie": ["vietnamese", "vi", "vie"],
    "tha": ["thai", "th", "tha"],
    "ind": ["indonesian", "id", "ind"],
    "mal": ["malay", "ms", "mal", "msa"],
}


@dataclass
class SubtitleResult:
    """نتيجة ترجمة واحدة من موقع."""
    site: str = ""
    site_name: str = ""
    title: str = ""
    release: str = ""
    year: str = ""
    language: str = ""
    language_code: str = ""
    season: str = ""
    episode: str = ""
    downloads: int = 0
    rating: float = 0.0
    kind: str = "page"          # "download" = رابط مباشر، "page" = صفحة ويب
    url: str = ""
    download_url: str = ""
    source_id: str = ""
    note: str = ""

    @property
    def display_language(self) -> str:
        return LANG_BY_CODE.get(self.language_code.lower(), self.language or self.language_code)

    @property
    def is_direct(self) -> bool:
        return bool(self.download_url)

    def label(self) -> str:
        """وصف نصي كامل للنتيجة (مناسب لقارئ الشاشة)."""
        parts: list[str] = [self.title or self.release or "ترجمة"]
        if self.year:
            parts.append(f"({self.year})")
        if self.season:
            parts.append(f"الموسم {self.season}")
        if self.episode:
            parts.append(f"الحلقة {self.episode}")
        parts.append(f"اللغة: {self.display_language}")
        if self.release and self.release != self.title:
            parts.append(f"الإصدار: {self.release}")
        if self.downloads:
            parts.append(f"{self.downloads} تحميل")
        if self.rating:
            parts.append(f"التقييم {self.rating:.1f}")
        parts.append(f"الموقع: {self.site_name}")
        return " - ".join(p for p in parts if p)


@dataclass
class SearchOutcome:
    """نتيجة بحث كاملة من موقع."""
    site: str = ""
    site_name: str = ""
    results: list[SubtitleResult] = field(default_factory=list)
    error: str = ""
    needs_manual: bool = False   # الموقع يتطلب تدخل يدوي (فتح المتصفح)
    manual_url: str = ""