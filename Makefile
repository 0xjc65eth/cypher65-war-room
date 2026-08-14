# Cypher65 War Room — quick commands.
# Uses Docker Compose v2 (`docker compose`), matching install.sh / run.sh.
.PHONY: help build up down logs test lint lint-sec clean clean-data

help:
	@echo "Cypher65 War Room — quick commands"
	@echo "  make build      - Build the Docker image"
	@echo "  make up         - Start the stack (http://localhost:8765)"
	@echo "  make down       - Stop containers (keeps volumes + SQLite data)"
	@echo "  make logs       - Tail container logs"
	@echo "  make test       - Run the full pytest suite in the venv"
	@echo "  make lint       - Advisory flake8/black (non-blocking)"
	@echo "  make lint-sec   - Static security gates: bandit -ll + flake8 bug-codes (BLOCKING no CI)"
	@echo "  make clean      - Stop containers and remove volumes"
	@echo "  make clean-data - DELETE the SQLite databases (device registry!)"

build:
	docker compose build

up:
	docker compose up -d --build
	@echo "✅ Acesse http://localhost:8765"

down:
	docker compose down

logs:
	docker compose logs -f

test:
	@test -d .venv || (echo "no .venv — run ./run.sh once first" && exit 1)
	.venv/bin/python -m pytest tests/ -q

# Advisory: the codebase is not lint-clean yet (814 flake8 violations / 43
# files needing black). These must never block local work — flip the gate in
# the CI workflow only after a dedicated cleanup commit (Issue #133).
lint:
	@echo "⚠️  Advisory lint — not a gate"
	-flake8 core/ routes/ services/ axe_fleet/ --count --max-complexity=12 --statistics
	-black --check core routes services axe_fleet

# Static security gates (Issue #125) — EXACTAMENTE o que o CI bloqueia.
# bandit -ll (medium+) e flake8 com .flake8 (F821/F541/E9) precisam passar;
# black é advisory até o cleanup dedicado (Issue #133).
# Usa o venv (igual `make test`). Deps: pip install -r requirements-dev.txt.
lint-sec:
	@test -d .venv || (echo "no .venv — run ./run.sh once first" && exit 1)
	@echo "🔐 Static security gates (bandit + flake8 bug-codes)"
	.venv/bin/python -m bandit -r services core axe_fleet routes agents app.py helpers.py solo_mining.py -ll -q
	.venv/bin/python -m flake8 app.py helpers.py solo_mining.py services core axe_fleet routes agents
	@echo "✅ Gates verdes — black advisory (backlog Issue #133):"
	@-.venv/bin/python -m black --check app.py helpers.py solo_mining.py services core axe_fleet routes agents 2>&1 | tail -1

clean:
	docker compose down -v
	@echo "⚠️  Volumes removed. SQLite data was NOT deleted — use 'make clean-data' to do that."

# Destructive by design — the SQLite files hold the device registry and all
# history. Never run this without a backup.
clean-data:
	@echo "⚠️  Deleting SQLite databases — this destroys the device registry + history!"
	@read -p "Type 'yes' to confirm: " ans; [ "$$ans" = "yes" ] || { echo "aborted"; exit 1; }
	# Also remove WAL/SHM sidecars — deleting only the .db while a -wal/-shm
	# survives leaves SQLite in an inconsistent state on next boot.
	rm -f data/*.db data/*.sqlite data/*.db-wal data/*.sqlite-wal data/*.db-shm data/*.sqlite-shm
	@echo "Done."
