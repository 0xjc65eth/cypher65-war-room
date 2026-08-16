"""
CYPHER65 // PARASITE POOL WAR ROOM — helpers
============================================
Shared formatting, parsing, and utility functions extracted from app.py.
"""

import math
import time
import logging
import json
import os
import hashlib
import threading
from collections import deque
from typing import Any, Optional

log = logging.getLogger("cypher65")

# ── Monotonic nonce (Issue #150) — nonce ms estritamente crescente ─────────
# APIs HMAC que rejeitam nonce duplicado (ex.: MiningRigRentals) exigem que
# cada request use um nonce MAIOR que o último. Fonte única de verdade:
# solo_mining.py, agents/solo_mining_advisor/tools.py e scripts/probe_mrr_api.py
# roteiam todos por este gerador (fix do "Bad Nonce" #148, estendido p/ #150).
_nonce_lock = threading.Lock()
_nonce_last_ms = 0


def next_monotonic_nonce_ms() -> str:
    """Next strictly-increasing millisecond nonce (thread-safe).

    Two calls in the same millisecond (or a clock that stalls or goes
    backwards) would otherwise emit the SAME nonce — which MRR rejects
    with ``Not Authenticated - Invalid Key - Bad Nonce``. The counter
    bumps to ``last + 1`` in those cases so values are always unique
    and increasing within the process.

    Note: per-process counter — the app runs single-process (``python
    app.py``), which is enough for MRR's per-key monotonic requirement.
    """
    global _nonce_last_ms
    with _nonce_lock:
        n = int(time.time() * 1000)
        if n <= _nonce_last_ms:
            n = _nonce_last_ms + 1  # colisão/clock parado/voltando → bump
        _nonce_last_ms = n
        return str(n)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PII redaction (Issue #116) — buyer/operator emails in logs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def mask_email(email: str) -> str:
    """Mask an email for logs: ``loc***@domain`` — never the full local part.

    Keeps the domain + local-prefix for fast operator triage. Short local
    parts (<=3 chars) expose nothing worth hiding and stay untouched.
    """
    email = (email or "").strip()
    if not email:
        return "-"
    if "@" not in email:
        return email[:3] + ("…" if len(email) > 3 else "")
    local, _, domain = email.partition("@")
    shown = local[:3]
    if len(local) > 3:
        shown += "…"
    return f"{shown}@{domain}"


def email_sha(email: str) -> str:
    """Deterministic non-reversible email hash — same scheme as
    conversion._anonymize (sha256 of lowercased email, first 24 hex chars)
    so log correlation matches the funnel's ``email_hash`` 1:1.
    """
    email = (email or "").strip().lower()
    if not email:
        return ""
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:24]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Spreadsheet formula-injection guard (shared CSV exporter safety)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def csv_neutralize(value) -> Any:
    """Neutralize spreadsheet formula-injection on text cells.

    A leading ``= + - @ \t \r`` is a formula risk when the sheet opens the
    CSV and auto-evaluates (Excel/Sheets) — ``=HYPERLINK(...)`` / ``=1+1``
    would EXECUTE. Prefixing such cells with ``'`` makes them inert text.
    Numbers/None pass through untouched (they are never a formula vector).

    Shared by every CSV export (admin accepted-recos, funnel weekly) so the
    guard lives in ONE place (Issue #184).
    """
    if value is None or isinstance(value, (int, float)):
        return value
    s = str(value)
    if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


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


