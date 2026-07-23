"""
CYPHER65 // PARASITE POOL WAR ROOM — helpers
============================================
Shared formatting, parsing, and utility functions extracted from app.py.
"""
import math
import time
import logging
import json
from collections import deque

log = logging.getLogger("cypher65")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Parsing
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def parse_diff_to_float(s):
    """Convert '1.23 T' → 1.23e12. Returns 0 if unparseable."""
    if not isinstance(s, str):
        try:
            return float(s)
        except Exception:
            return 0
    s = s.strip().replace(",", ".")
    mult = 1
    suffix_map = {"P": 1e15, "T": 1e12, "G": 1e9, "M": 1e6, "K": 1e3}
    for suf, m in suffix_map.items():
        if s.endswith(suf):
            mult = m
            s = s[:-1]
            break
    try:
        return float(s) * mult
    except Exception:
        return 0


def safe_int(v, default=0):
    """int() that survives 'N/A', 'null', '', whitespace, etc."""
    if v is None:
        return default
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        v = v.strip().upper()
        if v in ("", "N/A", "NA", "NULL", "NONE", "—", "-"):
            return default
        try:
            return int(float(v))
        except Exception:
            return default
    return default


def safe_num_from_str(v, default=None):
    """Parse string-encoded int or float from APIs."""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            s = v.strip()
            return float(s) if "." in s or "e" in s.lower() else int(s)
        except Exception:
            return default
    return default


def coerce_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def coerce_int(v, default=0):
    try:
        return int(float(v))
    except Exception:
        return default


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Formatting
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fmt_diff(v):
    """Pretty print a large number into readable difficulty units."""
    if not v:
        return "0"
    v = float(v)
    for unit in ["", "K", "M", "G", "T", "P", "E"]:
        if v < 1000:
            return f"{v:.2f} {unit}".strip()
        v /= 1000
    return f"{v:.2f} Z"


def fmt_hashrate(h):
    """Format hashrate in nice units."""
    if not h:
        return "0 H/s"
    h = float(h)
    for unit in ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s"]:
        if h < 1000:
            return f"{h:.2f} {unit}"
        h /= 1000
    return f"{h:.2f} ZH/s"


def fmt_uptime(seconds):
    if not seconds:
        return "—"
    s = int(seconds)
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    return " ".join(parts) if parts else f"{s}s"


def fmt_age(ts):
    if not ts:
        return "—"
    delta = int(time.time()) - int(ts)
    if delta < 0:
        return "in future"
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def human_int(v):
    """Compact integer formatter: 12,345 → '12K', 1.2M → '1.2M'."""
    try:
        v = float(v)
    except Exception:
        return str(v)
    if v < 1000:
        return f"{v:.0f}"
    for unit in ["", "K", "M", "B", "T"]:
        if v < 1000:
            return f"{v:.1f}{unit}".rstrip("0").rstrip(".")
        v /= 1000
    return f"{v:.1f}Q"


def human_secs_long(secs):
    """Human-readable long duration: seconds → 'X.Xy' (years displayed at 1dp)."""
    if secs is None:
        return "—"
    if not isfinite_v(secs) or secs <= 0:
        return "—"
    s = float(secs)
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s/60:.1f}m"
    if s < 86400:
        return f"{s/3600:.1f}h"
    days = s / 86400
    if days < 365:
        return f"{days:.0f}d"
    years = days / 365.25
    if years < 100:
        return f"{years:.1f}y"
    if years < 1e6:
        return f"{years:,.0f}y"
    return f"{years/1e6:.1f}My"


def isfinite_v(v):
    try:
        return math.isfinite(float(v))
    except Exception:
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Memory alert builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_next_memory_alert_id = 0


def make_memory_alert(ts, severity, category, message):
    """Build an in-memory alert dict with a STABLE id."""
    global _next_memory_alert_id
    a = {
        "id": _next_memory_alert_id,
        "ts": ts,
        "severity": severity,
        "category": category,
        "message": message,
        "memory_only": True,
    }
    _next_memory_alert_id += 1
    return a
