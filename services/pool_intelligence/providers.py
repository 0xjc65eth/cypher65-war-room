"""Chain-aware registry of SHA-256 mining pools, and provider detection.

Two facts drive this module:

1. Every pool figure in the dashboard used to come from exactly ONE host
   (``parasite.space/api``). A worker pointed at any other pool rendered zeros
   — not because the pool was incompatible, but because no other response
   shape was ever parsed.
2. The hardware already knows which pool it is on: every ASIC reports its
   ``stratumURL``/``stratumUser``. That is the cheapest and most reliable
   signal for "which pool is this worker on", and it was being collected and
   then thrown away.

So the registry answers two questions:

* :func:`detect_provider` — which provider is this stratum endpoint?
* :func:`stats_url_for` — where do we fetch its per-worker statistics, *when*
  the provider publishes a public API?

Providers that publish no public per-worker API are still recognised (label,
chain, kind). Their numbers come from the ASIC itself: the miner is the source
of truth for its own hashrate, best share and share counters, so "no API" must
degrade to *hardware data*, never to silent zeros.

Nothing here performs network I/O and nothing here is a guess: a provider is
only given a ``stats_url`` when the endpoint is the provider's own documented
API. Every other provider is ``stratum_only``.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

__all__ = [
    "Chain",
    "PoolDetection",
    "PoolKind",
    "PoolProvider",
    "PROVIDERS",
    "detect_provider",
    "provider_by_id",
    "stats_api_providers",
    "stats_url_for",
    "stratum_host",
]

# A stratum URL may arrive with a scheme the endpoint parser does not know
# (``stratum2+tcp://``, ``tcp://``) or with a bare ``host:port``. We only need
# the host, so we strip rather than validate — validation of what we are going
# to *connect* to stays in ``.endpoint`` / ``.resolver``.
_SCHEME_SEPARATOR = "://"


class Chain(str, Enum):
    """The SHA-256 chain a pool serves."""

    BTC = "btc"
    BSV = "bsv"


class PoolKind(str, Enum):
    """Solo pools pay the whole block reward to one address; pools share it."""

    SOLO = "solo"
    POOL = "pool"
    BOTH = "both"


@dataclass(frozen=True)
class PoolProvider:
    """One known SHA-256 pool.

    ``host_patterns`` are matched against the *stratum host* — exact match, or
    a subdomain of the pattern — so ``eu.stratum.braiins.com`` matches
    ``braiins.com`` without matching an unrelated ``notbraiins.com``.

    ``stats_kind`` names the parser in ``.stats``. It is None for providers
    with no public per-worker API, which is the majority: the registry still
    recognises them, and the numbers come from the ASIC.
    """

    provider_id: str
    label: str
    chain: Chain
    kind: PoolKind
    host_patterns: tuple[str, ...]
    stats_kind: str | None = None
    stats_url: str | None = None
    docs: str = ""

    @property
    def has_stats_api(self) -> bool:
        return bool(self.stats_kind and self.stats_url)


def _p(
    provider_id: str,
    label: str,
    chain: Chain,
    kind: PoolKind,
    *hosts: str,
    stats_kind: str | None = None,
    stats_url: str | None = None,
    docs: str = "",
) -> PoolProvider:
    return PoolProvider(
        provider_id=provider_id,
        label=label,
        chain=chain,
        kind=kind,
        host_patterns=tuple(hosts),
        stats_kind=stats_kind,
        stats_url=stats_url,
        docs=docs,
    )


# ── Registry ────────────────────────────────────────────────────────────
# Verified public per-worker stats APIs are marked ``stats_kind``. Everything
# else is deliberately ``stratum_only``: recognised, labelled, chain-tagged,
# and fed by the ASIC. Adding a real API later is a one-line change here.
PROVIDERS: tuple[PoolProvider, ...] = (
    # ── Bitcoin · solo ──────────────────────────────────────────────
    # Fleet audit (Issue #627): atlaspool verified by LIVE passive Stratum
    # V1 probe — DNS resolves for solo.atlaspool.io and :3333 answered
    # mining.subscribe with a valid notify subscription (no authorize, no
    # share submission). Its web/docs presence is NOT verifiable from here
    # (atlaspool.com/.org are swimming-pool companies; aggregators do not
    # list it), so it stays stratum_only with the evidence in the docs field.
    _p(
        "atlaspool",
        "AtlasPool",
        Chain.BTC,
        PoolKind.SOLO,
        "solo.atlaspool.io",
        "atlaspool.io",
        docs="stratum solo.atlaspool.io:3333 (TCP verified 2026-09-17, mining.subscribe OK; official web presence unverified)",
    ),
    _p(
        "parasite",
        "Parasite Pool",
        Chain.BTC,
        PoolKind.SOLO,
        "parasite.space",
        "parasite.pool",
        stats_kind="parasite_user",
        stats_url="https://parasite.space/api/user/{address}",
        docs="https://parasite.space",
    ),
    _p(
        "ckpool_solo",
        "CKPool (solo)",
        Chain.BTC,
        PoolKind.SOLO,
        "solo.ckpool.org",
        "raw.stats.ckpool.org",
        "stats.ckpool.org",
        stats_kind="ckpool_user",
        stats_url="https://solo.ckpool.org/users/{address}",
        docs="https://solo.ckpool.org",
    ),
    _p(
        "public_pool",
        "Public Pool",
        Chain.BTC,
        PoolKind.SOLO,
        "public-pool.io",
        "publicpool.io",
        "web.public-pool.io",
        "public-pool.com",
        stats_kind="public_pool_workers",
        stats_url="https://public-pool.io:40557/api/client/{address}",
        docs="https://web.public-pool.io",
    ),
    _p(
        "ocean",
        "OCEAN",
        Chain.BTC,
        PoolKind.POOL,
        "ocean.xyz",
        "mine.ocean.xyz",
        docs="https://ocean.xyz (per-address view is HTML, no JSON API)",
    ),
    # ── Bitcoin · pooled ────────────────────────────────────────────
    _p(
        "ckpool",
        "CKPool",
        Chain.BTC,
        PoolKind.POOL,
        "pool.ckpool.org",
        "ckpool.org",
    ),
    _p(
        "braiins_pool",
        "Braiins Pool",
        Chain.BTC,
        PoolKind.POOL,
        "braiins.com",
        "stratum.braiins.com",
        "pool.braiins.com",
    ),
    _p("antpool", "AntPool", Chain.BTC, PoolKind.POOL, "antpool.com"),
    _p("f2pool", "F2Pool", Chain.BTC, PoolKind.POOL, "f2pool.com"),
    _p(
        "viabtc",
        "ViaBTC",
        Chain.BTC,
        PoolKind.POOL,
        "viabtc.com",
        "viabtc.io",
    ),
    _p("binance_pool", "Binance Pool", Chain.BTC, PoolKind.POOL, "binance.com"),
    _p(
        "luxor",
        "Luxor",
        Chain.BTC,
        PoolKind.POOL,
        "luxor.tech",
        "luxor.xyz",
    ),
    _p("foundry_usa", "Foundry USA", Chain.BTC, PoolKind.POOL, "foundrydigital.com"),
    _p("mara_pool", "MARA Pool", Chain.BTC, PoolKind.POOL, "mara.com", "mara.tech"),
    _p("sbi_crypto", "SBI Crypto", Chain.BTC, PoolKind.POOL, "sbicrypto.com"),
    _p("spiderpool", "SpiderPool", Chain.BTC, PoolKind.POOL, "spiderpool.com"),
    _p("emcd", "EMCD", Chain.BTC, PoolKind.POOL, "emcd.io"),
    _p("poolin", "Poolin", Chain.BTC, PoolKind.POOL, "poolin.com"),
    _p("btc_com", "BTC.com", Chain.BTC, PoolKind.POOL, "btc.com"),
    _p("kano", "Kano", Chain.BTC, PoolKind.POOL, "kano.is"),
    _p(
        "nicehash",
        "NiceHash",
        Chain.BTC,
        PoolKind.POOL,
        "nicehash.com",
    ),
    _p("sigmapool", "Sigmapool", Chain.BTC, PoolKind.POOL, "sigmapool.com"),
    _p("novablock", "NovaBlock", Chain.BTC, PoolKind.POOL, "novablock.io"),
    _p("whitepool", "WhitePool", Chain.BTC, PoolKind.POOL, "whitepool.com"),
    _p("rawpool", "Rawpool", Chain.BTC, PoolKind.POOL, "rawpool.com"),
    _p("1thash", "1THash", Chain.BTC, PoolKind.POOL, "1thash.io"),
    _p("slushpool", "Slush Pool (legacy)", Chain.BTC, PoolKind.POOL, "slushpool.com"),
    # ── Fleet audit additions (Issue #627) — stratum_only until each pool's
    # own stats API is verified from official documentation ──
    _p(
        "braiins_solo",
        "Braiins Solo",
        Chain.BTC,
        PoolKind.SOLO,
        "solo.braiins.com",
        docs="Braiins solo product family; endpoint unverified (braiins.com/pool/solo 404 at audit time) — flagged stratum_only",
    ),
    _p(
        "solohash",
        "SoloHash",
        Chain.BTC,
        PoolKind.SOLO,
        "solohash.io",
        docs="solohash.io is live but serves educational content only (2026-09-17); stratum endpoint NOT verified — recognition may need a custom entry",
    ),
    _p(
        "satoshi_radio",
        "Satoshi Radio Pool",
        Chain.BTC,
        PoolKind.SOLO,
        "satoshiradio.xyz",
        docs="satoshiradio.xyz does not resolve DNS at audit time (2026-09-17) — kept for historic telemetry labelling",
    ),
    # ── Bitcoin SV ──────────────────────────────────────────────────
    # ckpool ships a BSV build, so the same stats adapter covers it — the
    # stats host is derived from the stratum host (see stats_url_for), which
    # is what keeps this list from having to duplicate every ckpool endpoint.
    _p(
        "ckpool_bsv_solo",
        "CKPool BSV (solo)",
        Chain.BSV,
        PoolKind.SOLO,
        "solo.bsv.ckpool.org",
        "bsv.ckpool.org",
        stats_kind="ckpool_user",
        stats_url="https://solo.bsv.ckpool.org/users/{address}",
        docs="https://solo.bsv.ckpool.org",
    ),
    _p(
        "gorillapool",
        "GorillaPool",
        Chain.BSV,
        PoolKind.POOL,
        "gorillapool.io",
        "gorillapool.com",
    ),
    _p("taal", "TAAL", Chain.BSV, PoolKind.POOL, "taal.com"),
    _p("antpool_bsv", "AntPool (BSV)", Chain.BSV, PoolKind.POOL, "bsv.antpool.com"),
    _p("viabtc_bsv", "ViaBTC (BSV)", Chain.BSV, PoolKind.POOL, "bsv.viabtc.com"),
    _p("sbi_bsv", "SBI Crypto (BSV)", Chain.BSV, PoolKind.POOL, "bsv.sbicrypto.com"),
)


_BY_ID = {provider.provider_id: provider for provider in PROVIDERS}


def provider_by_id(provider_id: str) -> PoolProvider | None:
    """Return the registered provider, or None for an unknown id."""
    return _BY_ID.get(str(provider_id or "").strip().lower())


def stats_api_providers() -> tuple[PoolProvider, ...]:
    """Providers with a public per-worker API, in registry (priority) order.

    The order is meaningful: :mod:`services.pool_intelligence.stats` probes
    these in sequence when no ASIC has told us which pool is in use.
    """
    return tuple(provider for provider in PROVIDERS if provider.has_stats_api)


def _split_host_port(value: str) -> str:
    """Strip userinfo and an optional ``:port`` from a ``host[:port]`` string.

    IPv6 literals keep their brackets (``[::1]:3333`` → ``[::1]``) so a colon
    inside the address is never mistaken for the port separator.
    """
    host = value.rsplit("@", 1)[-1]
    if host.startswith("["):
        closing = host.find("]")
        if closing != -1:
            return host[: closing + 1]
        return host
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def stratum_host(value: object) -> str:
    """Extract the stratum host from whatever the firmware reported.

    Accepts ``stratum+tcp://host:3333``, ``stratum2+tcp://host``, ``tcp://``,
    ``http(s)://``, a bare ``host:port`` and a bare ``host``. Returns ``""``
    when there is nothing usable. This is deliberately tolerant: real firmware
    reports every one of these shapes, and a strict parser would drop the
    signal we need most. It never resolves DNS and never validates the
    destination — that stays in ``.resolver``/``.policy``.
    """
    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw:
        return ""
    if _SCHEME_SEPARATOR in raw:
        raw = raw.split(_SCHEME_SEPARATOR, 1)[1]
    # Drop any path, query or fragment (some firmwares append a worker name).
    for separator in ("/", "?", "#"):
        if separator in raw:
            raw = raw.split(separator, 1)[0]
    host = _split_host_port(raw).strip().rstrip(".").lower()
    return host


def _matches(host: str, pattern: str) -> bool:
    """Exact host, or a subdomain of the pattern.

    Guards the ``notbraiins.com`` case: a suffix check must land on a label
    boundary, so ``evil-braiins.com`` does not match ``braiins.com``.
    """
    return host == pattern or host.endswith("." + pattern)


def detect_provider(
    stratum_endpoint: object = "",
    *,
    address: str = "",
    asic_host: object = "",
) -> "PoolDetection":
    """Identify the provider behind a stratum endpoint.

    ``stratum_endpoint`` is normally the ASIC-reported ``stratumURL`` (or the
    operator's own input). ``asic_host`` is accepted as a second, lower
    priority hint so a caller that only has a bare host can still call this.

    When nothing matches, the result is an honest ``unknown`` carrying the raw
    host — never an invented provider id.
    """
    raw = ""
    for candidate in (stratum_endpoint, asic_host):
        text = candidate if isinstance(candidate, str) else ""
        if text.strip():
            raw = text
            break
    host = stratum_host(raw)

    # Longest matching pattern wins. This matters because the registry holds
    # both a generic and a specialised entry for the same vendor —
    # ``ckpool.org`` (BTC pooled) and ``solo.bsv.ckpool.org`` (BSV solo). Both
    # match that host by suffix, and returning whichever is declared first
    # would tag a BSV worker as BTC.
    best: tuple[int, PoolProvider, str] | None = None
    for provider in PROVIDERS:
        for pattern in provider.host_patterns:
            if _matches(host, pattern) and (best is None or len(pattern) > best[0]):
                best = (len(pattern), provider, pattern)
    if best is not None:
        _, provider, pattern = best
        return PoolDetection(
            provider=provider,
            host=host,
            matched_pattern=pattern,
            chain=provider.chain,
            chain_source="provider_registry",
            address=str(address or "").strip(),
        )

    # Unregistered endpoint: still report the chain we can actually justify.
    chain, chain_source = _infer_chain(host)
    return PoolDetection(
        provider=None,
        host=host,
        matched_pattern="",
        chain=chain,
        chain_source=chain_source,
        address=str(address or "").strip(),
    )


def _infer_chain(host: str) -> tuple[Chain | None, str]:
    """Best-effort chain for an unregistered host.

    The only evidence available is the hostname itself. BSV operators name
    their endpoints with an explicit ``bsv`` label far more often than not, so
    we look for it as a whole label. We deliberately do NOT guess from the
    address: BSV and BTC share the base58 ``1…``/``3…`` formats, so an address
    cannot distinguish them, and pretending otherwise would be a fabricated
    signal. ``None`` therefore means "unknown", and the UI says so.
    """
    if not host:
        return None, "unknown"
    labels = host.split(".")
    if "bsv" in labels:
        return Chain.BSV, "host_label"
    return None, "unknown"


@dataclass(frozen=True)
class PoolDetection:
    """Result of :func:`detect_provider`.

    ``provider`` is None for an unregistered host; ``host`` is always the
    normalized stratum host we actually matched (or ``""``), so a caller can
    label the pool honestly even when the registry does not know it.
    """

    provider: PoolProvider | None
    host: str
    matched_pattern: str
    chain: Chain | None
    chain_source: str
    address: str = ""

    @property
    def provider_id(self) -> str:
        return self.provider.provider_id if self.provider else "unknown"

    @property
    def label(self) -> str:
        """Human label: the registered name, else the raw host, else unknown."""
        if self.provider:
            return self.provider.label
        return self.host or "unknown pool"

    @property
    def kind(self) -> PoolKind | None:
        return self.provider.kind if self.provider else None

    @property
    def stats_url(self) -> str | None:
        return stats_url_for(self.provider, self.address)

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "label": self.label,
            "kind": self.kind.value if self.kind else None,
            "chain": self.chain.value if self.chain else None,
            "chain_source": self.chain_source,
            "host": self.host,
            "matched_pattern": self.matched_pattern,
            "stats_url": self.stats_url,
            "has_stats_api": bool(self.provider and self.provider.has_stats_api),
            "docs": self.provider.docs if self.provider else "",
        }


def stats_url_for(provider: PoolProvider | None, address: str = "") -> str | None:
    """Build the per-worker stats URL, or None when there is no public API.

    ``{address}`` is substituted with the URL-quoted address. An empty address
    returns None rather than a URL with a hole in it: a stats request without
    an identity would return the pool's own aggregate and silently masquerade
    as the user's numbers.
    """
    if provider is None or not provider.stats_url:
        return None
    if not str(address or "").strip():
        return None
    from urllib.parse import quote

    return provider.stats_url.replace("{address}", quote(str(address).strip(), safe=""))


def known_hosts(chain: Chain | None = None) -> Iterable[str]:
    """All registered host patterns, optionally filtered by chain."""
    for provider in PROVIDERS:
        if chain is not None and provider.chain != chain:
            continue
        yield from provider.host_patterns
