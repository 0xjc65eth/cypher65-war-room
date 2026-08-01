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


def derive_worker_hashrate(share_calc_history=None, prev_pool=None, pool=None, elapsed_s=0.0):
    """Derive worker hashrate (H/s) when the pool reports 0 or missing.

    FENIX E1 (P1) fallback. Sources, in priority:
      1. "shares" — median of the most recent per-share instantaneous
         hashrates from share_calc_history (each = hashes_attempted /
         gap between submissions). Worker-specific, most representative.
      2. "work_delta" — pool workSinceLastBlock growth between two polls:
         ((cur_wslb - prev_wslb) * 2**32) / elapsed_s. Pool-wide proxy.

    Returns (hps, source_label) or (0.0, None) when nothing can be derived.
    Never raises.
    """
    try:
        # 1) Per-share instantaneous hashrate history (worker-specific)
        sch = list(share_calc_history or [])
        inst = [
            float(e.get("instantaneous_hr_hps") or 0)
            for e in sch if e.get("instantaneous_hr_hps")
        ]
        inst = [v for v in inst if v > 0]
        if inst:
            window = inst[-5:]  # last 5 shares, median for stability
            window.sort()
            median = window[len(window) // 2]
            if median > 0:
                return median, "shares"
        # 2) Pool workSinceLastBlock delta across polls
        if pool and prev_pool and elapsed_s and elapsed_s > 0:
            cur = float(pool.get("workSinceLastBlock") or 0)
            prev = float(prev_pool.get("workSinceLastBlock") or 0)
            if cur > prev:
                hps = (cur - prev) * (2 ** 32) / float(elapsed_s)
                if hps > 0:
                    return hps, "work_delta"
    except Exception:
        pass
    return 0.0, None


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
#  Bitcoin address validation (Bech32 + Base58Check)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Bech32 character set (BIP-173)
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
# Base58 alphabet (no 0, O, I, l)
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _bech32_polymod(values):
    """Compute Bech32 checksum using GF(32) generator."""
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= GEN[i]
    return chk


def _bech32_hrp_expand(hrp):
    """Expand HRP for checksum computation."""
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_verify_checksum(hrp, data):
    """Verify Bech32 checksum. Returns True if valid."""
    return _bech32_polymod(_bech32_hrp_expand(hrp) + data) == 1


def _decode_bech32(addr):
    """Decode a Bech32 address. Returns (hrp, data_part) or None.
    Handles both Bech32 (BIP-173) and Bech32m (BIP-350) but for
    Bitcoin addresses we only need Bech32 (bc1).
    """
    addr = addr.lower()
    # Find the last '1' separator
    pos = addr.rfind('1')
    if pos < 1 or pos + 7 > len(addr):
        return None
    hrp = addr[:pos]
    data = addr[pos + 1:]
    if len(data) < 6:
        return None
    # Check all characters are valid bech32
    for c in data:
        if c not in _BECH32_CHARSET:
            return None
    # Convert to 5-bit values
    values = [_BECH32_CHARSET.index(c) for c in data]
    # Verify checksum
    if not _bech32_verify_checksum(hrp, values):
        return None
    return (hrp, values[:-6])  # Strip checksum


def _decode_base58(addr):
    """Decode a Base58 string to an integer."""
    n = 0
    for c in addr:
        idx = _BASE58_ALPHABET.find(c)
        if idx == -1:
            return None
        n = n * 58 + idx
    return n


def _base58check_decode(addr):
    """Decode and verify Base58Check address.
    Returns (version_byte, payload) or None if invalid."""
    n = _decode_base58(addr)
    if n is None:
        return None
    # Convert to bytes (big-endian, minimum size)
    b = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    # Add leading zero bytes from Base58 encoding
    leading_zeros = 0
    for c in addr:
        if c == '1':
            leading_zeros += 1
        else:
            break
    if leading_zeros > 0:
        b = b'\x00' * leading_zeros + b
    if len(b) < 5:  # version(1) + payload + checksum(4)
        return None
    payload = b[:-4]
    checksum = b[-4:]
    # Verify checksum: first 4 bytes of double-SHA256 of payload
    import hashlib
    h = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if h != checksum:
        return None
    return (payload[0], payload[1:])


def validate_btc_address(addr: str) -> dict:
    """Validate a Bitcoin address. Returns dict with 'valid' bool and optional 'error' message.
    Supports Bech32 (bc1..., BIP-173), P2PKH (1..., Base58Check), P2SH (3..., Base58Check)."""
    if not addr or not isinstance(addr, str):
        return {"valid": False, "error": "Address is required"}
    addr = addr.strip()
    if len(addr) < 26 or len(addr) > 90:
        return {"valid": False, "error": f"Invalid address length ({len(addr)} chars)"}

    if addr.startswith('bc1'):
        # Bech32 (SegWit / Taproot)
        result = _decode_bech32(addr)
        if result is None:
            return {"valid": False, "error": "Invalid Bech32 checksum or format"}
        hrp, data = result
        if hrp != 'bc':
            return {"valid": False, "error": "Invalid human-readable part (expected 'bc')"}
        if len(data) < 2 or len(data) > 40:
            return {"valid": False, "error": "Invalid data length for Bech32 address"}
        return {"valid": True}

    elif addr.startswith('1') or addr.startswith('3'):
        # P2PKH (1...) or P2SH (3...) — Base58Check
        result = _base58check_decode(addr)
        if result is None:
            return {"valid": False, "error": "Invalid Base58Check checksum or format"}
        version, _ = result
        expected_version = 0x00 if addr.startswith('1') else 0x05
        if version != expected_version:
            return {"valid": False, "error": "Invalid version byte for address type"}
        return {"valid": True}

    elif addr.startswith('2'):
        # P2WPKH-in-P2SH (starts with '2'? Rare but some use it)
        result = _base58check_decode(addr)
        if result is not None:
            return {"valid": True}
        return {"valid": False, "error": "Invalid address format"}

    else:
        return {"valid": False, "error": "Address must start with 'bc1' (SegWit), '1' (Legacy), or '3' (P2SH)"}


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
