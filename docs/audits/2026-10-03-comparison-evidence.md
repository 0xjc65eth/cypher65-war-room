# C65-06–07: comparison evidence (Issue #733)

Base: master 39fa95b5833ea0f61c8f578df1cabb388d8a61e4. Production observed 03/10/2026 Europe/Brussels: Fleet reported 82.2 TH/s versus 3.19 EH/s observed, deviation -100%; Hash Market labeled SOLO best while pool and lease estimates were absent.

Cause: the UI averaged realized share-difficulty divided by interarrival time from the ticker. This is not an estimate from assigned work over a known window for the same worker. No matching worker/window estimator is present in this API contract. The decision matrix ranked a single probabilistic strategy without financial alternatives.

Fix: retain reported hashrate, show observed/deviation as unavailable and explain the matching-window requirement. Do not invent an estimator. Rank pool versus lease only when both finite daily estimates exist; keep solo probability/model mean informative, never a guaranteed deadline. The browser also rejects legacy SOLO winners or incomplete alternative rows. Invalid probabilities and negative model times remain unavailable; zero remains a number.

Validation: six independent Python regressions failed before; focused suite 129 passed after. Real-source JS regression failed with the EH/s estimate and -100%; 1563 JS assertions passed after. Playwright legacy-payload regression passed in desktop and mobile. Full CI Python coverage scope: 4114 passed, 1 skipped, 85.47%; 555 existing/dependency warnings retained. Combined frontend pipeline is recorded in the delivery report.

Self-review (not independent GitHub approval): Data — entity/window/unit mismatch guarded, no source freshness claimed; Frontend — textContent only, absent state replaces stale winner; Security — no account or command changes; QA — tests load real code, browser exercises legacy API response. No new animation. Limitation: valid observed comparison requires future assigned-difficulty telemetry with entity and window provenance. Financial models are estimates, not investment or profit guarantees. Rollback by a reviewed revert PR; merge/deploy and independent approval remain pending.
