# Cypher65 War Room — quick commands.
# Uses Docker Compose v2 (`docker compose`), matching install.sh / run.sh.
.PHONY: help build up down logs test lint clean clean-data

help:
	@echo "Cypher65 War Room — quick commands"
	@echo "  make build      - Build the Docker image"
	@echo "  make up         - Start the stack (http://localhost:8765)"
	@echo "  make down       - Stop containers (keeps volumes + SQLite data)"
	@echo "  make logs       - Tail container logs"
	@echo "  make test       - Run the full pytest suite in the venv"
	@echo "  make lint       - Advisory flake8/black (non-blocking)"
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
# the CI workflow only after a dedicated cleanup commit.
lint:
	@echo "⚠️  Advisory lint — not a gate"
	-flake8 core/ routes/ services/ axe_fleet/ --count --max-complexity=12 --statistics || true
	-black --check core routes services axe_fleet || true

clean:
	docker compose down -v
	@echo "⚠️  Volumes removed. SQLite data was NOT deleted — use 'make clean-data' to do that."

# Destructive by design — the SQLite files hold the device registry and all
# history. Never run this without a backup.
clean-data:
	@echo "⚠️  Deleting SQLite databases — this destroys the device registry + history!"
	@read -p "Type 'yes' to confirm: " ans; [ "$$ans" = "yes" ] || { echo "aborted"; exit 1; }
	rm -f data/*.db data/*.sqlite
	@echo "Done."
