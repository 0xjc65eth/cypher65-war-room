# Issue 857 — synthetic webhook delivery boundary

## Resumo executivo

O endpoint de teste usa HTTPS público na porta 443, valida o certificado no
hostname original e conecta ao IP previamente aprovado. O payload é sintético,
sem carteira ou worker do operador. Redirects, respostas não-2xx e entregas
não confirmadas não viram sucesso. Nenhum webhook real foi enviado nos testes.

## Scope and baseline

Initial base: 02901d7c095e378ec0b2daab005d127cc9be00e1. Updated base:
633b0d1202f6d83e7dd8e5d98398be5750c65893, containing only the independently
merged Block Lab change. Scope is `/api/settings/test-webhook`. Live, queued
and auto-exclusion notifications remain separate in Issue #860.

Previously the route accepted an arbitrary URL, inherited requests redirects
and proxies, sent global wallet/worker fields, returned success for HTTP 503
and exposed exception text. Synthetic regression-first route tests produced
41 failures and one pass before the fix. No production exploit was attempted.

## Safety contract

- The PRO gate and member authorization remain. Explicit invalid, conflicting
  or empty identity is rejected before settings access, including non-ASCII
  keys and conflicting legacy sessions. A viewer cannot gain member authority
  through open mode. Anonymous open single-user behavior is preserved.
- URLs are bounded to 2048 characters and HTTPS/443, without userinfo,
  fragments, controls, backslash, scope IDs or invalid hostname labels.
- Every DNS answer passes the existing public-destination policy. Private,
  loopback, link-local, reserved, multicast, IPv6 transition and mixed unsafe
  answers fail closed. At most 16 DNS records are accepted.
- DNS resolves once. A 2-second caller deadline and a four-slot semaphore
  bound outstanding daemon lookups. A stuck OS resolver retains its slot
  until return; thread-start failures release capacity. No unbounded queue.
- A direct urllib3 TLS pool connects to a validated numeric IP, retaining the
  original SNI, certificate hostname and Host header. It does not inherit
  environment proxies, re-resolve the hostname or follow redirects.
- Connect and socket-read timeouts are 3 seconds each. **A read timeout is not
  an absolute wall-clock deadline** for trickled response headers. No maximum
  eight-second delivery guarantee is claimed. Response bodies are not read.
- Automatic POST retries are disabled: a timeout can mean the destination
  already accepted the message. Retrying blindly could duplicate delivery.
- Only HTTP 2xx produces success. Redirect/non-2xx becomes 502 with the status;
  unsafe destination becomes 400; DNS/transport unavailability becomes 502.
  Errors do not echo destination/query secrets or provider exception details.
- The legacy payload keys remain, with worker `cypher65-test` and empty
  address. The test cannot disclose global operator wallet/worker data.
- Response and pool close independently even if cleanup raises. Cleanup
  failure emits a fixed structured event, without provider-controlled text.

## Verification boundaries

Real Flask routes and transport orchestration run with synthetic DNS and a
fake TLS pool. Tests cover unsafe URL/IP/DNS answers, numeric pinning, TLS/Host
arguments, proxy/redirect/retry behavior, payload privacy, non-2xx, identities,
DNS timeout/capacity/start failure, cleanup errors and open-mode RBAC.
Mocks validate control flow, **not a real TLS handshake or production setup**.

The initial extended selection passed 176 tests with 100% line/branch coverage
of the new transport. After final identity and test-target corrections, the
security/UX/auto-exclude/guard selection passed 85 tests in 6.03 seconds;
transport coverage remained 100%, with no partial branches in the tested
settings path. Whole-file settings coverage was 61% because other legacy
routes were outside that selection; this is not a patch-coverage estimate.

An independent reviewer inspected the implementation and installed urllib3
source, ran focused suites, and found two MEDIUM issues (raising cleanup and
malformed credentials). Both were fixed and regression-tested. Final extra
RBAC/session cases are revalidated separately. This is not GitHub approval.

The first full run passed 4942 tests but failed the real monkeypatch-target
guard: tests still patched globals removed from the route. The test now
patches the owning `config` module; no guard exemption was added. Failed and
intermediate evidence is retained. A final full run is recorded separately.

Black 25.1.0, Bandit 1.9.4 and Flake8 7.1.1 use the existing CI policy and a
temporary tool directory. No runtime dependency, timeout exclusion or CI
bypass was introduced. The global coverage gate remains 80%.

Real provider, TLS-handshake, hardware and production checks: NOT RUN.
Exact-head remote CI and formal independent approval: required before merge.
No merge, deploy, payment, command or manual Issue closure was performed.
Evidence: `/private/tmp/cypher65-devil-work.7Ltt1O/`.

Final current-tree run on 2026-10-24: **4945 PASS, 4 SKIP**, 644 baseline
warnings, 173.76 seconds, **86.23%** configured coverage, unchanged 80% gate.
The ownership guard passed in this run. Bundle drift, diff, Black 25.1.0,
Flake8 7.1.1 and Bandit 1.9.4 checks also passed. **JS core FAILS** in both
baseline and this branch: the Mini War Room worker-cache regression detects
private-route exclusions lost in feature composition (Issue #863). The final
Energy child-suite summary does not make its parent JS gate pass. This
unrelated failure is not hidden or bypassed. Failed prior logs remain
alongside `verified-webhook-full.log`; no result was overwritten.

## Primary reference

The custom TLS hostname and pool controls follow the official urllib3
[advanced usage](https://urllib3.readthedocs.io/en/stable/advanced-usage.html)
and [pool reference](https://urllib3.readthedocs.io/en/stable/reference/urllib3.connectionpool.html),
also checked against the installed 2.7.0 source.
