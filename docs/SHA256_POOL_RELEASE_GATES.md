# SHA-256 Pool Intelligence gates 078–101

Last reviewed: 2026-08-31. The foundation is intentionally network-free. A
parser unit test is not evidence that active discovery or pool changes are safe.

| Gate | State | Evidence / remaining work |
|---|---|---|
| 078 Endpoint parser | PASS | Strict parser and adversarial unit matrix. |
| 079 SSRF protection | FAIL | Destination policy exists; active connector is not implemented. |
| 080 DNS rebinding | FAIL | Validated-address result exists; connection pinning is not implemented. |
| 081 Generic Stratum V1 | FAIL | Protocol negotiation/adapter absent. |
| 082 Stratum V2 | FAIL | Separate protocol model exists; adapter absent. |
| 083 Unknown discovery | FAIL | No active discovery. |
| 084 Fingerprinting | FAIL | No provider confidence engine. |
| 085 Capability graph | FAIL | Capability states exist; discovery graph absent. |
| 086 Chain detection | FAIL | No observed chain classifier. |
| 087 Authentication | FAIL | Credentials deliberately excluded from foundation. |
| 088 Pool health | FAIL | No Stratum health probe. |
| 089 Pool latency | FAIL | No timestamped DNS/TCP/TLS/Stratum measurements. |
| 090 Failover | FAIL | Ordered failover policy absent. |
| 091 ASIC compatibility | FAIL | No DeviceCapabilities + PoolCapabilities evaluator. |
| 092 Pool dry-run | FAIL | Bitaxe `update_pool` now validates a complete canonical payload without network I/O, but DNS/destination/Stratum checks are still absent. |
| 093 Confirmation | FAIL | The Bitaxe route binds canonical config to a one-time server token; the universal pool engine and other firmware paths are not integrated. |
| 094 Reconciliation | FAIL | Bitaxe can compare fresh firmware telemetry to the request hash and never treats HTTP ACK as verified; auth/jobs/hashrate evidence and other firmware remain absent. |
| 095 Rollback | FAIL | Previous known-good pool model absent. |
| 096 Canary | FAIL | Fleet rollout state machine absent. |
| 097 Virtual Pool Lab | FAIL | Stateful Stratum simulators absent. |
| 098 Fuzzing | FAIL | Protocol parser/fuzzer absent. |
| 099 Red Team | FAIL | Endpoint matrix exists; active connector attack remains. |
| 100 iOS pool E2E | FAIL | Installed-app pool journey is not implemented. |
| 101 Android pool E2E | FAIL | Installed-app pool journey is not implemented. |

Arbitrary pool discovery must remain disabled until Gates 079–083 and resource
limits are proven together. Pool mutation must remain unavailable until Gates
091–096 pass.
