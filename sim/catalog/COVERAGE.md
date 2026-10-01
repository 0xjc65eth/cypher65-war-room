# Fidelity catalogue coverage

`source` means documented in a cited upstream schema/reference. `captured` is
reserved for raw, reviewed physical-device responses. `assumed` means the
behavior/value is inferred from implementation or a test fixture without
physical capture or an upstream guarantee. Source-schema fidelity is not
hardware validation.

| Family/item | Fidelity | Source / fixture | Contract test | Remaining gap |
|---|---|---|---|---|
| ESP-Miner `/api/system/info` SystemInfo keys/types | source | [ESP-Miner OpenAPI](https://github.com/bitaxeorg/ESP-Miner/blob/c75aa99dc867db6ed1f38c7add113c452f263633/main/http_server/openapi.yaml), commit `c75aa99dc867db6ed1f38c7add113c452f263633` | virtual payload + contract tests | No captured device response; schema does not prove all builds emit every key. |
| AxeOS `hashRate` GH/s, uptime, MAC, pool identity, temps/fans/power | source for types/units in the pinned schema | same OpenAPI; source-derived `axe_fleet/axeos_contract.py` fixture | normalizer/agent/HTTP virtual tests | Not measured against physical firmware; runtime ranges/freshness absent. |
| AxeOS command routes (restart/pause/resume/config) | source for route paths and declared response schemas; assumed for runtime semantics | pinned ESP-Miner OpenAPI paths and response schemas; implementation-specific effects remain firmware-dependent | local virtual restart/reboot and command mocks | No physical command response, reboot timing, pause/resume effect, or configuration effect is captured. |
| NerdQAxe+ AxeOS lineage | source for project description; exact per-release schema assumed | [NerdQAxe board repository](https://github.com/BitMaker-hub/NerdQaxe) (commit unresolved); [NerdQAxePlus firmware](https://github.com/shufps/ESP-Miner-NerdQAxePlus), commit `c18abafebde66c39f4bd8ae6d839088b84b4e79c` | source-shape virtual payload only | Exact release API parity and physical capture absent. |
| cgminer core JSON requests/responses | source | [cgminer API-README](https://github.com/ckolivas/cgminer/blob/b8491c66e7e22f23a9edf095dd1337ee581e88bd/API-README), archived commit `b8491c66e7e22f23a9edf095dd1337ee581e88bd` | TCP mocks for `version`, `summary`, `stats`, `pools` | Vendor forks differ; stats values, framing and rate units partly assumed. |
| Antminer, Whatsminer, Avalon specifics | assumed | no per-firmware source contract/capture registered | generic cgminer mock only | no family-specific hardware/firmware tests. |
| Braiins OS+ REST schema | assumed | no pinned official schema/fixture in this cycle | separate selected-path tests | Needs versioned source/capture before virtual response claims fidelity. |
| Stratum V1 jobs/shares | not implemented as part of lab gate | overview references only: [SV1 overview](https://bitcoinwiki.org/wiki/Stratum_mining_protocol), [BIP 310](https://github.com/bitcoin/bips/blob/master/bip-0310.mediawiki) | existing virtual pool is separate | no miner round-trip, share hash validation, or pool reconciliation. |
| ASIC physics/share statistics | not implemented | no calibrated physical dataset | none | no efficiency, thermal, hashrate or share-rate prediction claim. |
| LAN/Docker/DHCP/mDNS/VLAN | not simulated | see `sim/docs/contact-surface.md` | loopback only | no proof of physical LAN/Docker routes or discovery. |

## Gate decision

The catalogue gate passes only for a **bounded source-derived contract lab**.
Physical captures, multi-version parity, thermal calibration, real share
validation and Docker/LAN topology fidelity are not achieved. Never promote a
row to `captured` without reviewed raw bytes, headers/transport, device model,
firmware version and capture method.
