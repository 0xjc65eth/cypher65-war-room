# Independent rental observations (#599)

## Trust boundary

This ledger records **destination-pool API readings** retrieved by CYPHER65,
independent of the rental marketplace's seller-reported hashrate. It does not
measure accepted shares itself, verify a seller's physical equipment, establish
a refund entitlement, or prove uninterrupted delivery. A pool may smooth or
misreport its hashrate. Parasite's raw `workerData.hashrate` follows the existing
application H/s contract; its averaging interval and measurement timestamp are
not supplied and remain `null`. Never substitute `lastSubmission` for either.

The operator declares the rental reference, contracted TH/s, and **exclusive**
destination worker. This declaration is not vendor-verified. Use a dedicated
worker ID (or exact name when no ID exists); shared workers cannot establish
per-rental delivery. CYPHER65 refuses reuse for concurrent rentals in the same
tenant. It cannot attest exclusivity across other tenants or pool accounts.
Only Parasite wallet sessions are supported in this MVP. Fleet ASIC telemetry,
account aggregates, primary-worker fallback, and marketplace averages are never
evidence sources. The rentals detail cost-per-TH·h continues to use the provider's
reported average hashrate and is labeled separately from destination-pool sample
evidence; it must not be interpreted as cost over the sampled delivery series.
Support for another pool needs its own documented adapter.

## Operator workflow (Portuguese interface)

1. Connect the destination wallet and keep its polling session active.
2. Open a rental's detail, select its observed pool worker, and explicitly enter
   contracted TH/s, minimum delivery percentage, duration, and maximum gap.
3. Declare exclusive use of the worker before saving. No implicit SLA/default
   rule is enabled. A source older than the configured gap cannot be bound.
4. Inspect the latest readings and export the CSV for a support ticket.

The collector runs with both scheduled and synchronous tenant wallet polls.
No additional upstream API requests are introduced. Collection ends when the
wallet session expires/disconnects. Cached replies keep their original network
retrieval interval and are deduplicated; out-of-order replies older than the
latest accepted observation are discarded. Repeated browser reads cannot create
points or alerts. A new rule revision cannot backfill an earlier reply.

## Rule semantics

`delivery_pct = observed_hashrate_th / operator_contract_th * 100`.
An alert requires at least two valid below-threshold observations spanning the
explicit duration. Every adjacent observation gap must be at most `max_gap_s`.
Missing values, API errors, missing/ambiguous worker matches, healthy readings,
or larger gaps reset the streak. A real zero H/s is valid; missing data is `null`.
The latest retrieval older than `max_gap_s` yields `stale`, with no current
hashrate/verdict carried forward. Equality with the threshold is healthy.
These are **consecutive sampled readings**, not proof between observations.

The active evidence response also includes `coverage`: counts over retained points
for the active rule revision (`observation_count`, finite `observed_count`, and
`missing_count`), plus the percentage of those samples with observed hashrate and
delivery. `observed_pct` is `null` when there are no points; zero hashrate is a
valid observed sample, while absent/non-finite values are not. This percentage
is sample-quality coverage only—not elapsed-time coverage, delivery uptime, or
proof of continuous hashrate. With no active configuration, the frontend says
`Não configurado` for the contract and `Sem observações` for coverage; it never
uses zero to imply a missing contract or missing telemetry.

Rule revisions reset evaluation. Alerts are durably deduplicated by tenant,
rental, revision and streak start. Observation, dedup and durable tenant alert
feed/history inserts share one transaction: a feed insert failure rolls back
the dedup, allowing the retrieval to be retried without losing the warning.
Historical alert events are not current health verdicts.
There is no automatic cancellation, trading, refund or webhook action.

## API and storage

- `GET /api/rentals/<id>/evidence?provider=mrr`: tenant-scoped sources, active
  binding, fresh server evaluation, and latest 20 points; viewer role required.
- `POST` same URL: member role; JSON `source_id`, `contract_th`, `threshold_pct`,
  `duration_s`, `max_gap_s`, `exclusive_worker: true`. Numeric fields are finite;
  source ID/durations are integers. Contract: `(0, 1e9]` TH/s; threshold `(0,100]`;
  duration `[15,86400]` s; gap `[15,min(3600,duration)]` s.
- `DELETE` same URL: member role; disables collection, preserving retained CSV.
- `GET .../evidence/export`: viewer role; all retained revisions, source URL,
  exact selector, UTC observation/collection bounds, unknown averaging window,
  quality, nullable HR, contract/rule snapshot and limitations. Formula-leading
  strings are escaped for spreadsheets. Responses use `Cache-Control: no-store`.

Schema revision 5 adds four isolated `rental_evidence_*` tables and one lookup
index. SQL is parameterized and every query is tenant-scoped. No credentials or
arbitrary URLs are accepted/stored. The fixed upstream fetch retains the existing
10-second timeout and bounded retry policy. Collection errors enter the existing
JSON/Sentry logging path without logging payloads, wallets or secrets.

Pool user responses are streamed with a 2 MiB decompressed-body limit, a bounded
read deadline and no redirects. More than 250 workers invalidate the complete
reading (`oversized`), rather than cataloging a misleading partial list. This
state resets evaluation and does not become zero or worker absence.

Bounds: 250 known sources and 50 retained rental references per tenant; 10,000
points per rental across revisions, up to 30 days. The CSV is not an indefinite
archive; copy it before those limits. A disabled binding can be reconfigured.
Expired rows are excluded on reads/exports and pruned during collection. Alert
events older than 30 days are pruned during tenant collection. Operators should
back up the database according to their deployment's retention policy.

## Verification

Real-SQLite tests cover tenant isolation, finite validation, exclusive binding,
zero/missing/ambiguous/error states, low/gap/healthy streaks, revisions, retention,
cache idempotency, CSV injection and route roles. Polling tests cover original
retrieval metadata and the private-metadata handoff. The real JS fragment/core
suite and Playwright exercise configuration, UTC provenance, stale states, CSV,
escaping, keyboard interactions and request ordering. The generated `app.js`
must be rebuilt and pass its drift gate. CI still requires the full Python
coverage gate, frontend guards and an independent pre-merge review.
