# Universal SHA-256 Pool Intelligence Engine

## Implemented foundation

`services/pool_intelligence/` provides a network-free endpoint parser, typed
protocol/capability/provenance models and a post-DNS destination policy. Unknown
providers are valid: provider identity is separate from protocol compatibility,
chain and payout mechanism.

The current package does **not** yet probe a pool, authorize a worker, infer a
chain or change an ASIC. No compatibility claim is made without observed
protocol evidence.

Planned stages are: parse → policy → DNS → revalidate every address → connect to
the validated address → TLS/Stratum negotiation → capabilities → fingerprint →
optional specialized adapter. Stratum V1 and V2 require separate adapters behind
a common interface.

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

This boundary does not resolve DNS, apply the post-DNS destination policy,
negotiate Stratum, prove authentication/jobs/hashrate, preserve a rollback
target, or provide canary fleet rollout. Physical commands therefore remain
disabled by deployment policy unless explicitly enabled, and this work is not
evidence that arbitrary pool mutation is production-ready.
