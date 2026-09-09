# SHA-256 Pool Intelligence gates 078–101

Last reviewed: 2026-09-09. A bounded, read-only V1 probe performs explicit
network I/O. Sanitized evidence can be aggregated without further I/O, but the
probe is not exposed as arbitrary discovery and cannot change a pool.

| Gate | State | Evidence / remaining work |
|---|---|---|
| 078 Endpoint parser | PASS | Strict parser and adversarial unit matrix. |
| 079 SSRF protection | PASS | Single-pass resolver validates every answer before the read-only connector opens a socket; mixed public/private responses fail closed. |
| 080 DNS rebinding | PASS | Connector uses only numeric addresses captured by the validated result; TLS retains the original hostname only for SNI/certificate verification. |
| 081 Generic Stratum V1 | PASS | Bounded `mining.subscribe` probe validates the generic V1 response without credentials or share submission. |
| 082 Stratum V2 | FAIL | Separate protocol model exists; adapter absent. |
| 083 Unknown discovery | FAIL | No active discovery. |
| 084 Fingerprinting | PASS | Provider identity requires two independent trusted signals at or above 80%; weak, inferred or conflicting evidence returns unknown. |
| 085 Capability graph | PASS | Immutable graph caps assertions/nodes/dependencies and resolves observed states, missing nodes, conflicts and cycles fail-closed. |
| 086 Chain detection | PASS | Chain classification accepts only explicit observed/API-reported chain signals; endpoint and provider heuristics are not inputs. |
| 087 Authentication | FAIL | Credentials deliberately excluded from foundation. |
| 088 Pool health | PASS | Sanitized health result distinguishes valid V1 subscribe from timeout, TLS, transport and protocol failures. |
| 089 Pool latency | PASS | Probe records bounded DNS, TCP, TLS, Stratum and total timings. |
| 090 Failover | FAIL | Ordered failover policy absent. |
| 091 ASIC compatibility | FAIL | No DeviceCapabilities + PoolCapabilities evaluator. |
| 092 Pool dry-run | FAIL | Bitaxe `update_pool` now validates a complete canonical payload without network I/O, but DNS/destination/Stratum checks are still absent. |
| 093 Confirmation | FAIL | The Bitaxe route binds canonical config to a one-time server token; the universal pool engine and other firmware paths are not integrated. |
| 094 Reconciliation | FAIL | Bitaxe can compare fresh firmware telemetry to the request hash and never treats HTTP ACK as verified; auth/jobs/hashrate evidence and other firmware remain absent. |
| 095 Rollback | FAIL | Previous known-good pool model absent. |
| 096 Canary | FAIL | Fleet rollout state machine absent. |
| 097 Virtual Pool Lab | PASS | Stateful local V1 simulator covers successive sessions, timeout, invalid JSON and oversized responses. |
| 098 Fuzzing | FAIL | Protocol parser/fuzzer absent. |
| 099 Red Team | FAIL | Endpoint matrix exists; active connector attack remains. |
| 100 iOS pool E2E | FAIL | Installed-app pool journey is not implemented. |
| 101 Android pool E2E | FAIL | Installed-app pool journey is not implemented. |

Arbitrary pool discovery must remain disabled until Gates 079–083 and resource
limits are proven together. Pool mutation must remain unavailable until Gates
091–096 pass.
