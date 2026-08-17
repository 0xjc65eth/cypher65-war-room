"""
CYPHER65 // SLI tracker — data-completeness service-level indicators
====================================================================
Issue #206: a degradação de qualidade de dados não era mensurável (não
existia expected-vs-received em lugar nenhum). Este módulo define dois SLIs
amostrados em cada ciclo real de coleta:

  - completude_rentals : rentals processados ÷ total reportado pelo MRR
                         (superfície honesta rendered/total da Issue #200).
                         Target ≥ 99%. Amostrado em /api/rentals.
  - frescura_market    : fração de ciclos com market_data age < 5 min.
                         Target ≥ 98%. Amostrado em /api/snapshot.

Política de breach (Issue #206): quando o SLI fica ABAIXO do target por
>= 30 min consecutivos, emite log.error + dispara um sink plugável
(wired em app.py para error_tracker.record_degradation — o bucket
WARNING/degradation da Issue #202). A recuperação limpa o estado.

Sem dados não é breach: um ciclo sem `total` do MRR (conta vazia / chave
não configurada) não gera amostra — "unknown" nunca acusa degradação.

Todo o estado é in-memory (deque com janela deslizante). Nunca lança
exceção — telemetria não pode quebrar a aplicação.
"""

import logging
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional

log = logging.getLogger("cypher65.sli")

# ── Targets / janelas (Issue #206) ────────────────────────────────────
RENTALS_COMPLETUDE_TARGET = 0.99  # ≥ 99%
MARKET_FRESH_TARGET = 0.98  # ≥ 98%
MARKET_FRESH_MAX_AGE_S = 300  # market_data age < 5 min
BREACH_WINDOW_S = 1800  # alerta após 30 min abaixo do target
PERIODIC_LOG_S = 300  # cadência do log estruturado periódico (5 min)
_MAX_SAMPLES = 500

_TARGETS = {
    "completude_rentals": RENTALS_COMPLETUDE_TARGET,
    "frescura_market": MARKET_FRESH_TARGET,
}


class SLITracker:
    """In-memory rolling tracker for the two data-completeness SLIs."""

    def __init__(self) -> None:
        self._samples: Dict[str, Deque[dict]] = {
            kind: deque(maxlen=_MAX_SAMPLES) for kind in _TARGETS
        }
        self._bad_since: Dict[str, Optional[int]] = {}
        self._alerted: Dict[str, bool] = {}
        self._last_log = 0
        self._sink: Optional[Callable[[str, float, str], None]] = None

    def set_degradation_sink(
        self, fn: Optional[Callable[[str, float, str], None]]
    ) -> None:
        """Wire a degradation notifier (app.py → error_tracker)."""
        self._sink = fn

    # ── pure: completude rentals (expected vs received) ─────────────────
    @staticmethod
    def compute_rentals_completude(active, history, owner) -> Optional[float]:
        """(rendered_active + ...) ÷ (total_active + ...).

        Reuses the honest rendered/total surface from Issue #200. Returns
        None when there is no `total` at all (no MRR data → unknown, never
        a breach).
        """
        rendered = 0
        total = 0
        for src in (active, history, owner):
            src = src or {}
            rentals = src.get("rentals") or []
            rendered += int(src.get("rendered") or len(rentals))
            total += int(src.get("total") or len(rentals))
        if total <= 0:
            return None
        return min(1.0, rendered / total)  # nunca acima de 100%

    def record_completude(self, active, history, owner, now: Optional[int] = None):
        value = self.compute_rentals_completude(active, history, owner)
        if value is None:
            return None  # sem dados do MRR → sem amostra
        return self._record("completude_rentals", value, now)

    def record_market(self, updated_at, now: Optional[int] = None):
        """Uma amostra de frescura por ciclo do snapshot."""
        now = int(now if now is not None else time.time())
        ts = updated_at
        fresh = bool(ts and (now - int(ts)) < MARKET_FRESH_MAX_AGE_S)
        return self._record("frescura_market", 1.0 if fresh else 0.0, now)

    # ── core ────────────────────────────────────────────────────────────
    def _record(self, kind: str, value: float, now: Optional[int] = None) -> float:
        now = int(now if now is not None else time.time())
        self._samples[kind].append({"ts": now, "value": value})
        self._check_breach(kind, now)
        self._maybe_log_periodic(now)
        return value

    def _window_metric(self, kind: str, now: int) -> Optional[float]:
        cutoff = now - BREACH_WINDOW_S
        samples = [s for s in self._samples[kind] if s["ts"] >= cutoff]
        if not samples:
            return None
        return sum(s["value"] for s in samples) / len(samples)

    def _check_breach(self, kind: str, now: int) -> None:
        metric = self._window_metric(kind, now)
        if metric is None or metric >= _TARGETS[kind]:
            # OK (ou sem dados) → zera o relógio de breach.
            self._bad_since.pop(kind, None)
            self._alerted.pop(kind, None)
            return
        since = self._bad_since.setdefault(kind, now)
        if now - since >= BREACH_WINDOW_S and not self._alerted.get(kind):
            self._alerted[kind] = True
            msg = (
                f"[sli] {kind} abaixo do target por >= {BREACH_WINDOW_S // 60}min "
                f"({metric:.2%} < {_TARGETS[kind]:.0%})"
            )
            log.error(msg)
            if self._sink:
                try:
                    self._sink(kind, metric, msg)
                except Exception as e:  # pragma: no cover — sink nunca quebra
                    log.warning("[sli] sink falhou: %s", e)

    def _maybe_log_periodic(self, now: int) -> None:
        if now - self._last_log < PERIODIC_LOG_S:
            return
        self._last_log = now
        s = self.summary(now)
        log.info(
            "[sli] %s",
            {
                "completude_rentals": s["completude_rentals"]["value"],
                "completude_target": s["completude_rentals"]["target"],
                "completude_status": s["completude_rentals"]["status"],
                "frescura_market": s["frescura_market"]["value"],
                "frescura_target": s["frescura_market"]["target"],
                "frescura_status": s["frescura_market"]["status"],
                "window_s": s["window_s"],
                "breach": s["breach"],
            },
        )

    def summary(self, now: Optional[int] = None) -> dict:
        """Estado atual dos SLIs — exposto em /api/snapshot.health.sli."""
        now = int(now if now is not None else time.time())
        out: dict = {"window_s": BREACH_WINDOW_S, "breach": {}, "updated_at": now}
        for kind in _TARGETS:
            metric = self._window_metric(kind, now)
            if metric is None:
                status = "unknown"
            else:
                status = "ok" if metric >= _TARGETS[kind] else "below"
            out[kind] = {
                "value": None if metric is None else round(metric, 4),
                "target": _TARGETS[kind],
                "status": status,
                "samples": sum(
                    1 for s in self._samples[kind] if s["ts"] >= now - BREACH_WINDOW_S
                ),
            }
            out["breach"][kind] = self._alerted.get(kind, False)
        return out


# Singleton compartilhado por app.py (api_rentals) e routes/dashboard_routes.py
# (api_snapshot) — um único relógio de breach para o processo.
sli = SLITracker()
