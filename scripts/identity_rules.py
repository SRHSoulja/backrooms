"""Identity rules shared by recruitment and registry maintenance."""

import re

RESERVED_NAMES = ("echo", "morrow")


def is_reserved_name(name):
    """Core resident names may not be reused or embedded in a hireling's name."""
    text = str(name or "")
    return any(re.search(rf"\b{reserved}\b", text, re.I) for reserved in RESERVED_NAMES)


TITLES = {"dr", "mr", "mrs", "ms", "prof", "sir", "dame", "the"}


def name_stem(name):
    """The first real word of a name, lower-cased: 'Vex-9' -> 'vex', 'Dr. Glimmerbeam' -> 'glimmerbeam'.

    Two residents that differ only by a number or a suffix share a stem."""
    for token in re.findall(r"[A-Za-z]+", str(name or "")):
        word = token.lower()
        if word not in TITLES and len(word) >= 2:
            return word
    return ""


def shares_stem(name, current_names):
    """The current resident whose name shares a stem with ``name``, or None."""
    stem = name_stem(name)
    if not stem:
        return None
    for existing in current_names:
        if name_stem(existing) == stem:
            return existing
    return None
