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

The public subscribe-response validator rejects boolean IDs, missing or
duplicate JSON keys, invalid subscription tuples, absent `mining.notify`,
malformed extra nonces and responses above 64 KiB. It returns no remote data;
only controlled reason codes cross the boundary. A deterministic 6,000-case
byte/structured fuzz corpus verifies that malformed input cannot escape an
uncontrolled parser exception. Hermetic red-team cases also replay DNS
rebinding and mixed SSRF answers, and forge typed destinations to prove the
connector revalidates numeric address scope and resolution metadata before it
creates a socket.

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

`selection.py` adds a network-free decision layer for device/pool compatibility
and ordered failover. Compatibility accepts at most 32 named requirements and
compares only effective states already present in the immutable capability
graphs. Missing nodes remain `unknown`; `error`, `unsupported`,
`auth_required`, and `unknown` all prevent a positive compatibility result.
Model names, firmware names, provider names and endpoints are not heuristics.

Failover accepts at most 16 pre-evaluated candidates. It keeps the active pool
while health and compatibility remain `supported`; otherwise it selects the
lowest numeric priority, preserving caller order for ties. Cooldown, unhealthy
and incompatible candidates are skipped with controlled reason codes. The
policy never resolves DNS, retries, sleeps, handles credentials, opens a socket
or mutates an ASIC. Its result is a decision for a separately reviewed caller,
not permission to execute a command.

`rollout.py` provides the equally pure fleet canary state machine. A plan holds
only a sanitized rollout ID, a SHA-256 configuration reference and at most
1,000 unique device IDs; it contains no endpoint, worker or credential. The
first transition releases only the mandatory canary (at most 10 devices), then
stable batches of at most 100. Every active device must have an exact
reconciled outcome. A single `failed` or `unknown` outcome halts the rollout and
no later device is released. State objects validate their own ordering, and the
public transition path offers no way to skip the canary. This layer still
performs no physical update or rollback.

`dry_run.py` composes the reviewed boundaries before an `update_pool` command
can receive a confirmation token: complete canonical configuration, exactly
one DNS resolution, the default public-destination and Stratum-port policy,
then the credential-free V1 subscribe probe. The worker identity is validated
but is never passed to the resolver or probe. Public results omit endpoint,
numeric address, worker and remote payload; they contain only controlled state,
protocol, capability and finite non-negative latency values. Invalid config,
DNS failure, SSRF/private destinations, custom ports and protocol failures all
fail closed. Local-pool mode remains unavailable on this member-facing path.

Stratum V2 requires a separate adapter. Active unknown-pool discovery,
authentication and physical fleet rollout remain disabled until their own gates
pass.

Credentials remain separate from endpoint metadata. Passwords are never part of
normalized URLs, logs or the pool knowledge model.

## Safe `update_pool` boundary (Bitaxe/AxeOS)

The existing device-command API applies the network-free parser before a pool
dry-run, confirmation, idempotency claim, or adapter call. A pool dry-run then
performs the bounded network preflight above, and a failed preflight prevents
the server from issuing a confirmation token. The supported payload remains
`stratumURL`, `stratumPort`, and `stratumUser`, but all three are required so a
partial write cannot combine new input with stale firmware state.
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

The pool-update command boundary does not invoke the compatibility,
failover or canary decision layers yet and still does not preserve a rollback
target. A successful dry-run is evidence only for the proposed endpoint at that
moment; it does not authenticate the worker or prove a physical ASIC mutation.
Physical commands therefore remain disabled by deployment policy unless
explicitly enabled, and the V1 health probe is not evidence that arbitrary pool
mutation is production-ready.
