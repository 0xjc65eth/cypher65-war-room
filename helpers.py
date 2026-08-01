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
#  Solo-mining probability math (single source of truth)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_solo_probabilities(share_of_network: float, blocks_per_day: float = 144.0) -> dict:
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
    solo_p_day = 1 - (1 - share_of_network) ** blocks_per_day          # P(≥1 block today)
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
        net_btc = revenue_btc - power_btc                     # lease net
        mine_btc = mining_btc - power_btc                     # mine net (same power)
        net_usd = net_btc * price if price > 0 else None
        mine_usd = mine_btc * price if price > 0 else None

        out.update({
            "lender_net_btc_per_day": round(net_btc, 10),
            "lender_revenue_btc_per_day": round(revenue_btc, 10),
            "lender_power_cost_usd_per_day": round(power_usd, 4),
        })
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
