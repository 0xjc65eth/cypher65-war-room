# C65-08: cloud seed gate (Issue #734)

Base: master 39fa95b5833ea0f61c8f578df1cabb388d8a61e4. Public Fleet displayed SEED TEST. It was not pressed in production. Visibility alone did not prove an exploitable endpoint: tenant/member authorization and DEBUG_MOCK checks already existed.

Fix: remove the always-visible seed button from the public shell. Deny /api/axe-fleet/test-devices on any deployment detected by the existing cloud detector, even with DEBUG_MOCK=1. Preserve tenant/member checks and local developer seeding. No simulated devices or physical commands were sent to production.

Validation: four cloud-flag cases and public-shell regression failed before (5 failures), passed after; route suite 75 passed. Cloud tests assert rejection before registry access or insertion. Black, flake8, Bandit, DOM guard and diff checks passed. Full Python CI-scope coverage results are recorded in the delivery report.

Self-review (not independent approval): Security — deny before registry operations, existing auth retained; Backend — reuse central cloud detection, no DB/schema migration; Frontend — remove unused UI control without replacing it with a simulated workflow; QA — both positive local path and negative cloud/auth cases run in disposable test state. Remaining limitation: unmarked custom production deployments must set CLOUD_MODE; automatic Render flags are recognized. Rollback via reviewed revert PR, preserving the cloud restriction until equivalent protection is available. Merge/deploy and independent review remain pending.
