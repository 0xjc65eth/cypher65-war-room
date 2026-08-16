"""
CYPHER65 // Name normalization & sanitization
==============================================
Worker name utilities — normalize case, strip whitespace, decode HTML entities,
and merge case-duplicate workers (e.g. CYPHERORDIFUTURE == cypherordifuture).

Used by services/polling.py and static/app.js.
"""

import html
import re

# ── Character filter: keep only safe printable chars ──
# Removes null bytes, control chars, and other rendering-breaking garbage.
_SAFE_CHAR_RE = re.compile(r"[^\x20-\x7E\x80-\xFF\xA0-\xFF]")


def sanitize(raw: str) -> str:
    """Clean a worker name: decode HTML entities, strip whitespace, remove
    control/garbage characters.

    Examples
    --------
    >>> sanitize('cypher65&amp;')
    'cypher65&'
    >>> sanitize('  CYPHER65 ')
    'CYPHER65'
    >>> sanitize('')
    ''
    """
    if not raw:
        return ""
    # 1. Decode HTML entities (&amp; → &, &lt; → <, etc.)
    decoded = html.unescape(str(raw))
    # 2. Remove control characters / null bytes
    cleaned = _SAFE_CHAR_RE.sub("", decoded)
    # 3. Strip whitespace
    return cleaned.strip()


def normalize(raw: str) -> str:
    """Fully normalize a worker name for comparison: sanitize + lowercase.

    Use this when comparing worker names/IDs so that case differences
    (e.g. CYPHERORDIFUTURE vs cypherordifuture) are treated as equal.

    Examples
    --------
    >>> normalize('CYPHERORDIFUTURE')
    'cypherordifuture'
    >>> normalize('cypher65&amp;')
    'cypher65&'
    >>> normalize('')
    ''
    """
    return sanitize(raw).lower()


def dedup_key(name: str) -> str:
    """Return a case-insensitive deduplication key for a worker name.

    Two workers whose names produce the same dedup_key are considered
    the same worker with different case (e.g. CYPHERORDIFUTURE == cypherordifuture).

    Examples
    --------
    >>> dedup_key('CYPHERORDIFUTURE') == dedup_key('cypherordifuture')
    True
    >>> dedup_key('cypher65&amp;') == dedup_key('cypher65&')
    True
    """
    return normalize(name)
