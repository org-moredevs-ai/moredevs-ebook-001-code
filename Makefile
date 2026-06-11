.DEFAULT_GOAL := help
SHELL := /bin/bash

# Tunables
PY_VERSION ?= 3.13
COMPOSE := docker compose

##@ Help

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Setup

.PHONY: setup
setup: ## Create virtualenv with uv and install dependencies
	uv venv --python $(PY_VERSION)
	uv sync --all-extras

.PHONY: setup-min
setup-min: ## Install only common dependencies (no recipe extras)
	uv venv --python $(PY_VERSION)
	uv sync

##@ Stack

.PHONY: up
up: ## Start the base stack (TimescaleDB + Mosquitto + Grafana)
	$(COMPOSE) up -d
	@echo ""
	@echo "Stack is up. Open:"
	@echo "  Grafana:     http://localhost:3000  (admin/admin)"
	@echo "  TimescaleDB: localhost:5432"
	@echo "  Mosquitto:   localhost:1883"

.PHONY: down
down: ## Stop the base stack
	$(COMPOSE) down

.PHONY: ps
ps: ## Show running containers
	$(COMPOSE) ps

.PHONY: logs
logs: ## Tail logs of all services
	$(COMPOSE) logs -f --tail=100

.PHONY: nuke
nuke: ## Stop everything and delete volumes (DESTRUCTIVE)
	$(COMPOSE) down -v

##@ Data

.PHONY: seed-data
seed-data: ## Generate synthetic data for all recipes
	uv run python -m tools.seed_synth_data --all

##@ Demos

R1_N1_DIR := receita-1-olho-da-fabrica/nivel-1-diy

.PHONY: demo-r1
demo-r1: ## Recipe 1 — The Eye on the Floor (90s end-to-end demo)
	@echo "→ Make sure 'make up' is running (TimescaleDB + Mosquitto + Grafana)."
	@echo "→ Starting simulator + ingest in parallel for 90s..."
	uv run python $(R1_N1_DIR)/simulator/replay_to_mqtt.py \
	    --speed-up 600 --duration 80 --limit-machines 5 & \
	uv run python $(R1_N1_DIR)/ingest/mqtt_to_db.py \
	    --max-runtime-seconds 90 & \
	wait
	@echo "→ Open http://localhost:3000 (admin/admin) — dashboard 'Receita 1 N1 — Olho da fábrica'."

.PHONY: demo-r2
demo-r2: ## Recipe 2 — The Machine That Warns
	uv run python -m receita-2-maquina-avisa.nivel-1-diy.fft_alert --demo

.PHONY: demo-r3
demo-r3: ## Recipe 3 — The Quote Writer
	uv run streamlit run receita-3-orcamentista/nivel-1-diy/app.py

.PHONY: demo-r4
demo-r4: ## Recipe 4 — The Cut That Doesn't Waste
	uv run streamlit run receita-4-corte-sem-desperdicio/nivel-1-diy/app.py

.PHONY: demo-r5
demo-r5: ## Recipe 5 — The Delivery Promise
	uv run streamlit run receita-5-promessa-prazo/nivel-1-diy/app.py

##@ Quality

.PHONY: test
test: ## Run unit tests
	uv run pytest -m "not integration"

.PHONY: test-integration
test-integration: ## Run integration tests (requires `make up`)
	uv run pytest -m integration

.PHONY: test-all
test-all: ## Run all tests including integration
	uv run pytest

.PHONY: lint
lint: ## Run linters (ruff + mypy)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy lib_comum

.PHONY: format
format: ## Auto-format code with ruff
	uv run ruff format .
	uv run ruff check --fix .

##@ Verification

.PHONY: verify-ebook-sync
verify-ebook-sync: ## Verify ebook ↔ code snippet sync (cap=N optional)
	uv run python -m tools.verify_ebook_sync $(if $(cap),--cap $(cap),)

##@ Cleanup

.PHONY: clean
clean: ## Remove caches and build artefacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov dist build *.egg-info
