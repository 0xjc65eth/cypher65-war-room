# P0.4 — REFACTORING PLAN (Gradual & Safe)

## Current State
- `app.py`: 1654 lines (monolith)
- ~50 routes mixed with business logic
- Polling, DB, auth, and UI logic all in one file

## Refactoring Strategy

### Phase 1 (Current) — Foundation
- Extract configuration → `config.py`
- Extract auth middleware → `auth.py` (done)
- Create `services/` structure (already partially done)

### Phase 2 — Routes
- Move all `@app.route` to `routes/` package
- Keep only app initialization in `app.py`

### Phase 3 — Services
- Move business logic from `app.py` to `services/`
- `services/mining.py`
- `services/pool.py`
- `services/alerts.py`

### Phase 4 — Models & Repositories
- Create proper data access layer

## Rules
- Never break the running system
- One extraction at a time
- Add tests before moving critical logic
- Update imports carefully

## Current Action
Starting with configuration extraction.