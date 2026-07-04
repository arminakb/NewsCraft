import re
import unicodedata

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


def fingerprint_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(ARABIC_VARIANTS)
    without_marks = "".join(ch for ch in normalized if unicodedata.category(ch) not in DIACRITIC_CATEGORIES)
    return WHITESPACE_RE.sub(" ", without_marks.casefold()).strip()


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
