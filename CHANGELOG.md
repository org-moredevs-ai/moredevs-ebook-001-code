# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Recipe 2 Tier 2 (Pro) — Isolation Forest anomaly detection + multi-channel alerts.** Real end-to-end ML pipeline on top of the Tier 1 raw-vibration feed.
  - `lib_comum.alerting`: Apprise wrapper resolving `APPRISE_URLS` (Telegram, email, Slack, MS Teams). Degrades gracefully (log-only) when nothing is configured, so demos and tests stay deterministic.
  - `lib_comum/sql/init/05_vibration_features.sql`: new `vibration_features` hypertable (rms, peak, crest, kurtosis, dominant freq, 1× band, BPFO band, plus optional `anomaly_score`). Daily chunks + 7-day compression.
  - `lib_comum.db`: `VibrationFeatureRow` + `insert_vibration_features` helpers. `truncate_vibration_tables` now empties the new table too.
  - `receita-2-.../nivel-2-pro/feature_extractor/extractor.py`: stateless MQTT subscriber that runs FFT + statistics per snapshot, persists 21 features (7 × 3 axes) to `vibration_features`, and re-publishes the same vectors on `fabrica/<line>/<machine>/vibration-features` so multiple downstream models can consume them in parallel.
  - `receita-2-.../nivel-2-pro/isoforest_detector/detector.py`: per-machine IsolationForest (`n_estimators=80`, `contamination=0.05`). Warms up on the first 20 healthy snapshots, **freezes** the model (the default `--refit-every 0` prevents slow wear from being absorbed as the new normal), then scores every new vector. Negative scores below `--alert-threshold` fire alerts into `vibration_alerts` with `band='anomaly'` plus an Apprise dispatch with severity-scaled escalation.
  - `receita-2-.../nivel-2-pro/grafana-dashboards/n2-anomaly.json`: 4-panel dashboard (worst score per machine as a gauge, BPFO timeseries, crest-factor timeseries, recent alerts table) auto-provisioned via `docker-compose.yml`.
  - `make demo-r2-n2`: orchestrates simulator + extractor + detector for ~75 s (14 400× speed-up so the full 12-day wear arc — plus 4 healthy days of warmup — plays out in just over a minute).
  - `tests/test_r2_n2_e2e.py`: integration test asserting features land, the press dominates "warning" severity by at least 3× the next machine, and the most-anomalous score belongs to the press. Passes in ~63 s.
  - PT and EN READMEs covering the architecture, the 21-feature vector, why the model is frozen by default, Apprise wiring, and Tier 2 limits.

- **Recipe 2 Tier 1 (DIY) — ESP32 + ADXL345 vibration pipeline + Python FFT alerts.** Real end-to-end implementation of the Chapter 2 case study (Marinha Grande moulds, press-1 bearing developing a fault over 11+ days).
  - `lib_comum.plc_sim.vibration_signal`: deterministic 1-second 3-axis waveform synthesiser at 1 kHz. Healthy machines carry the 1× rotation harmonic + low-frequency noise; the fault-seeded press also gets a growing BPFO sinusoid, amplitude-modulated sidebands at BPFO ± rotation, and exponentially-decaying impulses at the bearing rate.
  - `lib_comum.plc_sim.vibration_signal.compute_spectrum_band_amp`: convenience that runs `numpy.fft.rfft` and returns the RMS amplitude in a band; reused by the receiver and the tests.
  - `receita-2-.../nivel-1-diy/simulator/replay_to_mqtt.py`: publishes 1-second snapshots per simulated minute over MQTT (`fabrica/<line>/<machine>/vibration`) for every moulds machine.
  - `receita-2-.../nivel-1-diy/fft_alert/receiver.py`: MQTT subscriber that runs FFT per snapshot, persists per-band amplitudes to `vibration_bands`, and fires alerts when the BPFO band climbs above a **frozen-after-warmup** baseline. Severity escalates with the ratio; min-amplitude floor prevents noise-band false positives on quiet machines.
  - `receita-2-.../nivel-1-diy/firmware-esp32/`: real PlatformIO project (ESP32 + ADXL345 over I²C, MQTT + WiFi auto-reconnect, ArduinoJson payload with the 1000-sample × 3-axis buffer, gitignored secrets).
  - `receita-2-.../nivel-1-diy/grafana-dashboards/n1-vibration.json`: 4-panel dashboard (BPFO timeseries per machine, 1× rotation timeseries, recent alerts table, per-machine spectral fingerprint).
  - `lib_comum/sql/init/04_vibration.sql`: `vibration_bands` and `vibration_alerts` hypertables with the same chunk-and-compress strategy as `telemetry`.
  - `lib_comum.db`: `VibrationBandRow`, `VibrationAlertRow`, `insert_vibration_bands`, `insert_vibration_alert`, `truncate_vibration_tables` helpers.
  - `tests/test_vibration_signal.py`: 7 fast tests covering shape/payload, determinism, healthy-vs-faulty BPFO growth, neighbour-isolation, in-band tone verification, and 1× persistence through wear.
  - `tests/test_r2_n1_e2e.py`: integration test spawning simulator + receiver; asserts rows land in `vibration_bands`, that BPFO alerts fire, and that **every alert is on press-1** (zero false positives across the other 5 machines).
  - `make demo-r2`: orchestrates a 60-second end-to-end demo (4320× speed-up so the full 12-day wear arc plays out in a minute).
  - PT and EN READMEs covering BOM, demo, architecture, MQTT contract, receiver behaviour, and Tier 1 limits.

