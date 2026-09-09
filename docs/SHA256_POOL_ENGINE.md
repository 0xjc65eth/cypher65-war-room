# Universal SHA-256 Pool Intelligence Engine

## Implemented foundation and read-only V1 probe

`services/pool_intelligence/` provides a network-free endpoint parser, typed
protocol/capability/provenance models, a single-pass resolver, a post-DNS
destination policy and a bounded Stratum V1 health probe. Unknown providers are
valid: provider identity is separate from protocol compatibility, chain and
payout mechanism.

The probe sends only `mining.subscribe`; it does **not** authorize a worker,
submit a share, infer a chain or change an ASIC. A valid subscribe response is
evidence for generic Stratum V1 compatibility only. It is not evidence for a
provider identity, payout method, worker authentication or usable jobs.

The implemented V1 path is: parse → resolve once → validate every address →
connect directly to a validated numeric address → optional TLS with the original
hostname used only for SNI/certificate verification → bounded subscribe request
and response. No connector calls DNS after policy validation, closing the
classic DNS-rebinding gap between validation and connection. At most four
validated addresses are attempted, each with a maximum 30-second configurable
timeout; a response may not exceed 64 KiB.

The result exposes sanitized state plus DNS, TCP, TLS and Stratum latency. It
never returns a remote error message, extra nonce, worker identity or credential.
The reusable stateful simulator in `tests/virtual_pool/stratum_v1_lab.py` proves
successful subscriptions, timeouts, malformed JSON and oversized responses
without contacting an external pool.

`evidence.py` builds an immutable capability dependency graph from at most 128
sanitized assertions, 256 total nodes and 16 dependencies per assertion. Only
`observed` and `api_reported` provenance can establish a capability or dependency;
missing dependencies become explicit `unknown` nodes, conflicting states become
`error`, and dependency cycles are rejected. The V1 result can be converted into
an observed `protocol.stratum_v1.subscribe` assertion without copying endpoint
data or remote payloads into the graph.

Provider fingerprinting and chain classification use separate signal types so a
provider cannot accidentally become chain evidence. Each classifier accepts at
most 64 signals, and identification requires two independent trusted sources with
at least 80% confidence. Inferred/user-provided, weak, single-source or conflicting
evidence stays `unknown`. No provider catalog or hostname/port heuristic is
embedded in the engine; callers must supply sanitized signals produced by
separately reviewed observers.

Stratum V2 requires a separate adapter. Active unknown-pool discovery,
authentication, failover and fleet rollout remain disabled until their own gates
pass.

Credentials remain separate from endpoint metadata. Passwords are never part of
normalized URLs, logs or the pool knowledge model.

## Safe `update_pool` boundary (Bitaxe/AxeOS)

The existing device-command API now applies the network-free parser before a
pool dry-run, confirmation, idempotency claim, or adapter call. The supported
payload remains `stratumURL`, `stratumPort`, and `stratumUser`, but all three are
required so a partial write cannot combine new input with stale firmware state.
Ports outside `1..65535`, ambiguous/mismatched endpoints, invalid worker
identities, credentials embedded in a URL, and unknown fields are rejected;
values are never clamped or repaired silently.

The canonical payload is bound to the one-time human confirmation and durable
idempotency hash. Endpoint and worker identity are transient: command responses,
history, logs, and audit details redact them. An AxeOS HTTP ACK means only
`acknowledged`. The operation becomes `confirmed` only when a newer telemetry
sample exposes a complete pool configuration whose canonical hash matches the
request. Missing comparable telemetry remains `unknown`; contradictory
telemetry fails reconciliation.

The pool-update command boundary does not invoke the read-only probe yet and
still does not preserve a rollback target or provide canary fleet rollout.
Physical commands therefore remain disabled by deployment policy unless
explicitly enabled, and the V1 health probe is not evidence that arbitrary pool
mutation is production-ready.
