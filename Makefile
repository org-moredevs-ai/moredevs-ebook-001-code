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
	@test -d .venv || uv venv --python $(PY_VERSION)
	uv sync --all-extras

.PHONY: setup-min
setup-min: ## Install only common dependencies (no recipe extras)
	@test -d .venv || uv venv --python $(PY_VERSION)
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
demo-r1: ## Recipe 1 — The Eye on the Floor (~2.5 min: replays ~1 day of telemetry)
	@echo "→ Make sure 'make up' is running (TimescaleDB + Mosquitto + Grafana)."
	@echo "→ Replaying ~1 day (1h = 6s) — line 3 (packing) vs lines 1 & 2, so the"
	@echo "  afternoon thermal stoppages on line 3 stand out, just like the field case…"
	uv run python $(R1_N1_DIR)/simulator/replay_to_mqtt.py \
	    --speed-up 600 --duration 144 --sample-period 20 \
	    --machine linha-3.maquina-1 --machine linha-3.maquina-2 \
	    --machine linha-1.maquina-1 --machine linha-2.maquina-1 & \
	uv run python $(R1_N1_DIR)/ingest/mqtt_to_db.py \
	    --max-runtime-seconds 155 & \
	wait
	@echo "→ Open http://localhost:3000 (admin/admin) — dashboard 'Receita 1 N1 — Olho da fábrica'."

R1_N2_DIR := receita-1-olho-da-fabrica/nivel-2-pro

.PHONY: demo-r1-n2
demo-r1-n2: ## Recipe 1 Tier 2 — Modbus + OEE (90s end-to-end demo)
	@echo "→ Make sure 'make up' is running (TimescaleDB + Mosquitto + Grafana)."
	@echo "→ Modbus emulator + collector — line 3 (packing) vs lines 1 & 2, so the OEE"
	@echo "  and the ambient temperature > 27 C on line 3 tell the field-case story…"
	uv run python -m lib_comum.plc_sim.modbus_emulator \
	    --port 1502 --speed-up 600 --duration 90 \
	    --machine linha-3.maquina-1 --machine linha-3.maquina-2 \
	    --machine linha-1.maquina-1 --machine linha-2.maquina-1 & \
	sleep 2 && \
	uv run python $(R1_N2_DIR)/modbus_collector/main.py \
	    --target localhost:1502 \
	    --machine linha-3.maquina-1 \
	    --machine linha-3.maquina-2 \
	    --machine linha-1.maquina-1 \
	    --machine linha-2.maquina-1 \
	    --max-runtime-seconds 80 & \
	wait
	@echo "→ Refreshing OEE continuous aggregates..."
	docker compose exec -T timescaledb psql -U fabrica -d fabrica \
	    -c "CALL refresh_continuous_aggregate('machine_availability_1m', NULL, NULL);" \
	    -c "CALL refresh_continuous_aggregate('machine_availability_1h', NULL, NULL);" || true
	@echo "→ Evaluating Tier 2 alert rules once (availability target 90%, so the thermally-affected line-3 surfaces an alert)..."
	uv run python $(R1_N2_DIR)/alerting/rules.py --once --idle-minutes 1 --availability-target 0.90 || true
	@echo "→ Open http://localhost:3000 — dashboard 'Receita 1 N2 — OEE & Pro'."

R2_N1_DIR := receita-2-maquina-avisa/nivel-1-diy

.PHONY: demo-r2
demo-r2: ## Recipe 2 — The Machine That Warns (90s end-to-end demo)
	@echo "→ Make sure 'make up' is running (TimescaleDB + Mosquitto + Grafana)."
	@echo "→ Starting vibration simulator + FFT alert receiver for ~90s..."
	@echo "→ Warmup covers healthy days, then the wear ramp: the 83 Hz BPFO band grows."
	uv run python $(R2_N1_DIR)/simulator/replay_to_mqtt.py \
	    --speed-up 14400 --duration 85 --start-offset-days 14 --sample-period-s 600 & \
	sleep 1 && \
	uv run python $(R2_N1_DIR)/fft_alert/receiver.py \
	    --max-runtime-seconds 90 --threshold-pct 40 \
	    --baseline-window 30 --warmup-samples 20 \
	    --cooldown-seconds 3 --min-amplitude-g 0.005 & \
	wait
	@echo "→ Open http://localhost:3000 — dashboard 'Receita 2 N1 — Vibração & FFT'."

