# Issue #856 — legacy operator wallet authorization

## Scope and confirmed failure

The legacy `POST /api/set-address` handler changes process-global monitoring
state and unpartitioned chart tables. `GET /api/wallet/history` reads an
unpartitioned operator history table. Neither is a per-tenant wallet API.
Before this change, valid named-tenant credentials passed their role checks:
a member could change the operator's monitored address, delete chart history,
and receive the outgoing address. Named tenants could also read the global
wallet history. These are monitoring/privacy boundaries, not evidence of
fund custody, payment-address modification, or a private-key compromise.

## Conservative boundary

`services/operator_wallet.operator_wallet_required` executes before the legacy
handlers and their tenant injection:

| Request | Legacy mutation | Legacy history |
| --- | --- | --- |
| Named-tenant JWT, API key, or authenticated session, including tenant admin | 403 `OPERATOR_SCOPED_DATA` | 403 `OPERATOR_SCOPED_DATA` |
| Invalid explicit Authorization/API key, refresh/revoked token, invalid session identity, or conflicting authenticated identities | 401 | 401 |
| Default-tenant admin identity or deployment-owner API key | Allowed | Allowed |
| Default-tenant member/viewer | 403 | Allowed |
| Unknown role | 403 | 403 |
| Anonymous remote with deployment authentication configured | 403 | 403 |
| Anonymous open self-host / documented configured loopback operator access | Existing behavior retained | Existing behavior retained |

An explicitly lower role is honored even on loopback and in open mode. A
valid owner key does not upgrade an explicitly supplied viewer JWT. Signed
legacy operator JWTs without a role retain their existing admin meaning.
All supplied bearer/key/session identities must agree; invalid credentials
never fall through to the open-mode or localhost operator defaults.

No schema change, tenant backfill, fake per-tenant history, hardware command,
provider request or payment change is included. Legacy history remains
operator-scoped. Named tenants retain the existing `/api/connect-wallet` and
ownership-checked `/api/session-snapshot` flow; this patch does not implement a
new wallet flow or change those handlers.

## Client compatibility

The existing wallet-history client checks non-2xx responses and renders an
unavailable/access-required message; it does not turn 403 into “no saved
wallets”. The legacy save handler displays the returned error and exits before
updating browser globals. A named tenant therefore receives a bounded refusal,
not an apparent successful operator mutation. The API refusal explains that
tenant sessions use `/api/connect-wallet`. No new frontend code or animation is
introduced by this security patch.

Requiring admin rather than member for the **global mutation** is intentional:
the default tenant identifies a data scope and does not grant an admin role.
Default-tenant viewers/members can continue to read history. Other legacy
operator-global surfaces are outside this narrow patch; this is not a claim
that every application endpoint has been exhaustively security-audited.

## Evidence and reproduction

Base: `02901d7c095e378ec0b2daab005d127cc9be00e1`.
`tests/test_operator_wallet_boundary.py` invokes the actual Flask routes using
synthetic JWTs/API keys/signed sessions and an isolated real SQLite database.
Rejected requests must make **zero** handler DB calls, leave all operator
fixture rows/globals intact, disclose no private fixture address/worker, and
perform no reset or thread startup. Socket connections and HTTP requests are
denied by the fixture. Positive operator cases replace only the fixture state;
background thread startup is intercepted. The tenant-session regression uses
the real session manager/ownership handlers with provider polling stubbed.

Regression-first run before production changes: **48 failed, 13 passed** across
the original 61 cases. After applying the fence: **61 passed**, 96.30% line
coverage on the new helper. Additional edge/compatibility cases bring the
focused suite to **74 passed** with **100% line and branch coverage** on the new
helper (54 statements, 28 branches, zero missing/partial branches). The related
auth/wallet suite passed **180 tests**, with 13
existing ResourceWarnings originating from legacy RBAC fixture DB handling.

```bash
SECRET_KEY=test-secret-0123456789-0123456789 \
python -m pytest tests/test_operator_wallet_boundary.py -q \
  --cov=services.operator_wallet --cov-branch --cov-report=term-missing \
  --cov-fail-under=80

python -m pytest tests/test_operator_wallet_boundary.py \
  tests/test_wallet_chart_switch.py tests/test_integration_session_wipe.py \
  tests/test_rbac_register.py tests/test_tenant_auth.py \
  tests/test_tenant_b2_isolation.py tests/test_auth_hardening.py \
  tests/test_ux_quickwins.py -q
```

Independent review, exact-head remote CI, full-project coverage, browser E2E
and any deployment confirmation are separate gates; local focused green is
not an approval or proof of deployment. No merge/deploy is performed here.
