# Recipe 1 — Tier 1 (DIY)

> ESP32 + SCT-013 → MQTT → TimescaleDB → Grafana. **~€600 for 10 machines.**

🇬🇧 EN (this file) · [🇵🇹 PT](README.md)

## What this does

Measures the current draw of each motor (a reliable proxy for "running / stopped") and shows it on a web dashboard reachable on the factory LAN. Chapter 1 of the ebook covers the theory; this folder is the code that runs.

## Components

| Folder | Purpose |
|---|---|
| [`firmware-esp32/`](firmware-esp32/) | ESP32 firmware (PlatformIO). Reads the SCT-013 and publishes over MQTT once a second. |
| [`ingest/`](ingest/) | MQTT subscriber → INSERT into TimescaleDB. |
| [`simulator/`](simulator/) | Replaces the physical ESP32s during demos and tests. Replays synthetic data over MQTT. |
| [`grafana-dashboards/`](grafana-dashboards/) | Auto-provisioned Grafana dashboard JSON. |

## Bill of materials (10 machines)

| Item | Qty | Unit price | Total |
|---|---|---|---|
| ESP32 DevKitC-32E | 10 | €12 | €120 |
| SCT-013 30 A voltage-output | 10 | €13 | €130 |
| IP54 enclosure 80 × 60 × 40 mm | 10 | €10 | €100 |
| USB-C 5 V 1 A PSU | 10 | €6 | €60 |
| USB-C 1 m cable | 10 | €3 | €30 |
| Terminals, wires, DIN rails | — | — | €40 |
| Raspberry Pi 5 8 GB Kit | 1 | €110 | €110 |
| MicroSD 64 GB A2 V30 | 1 | €18 | €18 |
| **Total** | | | **~€608** |

> Reference suppliers: DigiKey, Mouser, RS Components, Adafruit. Prices in EUR; June 2026, ±10%.

## Architecture

```
   [Motor]  ─cable─►  [SCT-013]  ─V_out─►  [ESP32]  ─WiFi/MQTT─►  [Mosquitto]
                                                                       │
                                                                       ▼
                                                    [Python ingest]  ─►  [TimescaleDB]
                                                                       │
                                                                       ▼
                                                                   [Grafana]  ──►  Browser
```

## Demo in <2 minutes (no hardware needed)

From the repo root:

```bash
make up                  # Postgres+TimescaleDB + Mosquitto + Grafana
make seed-data           # generate the alimentar dataset (once)
make demo-r1             # simulator + ingest in parallel, 90 seconds
# open http://localhost:3000 (admin/admin)
# → dashboard "Receita 1 N1 — Olho da fábrica"
```

The `demo-r1` target replays, in 90 seconds, the activity of 5 machines in a food-processing line — with stoppages, normal operation and cleaning. The dashboard shows live current and current state.

## Demo with real hardware

1. Flash the firmware to the ESP32 boards (see [`firmware-esp32/README.en.md`](firmware-esp32/README.en.md)).
2. Install the SCT-013 clamps around the motor power cables.
3. Bring everything onto the same WiFi network as the Raspberry Pi (or laptop) running `make up`.
4. Start the ingest: `uv run python receita-1-olho-da-fabrica/nivel-1-diy/ingest/mqtt_to_db.py`.

The ESP32s publish to `fabrica/<line>/<machine>/current`; the ingest subscribes to `fabrica/+/+/current`.

## Database schema

The `telemetry` hypertable is created automatically on TimescaleDB boot:

```sql
CREATE TABLE telemetry (
  ts        TIMESTAMPTZ      NOT NULL,
  machine   TEXT             NOT NULL,
  metric    TEXT             NOT NULL,
  value     DOUBLE PRECISION NOT NULL
);
SELECT create_hypertable('telemetry', 'ts', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX telemetry_machine_metric_ts_idx ON telemetry (machine, metric, ts DESC);
ALTER TABLE telemetry SET (timescaledb.compress, timescaledb.compress_segmentby = 'machine, metric');
SELECT add_compression_policy('telemetry', INTERVAL '7 days');
```

Chunks older than 7 days are automatically compressed.

## Typical total cost

- **Hardware:** €608.
- **Engineering:** 4.5 person-days.
- **Electrician (1 day):** ~€240.

**Typical total:** ~€2,700. If the company has an in-house person, this halves.

## When this isn't enough

Reading current as a proxy is a good first approximation but has limits:

- Doesn't tell stopped-because-fault from stopped-because-operator-absent.
- Doesn't measure quality or per-unit yield.
- No multi-channel alerting.
- No PLC or ERP integration.

For that, see [Tier 2](../nivel-2-pro/).

Back to [Recipe 1](../README.en.md).
