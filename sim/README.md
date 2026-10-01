# CYPHER65 miner simulator lab

This directory is a **bounded, local contract/integration lab**, not a claim
that virtual miners equal real hardware. It reuses repository-owned NerdQaxe/
AxeOS and cgminer API loopback servers, and validates the production agent
probe + Fleet registration/telemetry routes with scratch SQLite storage.

The three integration case labels (`7`, `19`, `43`) are fixed profile variants
for repeatability, **not** a seeded random physics model. They only select
different deterministic uptime values; no seed, PRNG, fake clock, or physical
model is implemented by this protocol-only slice.

## What this lab proves

- The selected source-derived AxeOS fixture can be served by an HTTP listener
  on loopback and read by the production agent's AxeOS probe/telemetry parser.
- The production agent's discovery result can be registered through the real
  Flask agent route, telemetry persisted by `DeviceRegistry`, and read through
  the authenticated Fleet listing route in a test environment.
- The existing cgminer mock accepts TCP JSON requests and tests the agent's
  `version`, `summary`, `stats`, `pools`, and parsing behavior against its
  authored response fixture.
- Tests can repeat deterministically at the contract level. This first slice
  does not yet provide a physical ASIC model or seeded stochastic simulation.

## What is deliberately not implemented / not proved

- No physical captures are checked in. `official_esp_miner_info` is a generated
  fixture informed by upstream OpenAPI; the cgminer fixtures are authored test
  responses. Neither should be described as `captured` evidence.
- No hardware thermal/electrical/hashrate calibration, chip-count scaling,
  throttling curves, Poisson share generator, pool-side PoW validation or
  realistic ASIC mining work is modeled.
- No mock pool is connected to a virtual miner in this lab cycle. Nothing
  contacts a public pool, real miner, Render, external DNS or real database.
- Loopback integration does not prove physical LAN, multicast/mDNS/DHCP/VLAN,
  Docker Engine host network, Docker Desktop VM routing, or installed service
  behavior.
- Only the AxeOS/ESP-Miner source-derived subset and generic cgminer-compatible
  test fixture are covered; Braiins, Antminer, Whatsminer, Avalon, and exact
  NerdQaxe release variations remain unproven unless catalogued explicitly.

## Reproduction

From the repository root. The three parameterized E2E cases use fixed profile
  values keyed by profile ID; they are repeatable deterministic fixtures, not
  seed variants or a randomized ASIC model.


```bash
SECRET_KEY=test-secret-0123456789 python -m pytest \
  tests/test_axeos_firmware_contract.py \
  tests/test_agent_protocol.py \
  tests/integration/test_agent_fleet_pipeline.py -q
```

The E2E test binds only to `127.0.0.1` using an ephemeral port. The cloud API
is Flask's in-process test client; database is under pytest's temporary path.
No background Flask server, Docker service, internet endpoint, pool, or ASIC is
started. To prove the virtual listener is real network I/O rather than a direct
function mock, the agent uses `urllib` to GET the listener and socket-based
cgminer tests run against local TCP sockets.

Run broader discovery/install/regression tests as appropriate:

```bash
SECRET_KEY=test-secret-0123456789 python -m pytest \
  tests/test_agent_discovery.py tests/test_agent_install_config.py \
  tests/test_agent_main_loop.py tests/test_agent_api.py -q
```

## Layout

- `docs/contact-surface.md` — external/network/storage boundary map.
- `catalog/*.yaml` — source/assumed item-level fidelity, gaps, and family notes.
- `catalog/COVERAGE.md` — summarized evidence matrix and promotion gate.
- `reports/fidelity-2026-10-01.md` — current proof, counterevidence and limits.

## Fidelity policy

Every response field used by a virtual profile must point to `source`,
`captured`, or `assumed`. `source` means an upstream document states the
contract; it is not hardware evidence. `captured` is reserved for reviewed,
sanitized raw hardware output with model, firmware and capture conditions.
Assumptions remain assumptions even when a test passes against them.

Source revisions currently recorded: ESP-Miner `c75aa99dc867db6ed1f38c7add113c452f263633`, NerdQAxePlus firmware `c18abafebde66c39f4bd8ae6d839088b84b4e79c`, and archived cgminer `b8491c66e7e22f23a9edf095dd1337ee581e88bd`. The BitMaker-hub board README revision could not be resolved (API returned 422); it is descriptive project context, not an API source.

Before adding richer virtual hardware, collect approved physical captures
(read-only, secret-scrubbed), decide the required families/topologies, and add
deterministic fake-clock/seeded physics and failure schedules. Keep production
code changes outside a simulator-only branch unless a separately reviewed
product bug is demonstrated.
