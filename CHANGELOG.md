# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial repository scaffolding: structure for 5 recipes, base Docker stack (TimescaleDB + Mosquitto + Grafana), uv-based Python project, Makefile, dev container, GitHub Actions CI.
- `lib_comum.data_synth.alimentar`: synthetic data generator for the food-processing case study used by Recipe 1. Produces machine state events, ambient sensor readings, and hourly production counters across 30 days, with the deterministic line-3 thermal-protection signal embedded for discovery from SQL.
- `tools.seed_synth_data`: CLI orchestrator (`make seed-data`).
- Test suite for the alimentar generator (determinism, schemas, case-study signal correlation).
- `.gitignore` now excludes regenerable datasets under `**/data-exemplo/**`.
- **Recipe 1 Tier 1 (DIY) end-to-end.** The pipeline described in Chapter 1 is now real, runnable code:
  - `telemetry` hypertable: SQL init script with 1-day chunk interval, compound index, and a 7-day compression policy.
  - `lib_comum.db`: async Postgres helpers (DSN resolution, batch inserts, `fetch_recent_state` matching the manuscript's SQL, truncation for tests).
  - `lib_comum.mqtt`: paho 2.x wrapper, canonical topic helper (`fabrica/<line>/<machine>/<metric>`), JSON payload codec.
  - `receita-1.../nivel-1-diy/ingest/mqtt_to_db.py`: MQTT subscriber → batched INSERT, signal-handled clean shutdown, `--demo` / `--max-runtime-seconds` options.
  - `receita-1.../nivel-1-diy/simulator/replay_to_mqtt.py`: replays the alimentar dataset over MQTT at configurable speed-up, replacing the physical ESP32 boards in demos and tests.
  - `receita-1.../nivel-1-diy/firmware-esp32/`: real PlatformIO project — ESP32 + SCT-013, MQTT + WiFi + auto-reconnect, ArduinoJson payload, secrets handled via gitignored `secrets.ini`.
  - `receita-1.../nivel-1-diy/grafana-dashboards/n1-overview.json`: 3-panel dashboard (current per machine, current state, hourly stopped-fraction heatmap) auto-provisioned at `/var/lib/grafana/dashboards/receita-1-n1`.
- `tests/test_r1_n1_e2e.py`: integration test that spawns the simulator and ingest as subprocesses, then verifies rows land in `telemetry` and that `fetch_recent_state` returns valid states. Marked `integration`; skipped if the stack isn't reachable.
- `make demo-r1`: runs the simulator + ingest in parallel for 90 seconds against a live stack.
- PT and EN READMEs for Recipe 1 Tier 1 (bill of materials, demo recipe, hardware-vs-simulator instructions, database schema).

### Changed
- `docker-compose.yml`: Grafana now receives `POSTGRES_USER/PASSWORD/DB` so the provisioned TimescaleDB datasource can authenticate. Mounts the R1 N1 dashboard folder read-only.
- `lib_comum/grafana/provisioning/datasources/timescaledb.yml`: switched from `${VAR:-default}` (a docker-compose syntax Grafana doesn't honour) to `$VAR`, with defaults provided by docker-compose itself.
- `lib_comum/grafana/provisioning/dashboards/dashboards.yml`: dashboard provider now points at `/var/lib/grafana/dashboards` (the conventional location, separate from the provisioning config tree).
- `pyproject.toml`: dropped `types-paho-mqtt` (stubs trail paho 2.x); we rely on `ignore_missing_imports = true` instead.
