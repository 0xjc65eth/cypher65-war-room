# Cypher65 War Room — quick commands.
# Uses Docker Compose v2 (`docker compose`), matching install.sh / run.sh.
.PHONY: help build up down logs test lint lint-sec format clean clean-data

help:
	@echo "Cypher65 War Room — quick commands"
	@echo "  make build      - Build the Docker image"
	@echo "  make up         - Start the stack (http://localhost:8765)"
	@echo "  make down       - Stop containers (keeps volumes + SQLite data)"
	@echo "  make logs       - Tail container logs"
	@echo "  make test       - Run the full pytest suite in the venv"
	@echo "  make lint       - Advisory flake8/black (non-blocking)"
	@echo "  make lint-sec   - Static security gates: bandit -ll + flake8 bug-codes + black (BLOCKING no CI)"
	@echo "  make format     - Roda black no escopo do gate (Issue #133)"
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

# Estilo completo (flake8 E/W + black) — advisory por escopo amplo (o gate
# do CI usa só os bug-codes F821/F541/E9 + black no escopo lint-sec). A
# formatação black do repositório foi commitada na Issue #133 — aqui o
# black roda sem bloquear para o fluxo local.
lint:
	@echo "⚠️  Advisory lint (estilo completo) — não é gate"
	-flake8 core/ routes/ services/ axe_fleet/ --count --max-complexity=12 --statistics
	-black --check core routes services axe_fleet

# Reformatar o escopo do gate (Issue #133) — roda black em tudo que o CI
# verifica, antes de commitar. Depois valide com `make lint-sec`.
format:
	@test -d .venv || (echo "no .venv — run ./run.sh once first" && exit 1)
	.venv/bin/python -m black app.py helpers.py solo_mining.py services core axe_fleet routes agents

# Static security gates (Issues #125 + #133) — EXACTAMENTE o que o CI
# bloqueia: bandit -ll (medium+), flake8 .flake8 (F821/F541/E9) e black
# (reformatado no commit dedicado #133 — agora é gate real).
# Usa o venv (igual `make test`). Deps: pip install -r requirements-dev.txt.
lint-sec:
	@test -d .venv || (echo "no .venv — run ./run.sh once first" && exit 1)
	@echo "🔐 Static security gates (bandit + flake8 + black)"
	.venv/bin/python -m bandit -r services core axe_fleet routes agents app.py helpers.py solo_mining.py -ll -q
	.venv/bin/python -m flake8 app.py helpers.py solo_mining.py services core axe_fleet routes agents
	.venv/bin/python -m black --check app.py helpers.py solo_mining.py services core axe_fleet routes agents

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
