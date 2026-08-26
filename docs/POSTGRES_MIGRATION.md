# Postgres migration gate

Issue [#22](https://github.com/0xjc65eth/cypher65-war-room/issues/22) is a
traction gate, not authorization to change the production database. SQLite plus
the pinned private-Gist backup remains the source of truth until every condition
below is evidenced.

## Decision rule

Begin a real rehearsal after **10 active paid PRO/PREMIUM licenses**. Only
licenses issued by `btcpay`, `lemon_squeezy`, or `webln` count; manual, test,
revoked, expired, and free-plan rows do not. This uses a durable business event
already stored in `pro_licenses`, instead of page views or anonymous boots that
can be inflated.

Monitor the gate without changing the database:

```bash
python scripts/postgres_readiness.py --db data/war_room.sqlite
```

The deployed operator can monitor the same redacted decision through
`GET /api/admin/postgres-readiness`. It uses the existing admin gate: a real
localhost request or a valid operator `X-API-Key`; proxied anonymous requests
receive HTTP 403. This endpoint returns no schema rows or credential values.

The report contains counts and booleans only. It never prints a license key,
email, GitHub token, Gist ID, or Postgres DSN. `decision=hold` means do not add
infrastructure. `ready-for-rehearsal` means only that the threshold and
credentials exist; it never authorizes cutover.

Current local evidence (2026-08-26): the checked database has schema version 4,
passes SQLite integrity validation, and contains 0 active provider-paid
licenses. This is local operator evidence, not a claim about an unavailable
production database.

## Schema map and portability boundary

`services.schema.CURRENT_SCHEMA_VERSION` is the side-effect-free source for the
expected revision; `app.py` keeps the legacy `SCHEMA_VERSION` alias. Generate a
column-level inventory from the database being rehearsed:

```bash
python scripts/postgres_readiness.py \
  --db data/war_room.sqlite \
  --include-schema-map > /tmp/cypher65-postgres-readiness.json
```

The inventory maps SQLite affinities as follows. It is an audit artifact, not
executable DDL:

| SQLite | Candidate Postgres | Required check |
|---|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGINT ... AS IDENTITY` | sequence is above migrated max ID |
| `INTEGER` boolean fields | `BOOLEAN` | every source value is 0, 1, or NULL |
| `INTEGER` epoch fields | `BIGINT` initially | timezone conversion verified before `TIMESTAMPTZ` |
| `REAL` | `DOUBLE PRECISION` | NaN/Infinity policy and financial precision reviewed |
| `TEXT` | `TEXT` | timestamps/JSON validated before specialized types |
| `BLOB` | `BYTEA` | byte length and digest match |

The existing access helper is not backend-neutral today. It returns
`sqlite3.Connection`, applies PRAGMAs, and callers use SQLite placeholders and
date functions. The first Postgres implementation must therefore extend the
existing `services.db` boundary and migrate callers incrementally; changing
`DATABASE_URL` alone is prohibited. Registry factories can reuse that boundary,
but direct SQL in `app.py` and services remains a tracked blocker.

## Real Gist rehearsal

The source must be an explicitly pinned private Gist. This avoids silently
creating a new empty Gist during a readiness check:

```bash
export GITHUB_TOKEN='<gist-read-token>'
export REMOTE_BACKUP_GIST_ID='<existing-private-gist-id>'
export POSTGRES_DSN='<temporary-empty-neon-or-supabase-dsn>'
python scripts/postgres_readiness.py --source-gist --include-schema-map
```

The command only downloads, decodes, and checks the source snapshot. It does
not write to Postgres. A subsequent migration PR must provide a repeatable
loader and compare, at minimum, table/row counts, primary keys, foreign-key
checks, schema digest, sampled row digests, sequences, and application read/write
flows against an isolated target. Set `RUN_REAL_GIST_TEST=1` only in a protected
job with the pinned-Gist credentials to run the real integration test.

## Cutover criteria and rollback

Do not cut over until all of these are true:

1. Traction is at or above 10 active paid licenses.
2. The pinned Gist source is intact and at the current schema version.
3. A disposable Postgres target completed the real-data rehearsal with no
   count, key, digest, timezone, or sequence mismatch.
4. The application data-access boundary supports both backends and the full
   Python, frontend, E2E, backup, tenant-isolation, and command-safety suites
   pass on Postgres.
5. A maintenance window, final SQLite snapshot, write freeze, reconciliation,
   observability dashboard, and rollback owner are recorded.

Rollback is a configuration rollback only after writes are frozen and the
Postgres delta is reconciled back to the final SQLite snapshot. Never point the
app at the old SQLite file after accepting unreconciled Postgres writes.

## Kill criteria

Pause or reduce scope when the paid-license threshold is not met, the source
snapshot is corrupt/stale, schema versions differ, any tenant boundary fails,
row or digest reconciliation is non-zero, or p95 latency/error rate regresses in
the rehearsal. Missing credentials are a blocker, not permission to use
fixtures as “real” evidence.