### Changed
- `docker-compose.yml`: Grafana now mounts the R2 N1 dashboard folder. The dashboards "Receita 1 N1 / N2" and "Receita 2 N1 — Vibração & FFT" are all auto-provisioned.

- **Recipe 1 Tier 3 (Premium) — reference architecture.** PT and EN READMEs with the multi-site / Edge AI / ERP integration diagram, sizing guidance for the data lake, ERP-specific connector strategy (Primavera, PHC, Sage X3, SAP B1), and the NIS2 + EU AI Act + IATF 16949 / ISO 9001 / FSSC 22000 obligations relevant at this tier. Plus the consultancy ladder (diagnostic → pilot → multi-site → retainer) and EU funding pointers.
- **Recipe 2 foundation — `moldes` synthetic dataset.** `lib_comum.data_synth.moldes` generates a Marinha Grande mould-making roster (1× 250 t press, 3× CNC mills, 2× EDMs) over 30 days. Beyond the usual `machine_states` / `sensor_readings` / `production_events`, it produces a new `vibration_metrics` table — per-minute, 3-axis RMS / peak / kurtosis / dominant_freq_hz. The fault-seeded press-1 develops a bearing wear signal over the last 12 days (RMS grows ~3× on running samples; dominant frequency drifts from 25 Hz toward the 83 Hz BPFO band; kurtosis climbs). The signal is discoverable from FFT (Chapter 2 Tier 1) and from Isolation Forest (Tier 2). Validated end-to-end: `make seed-data` writes ~5 MB of parquet for 30 days; case_summary reports the RMS gain (e.g. 13.4×).
- `lib_comum.data_synth.schemas`: `VIBRATION_METRICS_COLUMNS` / `_DTYPES` canonical schema shared by every recipe that needs vibration roll-ups.
- `tools.seed_synth_data --all` now generates `moldes` too.
- Tests: 11 new tests in `tests/test_data_synth_moldes.py` covering schema, determinism, case-study signal isolation (signal climbs only on the press), dominant-frequency drift, fault event placement, and family-aware production rates. The 4 tests that need the full 30-day dataset (~30 s of generation) are tagged `slow` and excluded from `make test`.

### Changed
- `make test` excludes `slow` (now ~12 s for the fast suite); `make test-slow` runs the long tests too. CI runs the fast subset.
- CI mypy and pytest steps are no longer `continue-on-error`; lib_comum is mature enough to enforce both.

- **Recipe 1 Tier 2 (Pro) — Modbus pipeline and OEE end-to-end.**
  - `lib_comum.plc_sim.state_clock.SimClock`: shared compressed-time clock used by every PLC emulator, so emulators (Modbus today, OPC-UA next) share a single logical timeline.
  - `lib_comum.plc_sim.modbus_emulator`: pymodbus 3.13-based async Modbus TCP server. Pretends to be N PLCs (default 5) on a single port, addressed by `device_id` 1..N. Per-machine `SimAction` callback writes register values from the alimentar dataset on every read — so the collector sees realistic, time-correlated state, shift counter, internal temperature and ambient temperature.
  - `receita-1.../nivel-2-pro/modbus_collector/main.py`: pymodbus async client that polls every machine in parallel, batches inserts, handles reconnect, and writes 4 metrics per machine.
  - `lib_comum/sql/init/03_oee.sql`: TimescaleDB continuous aggregates — `machine_availability_1m` (per-minute running fraction) and `machine_availability_1h` (hourly roll-up), with refresh policies. Plus the convenience view `machine_availability_last_24h`.
  - `receita-1.../nivel-2-pro/grafana-dashboards/n2-oee-overview.json`: 4-panel dashboard provisioned automatically — availability per machine (last 24 h), gauge of worst 10 machines, internal vs ambient temperature (the line-3 case-study signal), shift-counter progression.
  - `tests/test_r1_n2_e2e.py`: integration test that spawns emulator + collector on an isolated port and asserts rows in `telemetry` for all 4 metrics and 3 machines. Passes in ~19 s.
  - `make demo-r1-n2`: orchestrates emulator + collector for 90 s and refreshes the aggregates at the end.

### Initial scaffolding
- Repository structure for 5 recipes, base Docker stack (TimescaleDB + Mosquitto + Grafana), uv-based Python project, Makefile, dev container, GitHub Actions CI.
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
