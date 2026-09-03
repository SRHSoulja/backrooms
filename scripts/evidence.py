"""Shared evidence rules for source-backed findings.

Both the autonomy subprocess (at extraction time) and the daemon (at
publication time) use these pure functions so a finding is judged by one
standard. Nothing here touches the network, the model, or local state.
"""

import re

STOPWORDS = {"about", "after", "also", "from", "into", "that", "this", "with", "what", "which",
             "where", "when", "does", "did", "have", "their", "there", "these", "those", "than"}
IMPERATIVE = re.compile(r"^(?:explore|search|analyze|identify|continue|find|review|investigate|look)\b", re.I)
QUOTE_SUPPORT_THRESHOLD = 0.85
MIN_FUZZY_TOKENS = 4
_PUNCTUATION_MAP = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                    " ": " ", "…": "..."}


def normalize(text):
    """Lower-case, fold typographic punctuation, and collapse whitespace."""
    value = str(text or "")
    for source, target in _PUNCTUATION_MAP.items():
        value = value.replace(source, target)
    return re.sub(r"\s+", " ", value).strip().lower()


def tokens(text):
    return re.findall(r"[a-z0-9]+", normalize(text))


def _lcs_length(left, right):
    """Length of the longest common subsequence of two short token lists."""
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    for item in left:
        current = [0]
        for index, other in enumerate(right, start=1):
            if item == other:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[index - 1]))
        previous = current
    return previous[-1]


def quote_support(quote, excerpt, threshold=QUOTE_SUPPORT_THRESHOLD):
    """Return (supported, score, mode) describing how well the excerpt backs the quote.

    An exact normalized substring scores 1.0. Otherwise the quote must share at
    least ``threshold`` of its tokens, in order, with some window of the excerpt.
    Small models paraphrase punctuation and drop function words; this keeps the
    evidence bar high without demanding byte-exact copying.
    """
    quote_tokens = tokens(quote)
    excerpt_tokens = tokens(excerpt)
    if not quote_tokens or not excerpt_tokens:
        return False, 0.0, "none"
    if normalize(quote) in normalize(excerpt):
        return True, 1.0, "exact"
    if len(quote_tokens) < MIN_FUZZY_TOKENS:
        return False, 0.0, "too-short"
    window = len(quote_tokens) + max(2, len(quote_tokens) // 4)
    anchors = set(quote_tokens)
    best = 0.0
    for start, token in enumerate(excerpt_tokens):
        if token not in anchors:
            continue
        segment = excerpt_tokens[start:start + window]
        score = _lcs_length(quote_tokens, segment) / len(quote_tokens)
        if score > best:
            best = score
            if best >= 1.0:
                break
    supported = best >= threshold
    return supported, round(best, 3), "fuzzy" if supported else "unsupported"


def claim_terms(claim):
    return {term for term in re.findall(r"[a-z0-9]{4,}", normalize(claim)) if term not in STOPWORDS}


def claim_grounded(claim, quote):
    """A claim must share vocabulary with its quote and must not be an instruction."""
    if not claim or not quote:
        return False, "missing-claim-or-quote"
    if IMPERATIVE.match(str(claim).strip()):
        return False, "imperative-claim"
    terms = claim_terms(claim)
    quote_vocabulary = set(re.findall(r"[a-z0-9]{4,}", normalize(quote)))
    if len(terms & quote_vocabulary) < min(2, len(terms)):
        return False, "claim-not-grounded-in-quote"
    return True, "grounded"


def classify_finding(claim, quote, excerpt=None, confidence=None):
    """Return (status, reason, quote_score) for a candidate finding.

    ``excerpt`` may be None when re-checking a stored record whose page text is
    no longer available; the stored quote-to-excerpt verdict is then trusted and
    only claim grounding is re-evaluated.
    """
    if confidence is not None:
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            return "rejected", "invalid-confidence", 0.0
        if not 0 <= value <= 1:
            return "rejected", "invalid-confidence", 0.0
    grounded, reason = claim_grounded(claim, quote)
    if not grounded:
        return "rejected", reason, 0.0
    if excerpt is None:
        return "unreviewed", "grounded", 1.0
    supported, score, mode = quote_support(quote, excerpt)
    if not supported:
        return "rejected", f"quote-{mode}", score
    return "unreviewed", f"quote-{mode}", score


def is_accepted(record):
    """Rejected rows stay in the ledger for audit but never count as evidence."""
    return str((record or {}).get("status", "unreviewed")) not in {"rejected", "retracted"}
