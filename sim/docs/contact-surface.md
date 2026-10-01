# Fleet contact surface (read-only map)

## Flow in scope

`agent.agent.scan_lan_with_report()` → `agent.agent._probe_host()` →
`POST /api/agent/register` → `agent.agent._poll_telemetry()` →
`POST /api/agent/telemetry` → `DeviceRegistry` SQLite →
`GET /api/axe-fleet/devices` → tenant-filtered Fleet listing.

## Contact points

| Boundary | Code | Protocol / destination | Effect | Current evidence / limit |
|---|---|---|---|---|
| Host interface discovery | `agent/agent.py::_local_ipv4_addresses`, `_interface_cidrs` | OS routing/socket/ioctl; UDP `connect` to `8.8.8.8:80` to select a source address (no application data sent; OS route lookup may still be environment-dependent) | Reads local IPv4 and netmask when supported | Code inspected; not equivalent to LAN reachability. |
| LAN subnet discovery | `agent/agent.py::scan_lan_with_report` | Local IPv4 hosts from configured CIDR/explicit list | Concurrently probes up to configured host cap | Unit and loopback virtual tests; physical LAN, Docker Desktop VM and VLAN routing are not proven. |
| AxeOS probe/poll | `agent/agent.py::_get_json`, `_probe_axeos`, `_poll_telemetry`; `axe_fleet/connector.py` | HTTP GET `/api/system/info` on configured AxeOS port (default 80) | Reads identity/telemetry | ESP-Miner OpenAPI pinned to `c75aa99dc867db6ed1f38c7add113c452f263633`; virtual listener binds loopback. HTTP auth profiles are not simulated. |
| Braiins REST | `agent/agent.py::_probe_braiins_rest`, `_braiins_rest_telemetry` | HTTP GET `/api/v1/miner/stats` on configured port 80 then 50051 | Reads miner/pool/power blocks | Implementation contract only; no source-pinned Braiins fixture in repo, remains `assumed`. |
| cgminer family | `agent/agent.py::_cgminer_cmd`, `axe_fleet/scanner.py` | TCP JSON API (default 4028); response parser accepts NUL and tilde framing | `version`, `summary`, `stats`, `pools`; command execution can issue `restart` | cgminer API README pinned at `b8491c66e7e22f23a9edf095dd1337ee581e88bd`; vendor forks not individually captured. This AxeOS E2E does not exercise cgminer commands. |
| Virtual AxeOS restart/recovery | `agent/agent.py::_exec_command`; `tests/virtual_hardware/nerdqaxe.py`; Flask agent/Fleet routes | HTTP POST + loopback GET + in-process Flask POST/GET | Virtual restart yields one 503, heartbeat preserves last-good telemetry, recovered payload is persisted | E2E drives only the test-owned virtual listener; no physical command is issued. |
| Cloud agent API | `agent/agent.py::_post`, Flask `axe_fleet/routes.py` | Outbound HTTP(S) to configured `CYPHER65_SERVER_URL`; `/api/agent/heartbeat`, `/register`, `/telemetry`, `/commands/pull`, `/commands/<id>/ack` | Tenant-scoped registration, telemetry, command queue | Flask test client + scratch SQLite; no Render or external request in simulator. |
| SQLite persistence | `axe_fleet/registry.py::upsert_agent_device`, `save_agent_telemetry`, `list_devices` | Configured SQLite connection | Upsert by tenant/IP/MAC, persist telemetry/status, joined list | Scratch DB integration tests; not production DB. |
| Fleet read API | `axe_fleet/routes.py::list_devices` | Authenticated GET `/api/axe-fleet/devices` | Tenant-isolated list including trusted telemetry | Flask test client proves route response, not dashboard browser rendering. |
| Pool/Stratum | Device firmware → configured pool; not invoked by discovery | Firmware-level Stratum V1/V2 session | Mining jobs and submitted shares | Outside the lab's scan→Fleet flow. Existing pool simulators are separate; this E2E does not start one or connect to any pool. |
| DNS/mDNS/DHCP | Not invoked by this agent scan path | OS services / firmware may use independently | Address assignment and name resolution | Not simulated; hostname, DHCP churn and mDNS remain unproven. |
| Docker networking | External runtime | bridge/host/VM routes | Determines reachable IPs | Not proven by loopback tests; Docker is not started. |
| Installer/service | `agent/install.sh` | curl GET to dashboard `/agent/agent.py`; launchd/systemd/cron APIs; local files | Download and service configuration | Serializer tests are inert; no supervisor is installed or started. |

## Safety boundary

All virtual hardware listeners bind to loopback and ephemeral ports. The Fleet
test uses Flask's in-process client and scratch SQLite, and stubs
`_local_ipv4_addresses` so this harness does not perform the production
helper's UDP route-selection probe. The test code does not send requests to
real miners, external pools, DNS services, Render, Docker networks, or a
physical LAN; the only command is a virtual restart to its loopback listener.
Outside this harness, the production interface source-address selection may perform an OS route lookup
via UDP `connect` to `8.8.8.8:80` (without application data).

Never add tokens, pool passwords, wallet data, or real device addresses to
catalogue fixtures. Pool-like strings in the existing generated contract are
identity fields only; this harness does not resolve/connect to them.

## Known gaps

- No physical captured responses. AxeOS is `source` based on pinned upstream
  OpenAPI; NerdQaxe board README is not SHA-pinned; cgminer core API is pinned.
- No exact Braiins source contract, release matrix, or family-specific
  Antminer/Whatsminer/Avalon captures.
- No seeded thermal/electrical model, Poisson shares, Stratum validation,
  packet loss/latency, Docker topology, DHCP, mDNS, or VLAN model.
- No hardware LAN, Docker Desktop VM, service-manager, or hosted Render test.
