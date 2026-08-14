import re
import unicodedata

from bs4 import BeautifulSoup

RTL_RANGES = (
    (0x0590, 0x08FF),
    (0xFB1D, 0xFDFF),
    (0xFE70, 0xFEFF),
)

ARABIC_VARIANTS = str.maketrans(
    {
        "ك": "ک",
        "ي": "ی",
        "ى": "ی",
        "ئ": "ی",
        "ة": "ه",
        "ۀ": "ه",
        "ؤ": "و",
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
    }
)

DIACRITIC_CATEGORIES = {"Mn", "Me"}
WHITESPACE_RE = re.compile(r"\s+")
LANGUAGE_HINT_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$")

SCRIPT_RANGES = {
    "Arab": ((0x0600, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)),
    "Cyrl": ((0x0400, 0x052F),),
    "Deva": ((0x0900, 0x097F),),
    "Hebr": ((0x0590, 0x05FF), (0xFB1D, 0xFB4F)),
    "Latn": ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F)),
}

LANGUAGE_SCRIPTS = {
    "ar": frozenset({"Arab"}),
    "en": frozenset({"Latn"}),
    "fa": frozenset({"Arab"}),
    "he": frozenset({"Hebr"}),
    "hi": frozenset({"Deva"}),
    "ps": frozenset({"Arab"}),
    "ru": frozenset({"Cyrl"}),
    "ur": frozenset({"Arab"}),
}


def fingerprint_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(ARABIC_VARIANTS)
    without_marks = "".join(ch for ch in normalized if unicodedata.category(ch) not in DIACRITIC_CATEGORIES)
    return WHITESPACE_RE.sub(" ", without_marks.casefold()).strip()


def html_to_text(value: str) -> str:
    if not value:
        return ""
    return BeautifulSoup(value, "lxml").get_text(" ", strip=True)


def infer_direction(value: str) -> str:
    rtl_count = 0
    ltr_count = 0
    for ch in value:
        codepoint = ord(ch)
        if any(start <= codepoint <= end for start, end in RTL_RANGES):
            rtl_count += 1
        elif "a" <= ch.lower() <= "z":
            ltr_count += 1
    return "rtl" if rtl_count > ltr_count else "ltr"


def infer_script(value: str) -> str | None:
    counts = {script: 0 for script in SCRIPT_RANGES}
    for ch in value:
        codepoint = ord(ch)
        for script, ranges in SCRIPT_RANGES.items():
            if any(start <= codepoint <= end for start, end in ranges):
                counts[script] += 1
                break
    script, count = max(counts.items(), key=lambda item: item[1])
    return script if count else None


def normalized_language_hint(value: str | None, *, script_code: str | None) -> str | None:
    """Return a normalized source hint only when text does not contradict it.

    Source hints remain useful defaults, but they are not item-level detection.
    Unknown or absent hints therefore stay unknown, while known single-script
    languages are rejected when the item text is visibly in another script.
    """

    if value is None:
        return None
    candidate = value.strip()
    if not LANGUAGE_HINT_RE.fullmatch(candidate):
        return None
    language = candidate.split("-", 1)[0].lower()
    expected_scripts = LANGUAGE_SCRIPTS.get(language)
    if script_code is not None and expected_scripts is not None and script_code not in expected_scripts:
        return None
    return language
