"""Identity rules shared by recruitment and registry maintenance."""

import re

RESERVED_NAMES = ("echo", "morrow")


def is_reserved_name(name):
    """Core resident names may not be reused or embedded in a hireling's name."""
    text = str(name or "")
    return any(re.search(rf"\b{reserved}\b", text, re.I) for reserved in RESERVED_NAMES)