R2_N2_DIR := receita-2-maquina-avisa/nivel-2-pro

.PHONY: demo-r2-n2
demo-r2-n2: ## Recipe 2 Tier 2 — Isolation Forest anomaly detector (90s end-to-end demo)
	@echo "→ Make sure 'make up' is running (TimescaleDB + Mosquitto + Grafana)."
	@echo "→ Starting vibration simulator + feature extractor + IF detector for ~90s..."
	@echo "→ Warmup covers 4 healthy days, then the wear ramp: RMS ~0.45 -> ~1.3 g and"
	@echo "  kurtosis ~3 -> ~11 as the bearing fault develops, so the anomaly lights up."
	uv run python $(R2_N1_DIR)/simulator/replay_to_mqtt.py \
	    --speed-up 14400 --duration 85 --start-offset-days 14 --sample-period-s 600 & \
	sleep 1 && \
	uv run python $(R2_N2_DIR)/feature_extractor/extractor.py \
	    --max-runtime-seconds 92 & \
	sleep 2 && \
	uv run python $(R2_N2_DIR)/isoforest_detector/detector.py \
	    --max-runtime-seconds 92 --warmup-window 20 \
	    --alert-threshold 0.0 --cooldown-seconds 3 & \
	wait
	@echo "→ Open http://localhost:3000 — dashboard 'Receita 2 N2 — Anomalia (Isolation Forest)'."

.PHONY: demo-r3
demo-r3: ## Recipe 3 — The Quote Writer (Streamlit UI)
	@echo "→ Opens the Streamlit UI on http://localhost:8501"
	@echo "→ Set ANTHROPIC_API_KEY for the live Claude path; otherwise it falls back to the offline regex provider."
	uv run streamlit run receita-3-orcamentista/nivel-1-diy/quote_writer/app.py

.PHONY: demo-r3-cli
demo-r3-cli: ## Recipe 3 — Quote writer CLI (no UI, offline provider by default)
	LLM_PROVIDER=$${LLM_PROVIDER:-offline} \
	uv run python receita-3-orcamentista/nivel-1-diy/quote_writer/pipeline.py --provider $${LLM_PROVIDER:-offline}

.PHONY: demo-r3-n2
demo-r3-n2: ## Recipe 3 Tier 2 — review pipeline with quote memory (offline by default)
	LLM_PROVIDER=$${LLM_PROVIDER:-offline} \
	uv run python receita-3-orcamentista/nivel-2-pro/quote_review/pipeline.py --provider $${LLM_PROVIDER:-offline}

.PHONY: demo-r3-n2-ui
demo-r3-n2-ui: ## Recipe 3 Tier 2 — human review UI (Streamlit)
	@echo "→ Opens the review UI on http://localhost:8501 (Aprovar / Rejeitar)."
	uv run streamlit run receita-3-orcamentista/nivel-2-pro/quote_review/app.py

.PHONY: demo-r4
demo-r4: ## Recipe 4 — The Cut That Doesn't Waste
	uv run streamlit run receita-4-corte-sem-desperdicio/nivel-1-diy/app.py

.PHONY: demo-r5
demo-r5: ## Recipe 5 — The Delivery Promise
	uv run streamlit run receita-5-promessa-prazo/nivel-1-diy/app.py

##@ Quality

.PHONY: test
test: ## Run unit tests (excludes integration + slow)
	uv run pytest -m "not integration and not slow"

.PHONY: test-slow
test-slow: ## Run unit tests including the slow ones (full datasets)
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
