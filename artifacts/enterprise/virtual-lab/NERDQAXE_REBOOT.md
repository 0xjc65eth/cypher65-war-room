# NerdQaxe reboot lifecycle — virtual-lab evidence

Status: automated virtual-hardware validation implemented; physical validation
remains required.

## Proven path

```text
Mobile client contract
→ CYPHER65 device-control API
→ production BitaxeAdapter
→ stateful NerdQaxe/AxeOS HTTP service
→ reboot ACK
→ HTTP 503 / offline observed
→ HTTP telemetry reconnect
→ uptime 7200 s → 3 s
→ reconciliation confirmed / phase verified
→ durable operation ledger + audit callback
```

The virtual device is implemented as an actual localhost HTTP service. The
production adapter is not patched to return success. CYPHER65 independently
observes the offline and online responses.

## Safety invariants

- Dry-run remains the API and mobile default.
- A state-changing reboot requires the one-time server confirmation token.
- ACK is presented as acknowledged, never as physical success.
- Fresh online telemetry alone cannot verify a reboot.
- Verification requires an observed offline transition, reconnection and a
  lower post-command uptime.
- Missing or contradictory evidence stays pending/unknown and fails closed.
- Every reconciliation attempt is persisted directly in the structured audit
  log; the operation lifecycle and audit outcome are persisted in
  `external_operations`.

## Automated evidence

- `tests/integration/test_nerdqaxe_reboot_lifecycle.py`
- `tests/test_command_reconciliation.py`
- `mobile/tests/useCommands.test.ts`

## Explicit limitation

This evidence proves the backend/mobile contract and Virtual NerdQaxe path. It
does not prove an installed Android APK, physical NerdQaxe firmware behavior,
Wi-Fi/mobile transitions, Android process death, or hardware recovery timing.
Those release gates remain `BLOCKED_EXTERNAL`/pending until exercised with the
exact signed APK and controlled physical hardware.
