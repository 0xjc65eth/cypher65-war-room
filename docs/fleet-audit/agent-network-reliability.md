# Agent LAN reliability — Issue #669

## Scope verified

The codebase base already includes installer persistence for `CYPHER65_SCAN_CIDR`
and `CYPHER65_DEVICES` (Issue #636) and best-effort interface CIDRs with a
bounded `/24` fallback (Issue #667). This change documents those actual
semantics, distinguishes Linux Docker Engine host networking from Docker Desktop,
replaces unsupported installer success claims, and covers the local agent to
Fleet data path with a virtual AxeOS miner.

## Positive evidence

- `tests/integration/test_agent_fleet_pipeline.py` uses the production agent
  scan/probe/telemetry code, source-derived NerdQaxe/AxeOS payload, authenticated
  Flask registration and telemetry routes, the real SQLite `DeviceRegistry` on
  a temporary database, and authenticated Fleet listing. It asserts H/s, MAC,
  shares, uptime, model and IP, and checks tenant isolation.
- Discovery tests prove CIDR interface masks take priority, fallback uses the
  documented IPv4-derived `/24`, and explicit IPs win over a configured CIDR.
- Installer serializer tests parse launchd/systemd output and execute the
  inert fallback runner, proving explicit network configuration survives
  service generation without launching an actual agent.
- Installer message test pins the honest “service configured” claim and
  rejects the old “AGENT INSTALLED & RUNNING”/“fleet appears in ~1 min” claims.

## Counter-evidence / limits

- A virtual miner reachable at loopback proves protocol-to-database integration,
  not LAN routing, a Docker Desktop VM route, physical miner interoperability,
  Render authentication, or hosted dashboard availability.
- Discovery may still choose an irrelevant interface CIDR; an operator should
  configure `CYPHER65_SCAN_CIDR`/`CYPHER65_DEVICES` if the detected LAN is wrong.
  Explicit selection cannot fix a blocked route or firewall.
- No timing/throughput claim is made. The scan caps hosts at 1,024 per CIDR and
  uses bounded probe timeouts/worker count; hardware-network efficiency requires
  measurement in the operator's target network.
- No real miner commands were sent and no production system/service was changed.

## Validation run

`SECRET_KEY=test-secret-0123456789 python -m pytest tests/test_agent_api.py tests/test_agent_protocol.py tests/test_axeos_firmware_contract.py tests/test_agent_discovery.py tests/test_agent_install_config.py tests/test_agent_main_loop.py tests/integration/test_agent_fleet_pipeline.py -q`

Final affected-suite run: **125 passed in 20.51s**. Full Python suite:
**3785 passed, 2 skipped in 251.70s**. `bash -n agent/install.sh`, Python
`compileall`, Black checks for changed Python files, and `git diff --check`
passed. CI feedback on the first PR revision found an accidental dependency on
uncommitted #670 harness code; #669 now uses direct strict field assertions so
it remains independently buildable and does not absorb simulator files.

An initial run exposed an existing docs assertion requiring the Docker image
reference; it was restored in the guide, after which `TestDocsAgent` passed.
