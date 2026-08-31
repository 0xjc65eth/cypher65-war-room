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
