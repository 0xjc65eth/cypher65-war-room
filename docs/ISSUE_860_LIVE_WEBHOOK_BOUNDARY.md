# Issue #860 — Shared live webhook delivery boundary

## Scope and provenance

Issue: <https://github.com/0xjc65eth/cypher65-war-room/issues/860>.
Base: `f479382750f608b44d3a8dfd6a163ab87ae97d6a`.
Branch: `security/860-live-webhook-boundary`.

Issue #857 / PR #864 protected only the synthetic test-webhook route. This
patch routes live Discord, Telegram and generic payloads through that same
destination policy, extracted as `deliver_webhook`. The compatibility probe
wrapper still uses the same implementation. No dependency is added.

## Call map

- Operator polling: `services.polling` -> `send_webhook_for_alert`.
- AlertEngine: `app._webhook_dispatch` -> `dispatch_webhook_or_queue`.
- Tenant wallet/rental/energy alert families: `services.user_polling` ->
  async dispatcher -> persistent queue dispatcher.
- Delayed deliveries: `services.webhook_queue.process_due_webhooks` ->
  `send_webhook_notification`.
- Sample auto-exclusion alert: settings route -> `send_webhook_for_alert`.
- Synthetic channel probe: settings route -> `deliver_test_webhook` wrapper.

All actual HTTP webhook sends now converge on the shared pinned-IP transport.
Web Push/VAPID delivery is a different transport and is not certified here.

## Destination and payload contract

Only public HTTPS destinations on port 443 are accepted. URL validation,
bounded DNS capacity/deadline, validation of every returned address, numeric
IP pinning, original Host/SNI/certificate verification, no environment proxy,
no redirects, no response-body download and no inline POST retry are shared
with #857. Resolver lookup has a two-second budget; connect/read phases have
separate positive bounds of at most five seconds. These are **not** a total
wall-clock deadline. A stuck OS resolver retains one of four capacity slots
until it returns; it cannot spawn an unbounded retry queue of DNS jobs.

Discord and Telegram payload builders are selected by exact parsed hostname,
not substrings in URL paths, queries, userinfo or lookalike domains. Intended
embed/Markdown/generic shapes are retained. Only HTTP 2xx is accepted; redirects,
non-2xx, invalid destinations and transport uncertainty return failure.

The AlertEngine callback no longer attaches global operator wallet/worker
fields to a named tenant's destination. Operator default-tenant behavior is
retained. On **all named-tenant queue retries**, optional worker/address fields
are blanked because persisted legacy field provenance cannot be trusted.
This intentionally also omits legitimate own-wallet/worker fields on new
named-tenant retries; alert content remains. It does not reconstruct ownership
or claim a migration of historically delivered payloads.

## Retry and logging semantics

Existing queue attempt caps and backoff schedule remain unchanged. Delivery is
best-effort with bounded at-least-once attempt semantics, **not exactly once**:
acceptance followed by timeout can duplicate on a delayed retry, and exhaustion
or persistence failure can lose an alert. The async outer exception handler no
longer blindly sends a second POST after an unknown dispatcher failure. Every
queue attempt revalidates DNS/destination; a public-to-private DNS change cannot
use the earlier validated address as authority for another attempt.

Webhook/queue/caller failures emit fixed structured outcomes, without raw
destination URLs, provider response bodies or exception details. Persistence
still stores the configured destination for later delivery, as before; this is
not encryption-at-rest or credential rotation work. No real credential is used
in tests and no production webhook, hardware or payment operation is requested.

## Regression evidence

- New notifier/queue/probe tests inject synthetic DNS and HTTPS connection pools
  into the real shared transport. They exercise all callers, private/mixed DNS,
  lookalike provider hosts, HTTP outcomes, DNS revalidation, timeout validation,
  redaction, unknown-delivery no-replay and legacy queue identity suppression.
- The existing tenant callback regression was first extended and failed on the
  operator worker field; it passes after isolation. Existing payload/queue/
  polling assertions remain active, with mocks retargeted to the actual owner.
- The first full suite had **5,083 passes / 1 failure / 4 skips**, coverage
  86.35%. The failure was an integration test still mocking `requests.post` after
  production moved to the shared transport. It was not waived: the test now
  asserts the actual builder reaches an injected shared transport. The original
  failed log is retained. Final rerun evidence is recorded below when complete.
- Independent source review and repeated affected tests found no blocking new
  defect; this is not a formal GitHub approval or exact-head remote CI.

Logs and coverage files are outside Git under
`/private/tmp/cypher65-devil-work.7Ltt1O/`. Full-suite reruns use a local plugin
that blocks real non-loopback DNS/socket operations while preserving explicit
test mocks and loopback fixtures. It is verification tooling, not a production
dependency or a claim that prior unrelated tests proved no network activity.

### Final local verification

- Full Python: **5,088 passed, 4 skipped**, 644 existing warnings, 195.07 seconds;
  configured coverage **86.41%**, unchanged 80% gate. Log
  `live-webhook-full-final.log`, XML `live-webhook-full-final.xml`.
- The preceding guarded rerun had 5,082 passes / 3 scanner failures because the
  verification plugin raised PermissionError instead of the DNS API's gaierror
  for blocked resolution. The plugin was corrected, not the scanner or its
  assertions. That failed log `live-webhook-full-v2.log` is also retained.
- Focused transport/queue/polling/scanner: 239 passed; transport **100% line and
  branch coverage**, queue **98%** (only unchanged queue-depth error path missed).
  This is module coverage, not the whole repository or a Codecov patch result.
- Pinned CI Black25.1.0, Flake8 7.1.1, Bandit1.9.4 (-ll), monkeypatch-owner guard,
  generated bundle drift and diff whitespace checks pass. Existing Bandit
  unmatched-nosec warnings are not findings. No static-analysis exclusion added.
- Independent reviewer repeated 203 affected cases and reviewed the production
  diff; all passed. Later changes add timeout edge-case validation, corrected
  mock ownership, logging tests and documentation; final full suite covers them.

## Remaining release gates

JS baseline worker regression #863 and nested-runner defect #867 are separate
Issues. Mobile audit #859 remains a composed release blocker. No test exclusion,
forced major dependency override, relaxed coverage gate, merge or deploy is
part of this correction. Exact-head CI/Codecov and independent GitHub approval
are still required.
