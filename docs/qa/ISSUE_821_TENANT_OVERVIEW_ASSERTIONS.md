# Issue #821 — timestamp-independent tenant privacy assertion

Base `a121276f00c20feff5a9f06d3854eda911b35dcf`, 2026-10-11. This unit changes only a security regression test; production payload filtering, overview composition, JWT, guards and dependencies are unchanged.

## Demonstrated cause

PR820 head `a57af26fcbf29afbf61603ad4c2e017350edc038`, [Unit Tests job](https://github.com/0xjc65eth/cypher65-war-room/actions/runs/38151406220/job/114505462934), failed at `assert "65" not in str(overview)`. The public timestamp `1791732659` contains that substring. Mining/economics signals were empty and private top-level fields absent; this result demonstrates a brittle assertion rather than a private telemetry leak.

The real Flask route and real overview builder now run at explicit evidence timestamps `1791732659` and `1791732700`. Only the builder binding used by the route receives its supported `now` argument; system time and JWT issuance/expiry remain real. Both `as_of` and network `observed_at` are asserted, so removing timestamps cannot make the regression pass.

The test retains every top-level private-key exclusion, tenant/data scope, missing mining/economics status, empty economics signals and private worker-name exclusion. It also requires empty mining signals and absence of the private wallet marker, and walks numeric leaves to exclude the fixture's private hashrate65/account999 as values rather than substrings. This remains a fixture-specific privacy check, not a blanket certification of all tenant behavior.

## Validation

- Before replacing the brittle assertion, deterministic cases: **1 FAIL / 1 PASS**; only the timestamp containing65 failed.
- Corrected tenant B2 test file: **16 PASS**.
- Complete Python suite using CI production coverage targets: **4471 PASS / 2 SKIP**, 289.04 s, **85.81%** (gate80), exit0.
- Monkeypatch-target guard and `git diff --check`: **PASS**.
- /advisor independently reran the file: **16 PASS**; verified real JWT and the correct route binding.
- /devil independently reran **16 PASS** and injected four private-data mutations through the real route: hash65 in mining, hash65 in another domain, account999 in another domain, account999 in a nested anomaly. Both timestamps rejected each mutation: **8 expected failures**. No CRITICAL/HIGH/MEDIUM residual demonstrated in this delta. Technical reviews are not GitHub approval.

A deliberately reordered related 11-file selection returned **7 FAIL / 159 PASS**, due to settings fixture JWT configuration persisting into export tests. The reduced settings→export selection reproduced **7 FAIL / 20 PASS on unmodified master**; auth→export alone passed33. That independent fixture defect is tracked and repaired separately in Issue #822. It was not hidden by relabeling the subset green, and it did not fail the standard full suite above.

Logs: `/tmp/c65-820-unit-fail.log`, `/tmp/c65-821-before.log`, `/tmp/c65-821-focused.log`, `/tmp/c65-821-full.log`, `/tmp/c65-821-contracts.log`, `/tmp/c65-821-baseline-settings-order.log`. Temporary logs are not remote artifacts.

Remote exact-head CI remains authoritative after publication. At original publication this branch inherited the mobile blocker; PR820 was subsequently integrated externally as f5dde52 and the branch reconciled with that base. No merge, deploy, manual Issue closure, production secrets or physical operations were performed.