def derive_worker_hashrate(
    share_calc_history=None, prev_pool=None, pool=None, elapsed_s=0.0
):
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
            for e in sch
            if e.get("instantaneous_hr_hps")
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
                hps = (cur - prev) * (2**32) / float(elapsed_s)
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
    GEN = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
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
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr):
        return None
    hrp = addr[:pos]
    data = addr[pos + 1 :]
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
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    # Add leading zero bytes from Base58 encoding
    leading_zeros = 0
    for c in addr:
        if c == "1":
            leading_zeros += 1
        else:
            break
    if leading_zeros > 0:
        b = b"\x00" * leading_zeros + b
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
    Supports Bech32 (bc1..., BIP-173), P2PKH (1..., Base58Check), P2SH (3..., Base58Check).
    """
    if not addr or not isinstance(addr, str):
        return {"valid": False, "error": "Address is required"}
    addr = addr.strip()
    if len(addr) < 26 or len(addr) > 90:
        return {"valid": False, "error": f"Invalid address length ({len(addr)} chars)"}

    if addr.startswith("bc1"):
        # Bech32 (SegWit / Taproot)
        result = _decode_bech32(addr)
        if result is None:
            return {"valid": False, "error": "Invalid Bech32 checksum or format"}
        hrp, data = result
        if hrp != "bc":
            return {
                "valid": False,
                "error": "Invalid human-readable part (expected 'bc')",
            }
        if len(data) < 2 or len(data) > 40:
            return {"valid": False, "error": "Invalid data length for Bech32 address"}
        return {"valid": True}

    elif addr.startswith("1") or addr.startswith("3"):
        # P2PKH (1...) or P2SH (3...) — Base58Check
        result = _base58check_decode(addr)
        if result is None:
            return {"valid": False, "error": "Invalid Base58Check checksum or format"}
        version, _ = result
        expected_version = 0x00 if addr.startswith("1") else 0x05
        if version != expected_version:
            return {"valid": False, "error": "Invalid version byte for address type"}
        return {"valid": True}

    elif addr.startswith("2"):
        # P2WPKH-in-P2SH (starts with '2'? Rare but some use it)
        result = _base58check_decode(addr)
        if result is not None:
            return {"valid": True}
        return {"valid": False, "error": "Invalid address format"}

    else:
        return {
            "valid": False,
            "error": "Address must start with 'bc1' (SegWit), '1' (Legacy), or '3' (P2SH)",
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Solo-mining probability math (single source of truth)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_solo_probabilities(
    share_of_network: float, blocks_per_day: float = 144.0
) -> dict:
    """Solo-mining probability math — single source of truth for app.py._do_poll().

    `share_of_network` is the per-BLOCK chance (worker hashrate ÷ network
    hashrate). With ~144 blocks/day:
      - P(≥1 block in N days) = 1 - (1 - share)^(144·N)
      - expected blocks/year   = share × 144 × 365
      - expected time (days)   = 1 / (share × 144)

    Returns a dict with keys: solo_p_day, solo_p_year, solo_p_5year,
    solo_expected_blocks_per_year, solo_expected_time_to_block_days.
    When share <= 0, all probabilities are 0 and expected time is None
    (guards the divide-by-zero; never raises).
    """
    if share_of_network is None or share_of_network <= 0:
        return {
            "solo_p_day": 0.0,
            "solo_p_year": 0.0,
            "solo_p_5year": 0.0,
            "solo_expected_blocks_per_year": 0.0,
            "solo_expected_time_to_block_days": None,
        }
    solo_p_day = 1 - (1 - share_of_network) ** blocks_per_day  # P(≥1 block today)
    solo_p_year = 1 - (1 - share_of_network) ** (blocks_per_day * 365)
    solo_p_5year = 1 - (1 - share_of_network) ** (blocks_per_day * 365 * 5)
    solo_expected_blocks_per_year = share_of_network * blocks_per_day * 365
    solo_expected_time_to_block_days = 1.0 / (share_of_network * blocks_per_day)
    return {
        "solo_p_day": solo_p_day,
        "solo_p_year": solo_p_year,
        "solo_p_5year": solo_p_5year,
        "solo_expected_blocks_per_year": solo_expected_blocks_per_year,
        "solo_expected_time_to_block_days": solo_expected_time_to_block_days,
    }


def compute_lender_profitability(
    ths: float,
    market_btc_per_th_day: float,
    power_cost_usd_per_day: float = 0.0,
    pool_net_btc_per_day: float = 0.0,
    btc_usd: float = 0.0,
) -> dict:
    """Scenario D — rent OUT your own hashrate vs mining directly.

    Revenue from leasing your rigs = hashrate(TH/s) × market rental rate
    (BTC/TH/day). The locador pays electricity in BOTH scenarios (the rigs
    run either way), so the power cost CANCELS in the lease-vs-mine
    comparison:
        lease net = revenue − power
        mine  net = mining income − power
        vs_mining = lease net − mine net = revenue − mining income
    The comparison therefore reduces to revenue vs mining income — power is
    subtracted on both sides only to expose the per-scenario net figures.

    Returns a dict with keys:
      - lender_net_btc_per_day        : lease revenue − power cost (BTC)
      - lender_net_usd_per_day        : same in USD
      - lender_revenue_btc_per_day    : gross lease revenue (BTC)
      - lender_power_cost_usd_per_day
      - lender_mine_net_usd_per_day   : mining income − power cost (USD)
      - lender_vs_mining_usd_per_day  : lease net − mine net (positive → lease)
      - lender_recommendation         : 'lease' | 'mine' | 'equal' | 'insufficient'
      - lender_breakeven_btc_per_th_day : market rate where lease == mine
      - lender_breakeven_usd_per_th_day : same in USD

    Never raises. When inputs are missing/zero the recommendation is
    'insufficient' and money fields are None.
    """
    out = {
        "lender_net_btc_per_day": None,
        "lender_net_usd_per_day": None,
        "lender_revenue_btc_per_day": None,
        "lender_power_cost_usd_per_day": None,
        "lender_mine_net_usd_per_day": None,
        "lender_vs_mining_usd_per_day": None,
        "lender_recommendation": "insufficient",
        "lender_breakeven_btc_per_th_day": None,
        "lender_breakeven_usd_per_th_day": None,
    }
    try:
        ths = float(ths or 0)
        rate = float(market_btc_per_th_day or 0)
        power_usd = float(power_cost_usd_per_day or 0)
        mining_btc = float(pool_net_btc_per_day or 0)
        price = float(btc_usd or 0)
        if ths <= 0 or rate <= 0:
            return out

        revenue_btc = ths * rate
        power_btc = power_usd / price if price > 0 and power_usd > 0 else 0.0
        net_btc = revenue_btc - power_btc  # lease net
        mine_btc = mining_btc - power_btc  # mine net (same power)
        net_usd = net_btc * price if price > 0 else None
        mine_usd = mine_btc * price if price > 0 else None

        out.update(
            {
                "lender_net_btc_per_day": round(net_btc, 10),
                "lender_revenue_btc_per_day": round(revenue_btc, 10),
                "lender_power_cost_usd_per_day": round(power_usd, 4),
            }
        )
        if net_usd is not None and mine_usd is not None:
            out["lender_net_usd_per_day"] = round(net_usd, 4)
            out["lender_mine_net_usd_per_day"] = round(mine_usd, 4)
            out["lender_vs_mining_usd_per_day"] = round(net_usd - mine_usd, 4)
            if abs(net_usd - mine_usd) < 0.005:
                out["lender_recommendation"] = "equal"
            elif net_usd > mine_usd:
                out["lender_recommendation"] = "lease"
            else:
                out["lender_recommendation"] = "mine"

        # Market rate where lease net == mine net. Power cancels (both sides
        # pay it), so breakeven rate = mining income / ths.
        breakeven_btc = mining_btc / ths if ths > 0 else None
        if breakeven_btc is not None:
            out["lender_breakeven_btc_per_th_day"] = round(breakeven_btc, 12)
            if price > 0:
                out["lender_breakeven_usd_per_th_day"] = round(breakeven_btc * price, 4)
        return out
    except Exception:
        return out


def compute_pool_rental_break_even(
    ths: float,
    pool_net_btc_per_day: float,
    btc_usd: float = 0.0,
    cost_mode: str = "none",
    rental_usd_per_th_day: float = 0.0,
    power_watts: float = 0.0,
    power_kwh_usd: float = 0.0,
) -> dict:
    """Pool/rental cost model + break-even math — single source of truth for
    app.py._do_poll() profitability block.

    Cost model (cost_mode):
      - 'rental': daily cost = hashrate(TH/s) × rental rate ($/TH/day)
      - 'power':  daily cost = (watts / 1000) × 24h × $/kWh
      - 'none' (default): no cost
    Only ONE branch applies (the elif), mirroring the original inline logic.

    Break-even:
      break_even_rental_usd_per_th_day = (pool_net_btc_per_day × BTC price) / ths
        → the rental rate at which the pool income equals the rental cost.
        Only computed when cost_mode == 'rental' AND a BTC price exists.
      breakeven_cost_per_th_day = same figure, always computed when a BTC
        price exists and ths > 0.

    Returns a dict with keys: rental_cost_per_day, power_cost_per_day,
    cost_per_day, break_even_rental_usd_per_th_day, breakeven_cost_per_th_day.
    Never raises. When inputs are missing/zero the break-even fields are None.
    """
    out = {
        "rental_cost_per_day": 0.0,
        "power_cost_per_day": 0.0,
        "cost_per_day": 0.0,
        "break_even_rental_usd_per_th_day": None,
        "breakeven_cost_per_th_day": None,
    }
    try:
        ths = float(ths or 0)
        net_btc = float(pool_net_btc_per_day or 0)
        price = float(btc_usd or 0)
        mode = str(cost_mode or "none")

        # NOTE: deliberately NOT rounded here — the original inline math in
        # app.py kept these raw and only rounded at each dict usage site
        # (cost_per_day_usd, rental_net_usd_per_day, net_btc_per_day_rental,
        # fiat_*). Rounding early would double-round and drift the payload.
        if mode == "rental":
            out["rental_cost_per_day"] = ths * float(rental_usd_per_th_day or 0)
        elif mode == "power":
            watts = float(power_watts or 0)
            kwh_rate = float(power_kwh_usd or 0)
            out["power_cost_per_day"] = (watts / 1000.0) * 24.0 * kwh_rate
        out["cost_per_day"] = out["rental_cost_per_day"] + out["power_cost_per_day"]

        if price > 0 and ths > 0:
            be = (net_btc * price) / max(ths, 1e-12)
            out["breakeven_cost_per_th_day"] = round(be, 4)
            if mode == "rental":
                out["break_even_rental_usd_per_th_day"] = round(be, 4)
        return out
    except Exception:
        return out


def build_decision_matrix(
    pool_net_usd_per_day=None,
    solo_expected_time_days=None,
    solo_p_year_pct=None,
    lender_net_usd_per_day=None,
    lender_recommendation=None,
    breakeven_cost_per_th_day=None,
) -> dict:
    """P0-2 // Unified solo vs pool vs lease comparison for the Decision Matrix.

    Pure aggregation over the profitability payload already computed by
    app.py._do_poll() — no network, no DB, never raises. Answers the capital
    allocation question in one glance: "where does my hashrate yield most?".

    Returns:
      - rows: pool / solo / lease dicts with only the fields the panel needs
      - best_option: 'pool' | 'lease' | 'solo' | 'insufficient'
      - recommendation: human string
      - breakeven_cost_per_th_day (pass-through)

    Deterministic tie-break: pool vs lease are both deterministic USD/day
    figures, so the higher wins; solo is probabilistic (expected time) and is
    only crowned when neither pool nor lease has a usable number.
    """

    def _num(v):
        try:
            f = float(v)
            return f if (f == f and f != float("inf") and f != float("-inf")) else None
        except (TypeError, ValueError):
            return None

    pool_usd = _num(pool_net_usd_per_day)
    lease_usd = _num(lender_net_usd_per_day)
    exp_days = _num(solo_expected_time_days)
    p_year = _num(solo_p_year_pct)
    be = _num(breakeven_cost_per_th_day)
    rec = str(lender_recommendation or "").lower()

    rows = {
        "pool": {
            "net_usd_per_day": pool_usd,
            "net_btc_per_day": None,  # filled by caller when available
        },
        "solo": {
            "expected_time_days": round(exp_days, 1) if exp_days else None,
            "p_year_pct": round(p_year, 4) if p_year is not None else None,
        },
        "lease": {
            "net_usd_per_day": lease_usd,
            "recommendation": rec or None,
        },
    }

    if pool_usd is not None and lease_usd is not None:
        best = "pool" if pool_usd >= lease_usd else "lease"
    elif pool_usd is not None:
        best = "pool"
    elif lease_usd is not None:
        best = "lease"
    elif exp_days is not None:
        best = "solo"
    else:
        best = "insufficient"

    if best == "pool":
        recommendation = "Pool mining nets the highest deterministic USD/day."
    elif best == "lease":
        recommendation = "Renting out hashrate (lease) nets more than pool mining."
    elif best == "solo":
        recommendation = (
            "Only probabilistic data available — expected %.0f days to a block."
            % exp_days
        )
    else:
        recommendation = "Not enough data to compare strategies yet."

    return {
        "rows": rows,
        "best_option": best,
        "recommendation": recommendation,
        "breakeven_cost_per_th_day": be,
    }


def affiliate_map_from_env() -> dict:
    """Parse HASH_MARKET_AFFILIATE_URLS (JSON {provider: url}) into a dict.

    Off-by-default: missing/invalid env → {}. The operator configures REAL
    affiliate links; the app never fabricates one. Keys are lowercased and
    only http(s) URLs are kept.
    """
    raw = os.environ.get("HASH_MARKET_AFFILIATE_URLS", "") or ""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        key = str(k).strip().lower()
        val = str(v).strip()
        if key and val.startswith(("http://", "https://")):
            out[key] = val
    return out


def resolve_affiliate_link(offers, affiliate_map=None) -> dict | None:
    """P0-3 // One-click affiliate link for the best buyable lease offer.

    Pure + honest: only offers whose provider is in the operator's affiliate
    map are eligible (real configured URLs). Prefers non-estimated (real
    marketplace) quotes; among the eligible pool picks the cheapest
    price_per_th_day. Returns {provider, url, price_per_th_day} or None — a
    missing/invalid entry never raises and never fabricates a link.
    """
    if not offers:
        return None
    mapping = dict(affiliate_map or {})
    if not mapping:
        return None
    eligible = []
    for o in offers:
        if not isinstance(o, dict):
            continue
        prov = str(o.get("provider") or o.get("source") or "").strip().lower()
        url = mapping.get(prov)
        if not url:
            continue
        try:
            price = float(o.get("price_per_th_day"))
        except (TypeError, ValueError):
            continue
        eligible.append(
            {
                "provider": prov,
                "url": url,
                "price_per_th_day": price,
                "estimated": bool(o.get("estimated")),
            }
        )
    if not eligible:
        return None
    real = [e for e in eligible if not e["estimated"]]
    pool = real or eligible
    best = min(pool, key=lambda e: e["price_per_th_day"])
    return {
        "provider": best["provider"],
        "url": best["url"],
        "price_per_th_day": best["price_per_th_day"],
    }


def attach_affiliate(snapshot: dict, offers, affiliate_map=None) -> None:
    """P0-3 // Attach the one-click affiliate link to a snapshot in place.

    Sets snapshot['market_data']['affiliate'] and, when a link is available,
    mirrors it into snapshot['profitability']['decision_matrix']['affiliate']
    so the Decision Matrix panel is self-contained. Honest: only URLs from
    the operator's affiliate_map; never fabricates. Missing sections no-op.
    """
    aff = resolve_affiliate_link(offers, affiliate_map)
    md = snapshot.get("market_data")
    if isinstance(md, dict):
        md["affiliate"] = aff
    dm = (snapshot.get("profitability") or {}).get("decision_matrix")
    if isinstance(dm, dict) and aff:
        dm["affiliate"] = aff


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  P0-5 // Wallet account rank enrichment (leaderboard authoritative)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def enrich_account_ranks(account, leaderboard_entry):
    """P0-5 // Fill diff/loyalty/combined ranks on the account from the pool
    leaderboard when the account API omits them (measured: it always does).

    Mutates a copy and returns it (pure — the caller may pass the live dict
    and get a new one back). Leaderboard is authoritative: values are copied
    only when the account lacks its own. block_count is backfilled from
    leaderboard.total_blocks so the frontend C3 fallback has real data.

    Returns the (possibly enriched) account; None in → None out. Never raises.
    """
    if not isinstance(account, dict):
        return account
    if not isinstance(leaderboard_entry, dict):
        return account
    out = dict(account)
    meta = dict(out.get("metadata") or {})
    le = leaderboard_entry
    if not out.get("diff_rank") and not out.get("diffRank"):
        dr = le.get("diff_rank") or le.get("diffRank") or le.get("rankDifficulty")
        if dr is not None:
            out["diff_rank"] = dr
    if not out.get("loyalty_rank") and not out.get("loyaltyRank"):
        lr = le.get("loyalty_rank") or le.get("loyaltyRank")
        if lr is not None:
            out["loyalty_rank"] = lr
    if not out.get("combined_score") and not out.get("combinedScore"):
        cs = le.get("combined_score") or le.get("combinedScore")
        if cs is not None:
            out["combined_score"] = cs
    if not meta.get("block_count") and le.get("total_blocks") is not None:
        meta["block_count"] = le["total_blocks"]
    if meta:
        out["metadata"] = meta
    return out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  P0-3 // Command Center — contextual action cards
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Severity order used to rank Command Center cards (highest wins).
_CC_SEVERITY_ORDER = {"crit": 0, "gold": 1, "warn": 2, "info": 3}
CC_MAX_ACTIONS = 3

# P1 Auto-Pilot advisory thresholds — REAL data gating (never fabricates).
AP_HASHRATE_DROP_RATIO = 0.70  # fire when current < 70% of 7d peak
AP_TEMP_HIGH_C = 75.0  # fire when a fleet device runs ≥ 75°C
AP_PEAK_WINDOW_S = 7 * 86400  # 7-day window for the hashrate peak


def build_command_center(snapshot: Optional[dict] = None) -> list:
    """P0-3 // Build up to CC_MAX_ACTIONS contextual action cards.

    The Command Center is the advisory read-only layer that precedes the
    Auto-Pilot Big Bet: instead of raw metrics, it surfaces the ONE action to
    take right now (check the fleet, see the probability, buy hashrate) as a
    decision card — each carrying a navigation target so a single click takes
    the operator to the right module.

    Pure + honest: reads ONLY data already present in the snapshot (no
    network, no DB, never raises). A card is emitted only when a real
    condition holds — never fabricated advice. When nothing fires it returns
    [] and the panel renders its quiet state.

    Card shape (frontend contract):
      {
        "id": str,            // stable id (dedup key for tests/UI)
        "severity": str,      // crit | gold | warn | info
        "title": str,
        "message": str,
        "action": str,        // CTA label, e.g. "VER FLEET"
        "target": str,        // module to navigate to: fleet|probability|market
        "panel": str,         // optional panel id to scroll into view
        "url": str | None,    // optional external link (affiliate buy)
      }

    Rule set (all fed by REAL snapshot data):
      1. worker_offline      (crit) — snapshot.worker is missing
      2. fleet_attention     (warn) — axe_fleet devices OFFLINE/WARNING
      3. proximity_streak    (gold) — proximity.hot_streak
      4. proximity_milestone (info) — pct_of_network_cur >= 1.0%
      5. capital_lease       (info) — decision_matrix.best_option == 'lease'
      6. negative_operation  (warn) — pool_net_usd_per_day < 0
      7. affiliate_buy       (info) — market_data.affiliate.url configured

    P1 Auto-Pilot advisory rules (phased start of the Big Bet — read-only,
    fed by the real `auto_pilot` snapshot block injected in app.py):
      8. hashrate_drop       (gold) — current hashrate < 70% of the real
         7-day peak (proximity_history MAX, window AP_PEAK_WINDOW_S)
      9. temp_high           (warn) — fleet device temperature >= AP_TEMP_HIGH_C
      10. automation_ready   (info) — AutomationEngine.preview_rules()
          reports a rule that WOULD fire right now (no execution)

    Cards are ranked by severity (crit > gold > warn > info), then emitted in
    rule order, capped at CC_MAX_ACTIONS.
    """

    def _num(v):
        try:
            f = float(v)
            return f if (f == f and f != float("inf") and f != float("-inf")) else None
        except (TypeError, ValueError):
            return None

    snap = snapshot if isinstance(snapshot, dict) else {}
    cards: list = []

    def _add(card: dict):
        cards.append(card)

    # ── 1. Worker offline (crit) ──
    # Honest gate: a worker-less snapshot is normal on a cold boot / before
    # the first poll (no wallet connected yet, ts == 0 — the pool/network
    # dicts exist but hold only None). Only once a poll has actually run
    # (ts > 0) and the worker is missing is that a real "offline" condition.
    worker = snap.get("worker")
    _has_polled = bool(_num(snap.get("ts")))
    if not worker and _has_polled:
        _add(
            {
                "id": "worker_offline",
                "severity": "crit",
                "title": "Worker offline",
                "message": "Nenhum worker ativo na pool — verifique a conexão do minerador.",
                "action": "VER FLEET",
                "target": "fleet",
                "panel": "axe-fleet-panel",
                "url": None,
            }
        )

    # ── 2. Fleet device attention (warn) ──
    fleet = snap.get("axe_fleet") or []
    if isinstance(fleet, list):
        problem_devices = [
            d
            for d in fleet
            if isinstance(d, dict)
            and (d.get("status") or "").upper() in ("OFFLINE", "WARNING")
        ]
        if problem_devices:
            _add(
                {
                    "id": "fleet_attention",
                    "severity": "warn",
                    "title": f"{len(problem_devices)} minerador(es) precisam de atenção",
                    "message": "Há device(s) OFFLINE ou WARNING na frota — inspecione antes de prosseguir.",
                    "action": "VER FLEET",
                    "target": "fleet",
                    "panel": "axe-fleet-panel",
                    "url": None,
                }
            )

    # ── 3. Proximity hot streak (gold) ──
    prox = snap.get("proximity") or {}
    if isinstance(prox, dict) and prox.get("hot_streak"):
        trend = _num(prox.get("trend_1h_pct"))
        _add(
            {
                "id": "proximity_streak",
                "severity": "gold",
                "title": "HOT STREAK na proximidade",
                "message": (
                    f"Best-diff subiu {trend:.1f}% em 1h — a proximidade de bloco está acelerando."
                    if trend is not None
                    else "Best-diff subindo — a proximidade de bloco está acelerando."
                ),
                "action": "VER PROBABILITY",
                "target": "probability",
                "panel": "proximity-panel",
                "url": None,
            }
        )
    elif isinstance(prox, dict):
        # ── 4. Proximity milestone reached (info) ──
        pct = _num(prox.get("milestone_cur_pct"))
        if pct is not None and pct >= 1.0:
            _add(
                {
                    "id": "proximity_milestone",
                    "severity": "info",
                    "title": "Proximidade de bloco relevante",
                    "message": f"Você está a {pct:.2f}% da dificuldade da rede — cada share tem valor real.",
                    "action": "VER PROBABILITY",
                    "target": "probability",
                    "panel": "proximity-panel",
                    "url": None,
                }
            )

    # ── 5. Capital allocation — lease wins (info) ──
    dm = (snap.get("profitability") or {}).get("decision_matrix") or {}
    if isinstance(dm, dict) and dm.get("best_option") == "lease":
        _add(
            {
                "id": "capital_lease",
                "severity": "info",
                "title": "Lease rende mais que pool",
                "message": "A Decision Matrix aponta o aluguel de hashrate como a melhor alocação de capital.",
                "action": "VER MARKET",
                "target": "market",
                "panel": "decision-matrix-panel",
                "url": None,
            }
        )

    # ── 6. Negative operation (warn) ──
    profit = snap.get("profitability") or {}
    pool_net = _num(profit.get("pool_net_usd_per_day"))
    if pool_net is not None and pool_net < 0:
        _add(
            {
                "id": "negative_operation",
                "severity": "warn",
                "title": "Operação no vermelho",
                "message": (
                    f"Custo diário supera a receita do pool (net ${abs(pool_net):.2f}/dia) — "
                    "revise energia, pool ou alugue hashrate."
                ),
                "action": "VER MARKET",
                "target": "market",
                "panel": "decision-matrix-panel",
                "url": None,
            }
        )

    # ── 7. Affiliate buy CTA (info) ──
    md = snap.get("market_data") or {}
    aff = (md.get("affiliate") or {}) if isinstance(md, dict) else {}
    if isinstance(aff, dict) and aff.get("url"):
        _add(
            {
                "id": "affiliate_buy",
                "severity": "info",
                "title": "Comprar hashrate em 1 clique",
                "message": (
                    f"Melhor oferta afiliada: {str(aff.get('provider') or 'hashrate').upper()} "
                    "— link direto para o marketplace."
                ),
                "action": "COMPRAR HASHRATE",
                "target": "market",
                "panel": "market-panel",
                "url": aff.get("url"),
            }
        )

    # ── 8. P1 Auto-Pilot: hashrate below its real 7-day peak (gold) ──
    # Fed by snap["auto_pilot"]["peak_hashrate_7d"] — the true MAX worker
    # hashrate observed over the last 7 days (from proximity_history, real
    # data, injected by app.py). When the current hashrate has dropped below
    # 70% of that peak, the operator loses real revenue: surface a reset /
    # inspect card instead of a raw metric.
    ap = snap.get("auto_pilot") if isinstance(snap.get("auto_pilot"), dict) else {}
    peak_7d = _num(ap.get("peak_hashrate_7d"))
    cur_hr = _num(worker.get("hashrate") if isinstance(worker, dict) else None)
    if peak_7d and cur_hr and cur_hr > 0 and cur_hr < peak_7d * AP_HASHRATE_DROP_RATIO:
        drop_pct = (1 - cur_hr / peak_7d) * 100
        _add(
            {
                "id": "hashrate_drop",
                "severity": "gold",
                "title": "HASHRATE DROP — abaixo do pico de 7d",
                "message": (
                    f"Hashrate atual é {drop_pct:.0f}% menor que o pico da semana "
                    "(reset do device ou rede local podem recuperá-lo)."
                ),
                "action": "VER FLEET",
                "target": "fleet",
                "panel": "axe-fleet-panel",
                "url": None,
            }
        )

    # ── 9. P1 Auto-Pilot: fleet device running hot (warn) ──
    if isinstance(fleet, list):
        hot_devices = [
            d
            for d in fleet
            if isinstance(d, dict)
            and _num(d.get("temperature")) is not None
            and _num(d.get("temperature")) >= AP_TEMP_HIGH_C
        ]
        if hot_devices:
            hot = hot_devices[0]
            hot_name = str(
                hot.get("name") or hot.get("device_id") or hot.get("id") or "device"
            )
            _add(
                {
                    "id": "temp_high",
                    "severity": "warn",
                    "title": f"{hot_name} a {_num(hot.get('temperature')):.0f}°C",
                    "message": "Temperatura acima do limite térmico — reduza overclock, melhore o airflow ou pausa o device antes de dano.",
                    "action": "VER FLEET",
                    "target": "fleet",
                    "panel": "axe-fleet-panel",
                    "url": None,
                }
            )

    # ── 10. P1 Auto-Pilot: automation rule ready to fire (info) ──
    # The Big Bet merge with Automations — read-only advisory preview of what
    # a rule WOULD do right now (AutomationEngine.preview_rules, no execution
    # by design). The operator sees the pending trigger and can confirm or
    # disarm the rule in the Automations module.
    ap_preview = ap.get("automation_preview") or []
    if isinstance(ap_preview, list) and ap_preview:
        first = ap_preview[0] if isinstance(ap_preview[0], dict) else {}
        rule_name = str(first.get("rule_name") or "regra")
        dev_id = str(first.get("device_id") or "")
        action = str(first.get("action_command") or "ação")
        _add(
            {
                "id": "automation_ready",
                "severity": "info",
                "title": "Auto-Pilot: automação pronta",
                "message": (
                    f"Regra «{rule_name}» dispararia agora: {action}"
                    + (f" em {dev_id}" if dev_id else "")
                    + "."
                ),
                "action": "VER AUTOMATIONS",
                "target": "automations",
                "panel": "ai-operator-panel",
                "url": None,
            }
        )

    # Rank by severity (crit > gold > warn > info), stable by rule order.
    cards.sort(key=lambda c: _CC_SEVERITY_ORDER.get(c.get("severity", "info"), 99))
    return cards[:CC_MAX_ACTIONS]


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
