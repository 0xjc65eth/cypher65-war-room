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
  scan/probe/telemetry code, official NerdQaxe payload, authenticated Flask
  registration and telemetry routes, the real SQLite `DeviceRegistry` on a
  temporary database, and authenticated Fleet listing. It asserts H/s, MAC,
  shares, tenant ID, and count across each hop.
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

Final affected-suite run: **121 passed in 25.88s**. The preceding run, before
the final output-assertion cleanup, had 122 passed; this is not the final count.
A focused contra-evidence run of CIDR-cap, explicit-host selection, and full
virtual pipeline: **3 passed in 1.13s**. `bash -n agent/install.sh`, Python
`compileall`, and `git diff --check` passed.

An initial run exposed an existing docs assertion requiring the Docker image
reference; it was restored in the guide, after which `TestDocsAgent` passed.
