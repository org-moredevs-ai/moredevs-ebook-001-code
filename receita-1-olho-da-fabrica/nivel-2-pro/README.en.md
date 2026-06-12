# Recipe 1 — Tier 2 (Pro)

> Modbus TCP + TimescaleDB + real-time OEE + multi-user dashboards.

🇬🇧 EN (this file) · [🇵🇹 PT](README.md)

## What changes versus Tier 1

| Aspect | Tier 1 (DIY) | Tier 2 (Pro) |
|---|---|---|
| Telemetry | SCT-013 → ESP32 → MQTT (current proxy) | PLC → Modbus TCP (state, counters, temperatures) |
| OEE | Not computed | Real-time availability (continuous aggregates) |
| History | Compressed at 7 days | Same + per-minute/hour roll-ups |
| Users | Local dashboard | Dashboard with multiple panels and roles |

Recipe 1 covers only the **availability** component of OEE (running ÷ scheduled). Recipe 2 adds quality (anomalies); Recipe 5 adds performance (planned vs actual).

## Components

| Folder | Purpose |
|---|---|
| [`modbus_collector/`](modbus_collector/) | Async Modbus TCP client. Polls N machines in parallel, writes `state`/`shift_count`/`temperature_c`/`ambient_temp_c` to TimescaleDB. |
| [`grafana-dashboards/`](grafana-dashboards/) | Dashboard "Receita 1 N2 — OEE & Pro". |

Added to `lib_comum`:

- [`lib_comum/plc_sim/modbus_emulator.py`](../../lib_comum/plc_sim/modbus_emulator.py) — Modbus TCP emulator that replaces physical PLCs in demos and tests.
- [`lib_comum/plc_sim/state_clock.py`](../../lib_comum/plc_sim/state_clock.py) — compressed clock (`SimClock`) shared across emulators.
- [`lib_comum/sql/init/03_oee.sql`](../../lib_comum/sql/init/03_oee.sql) — continuous aggregates: `machine_availability_1m`, `machine_availability_1h`, view `machine_availability_last_24h`.

## Demo in <2 minutes (no hardware)

```bash
make up                  # base stack
make seed-data           # generate the alimentar dataset (once)
make demo-r1-n2          # Modbus emulator (5 PLCs) + collector, ~90 seconds
# → open http://localhost:3000
# → dashboard "Receita 1 N2 — OEE & Pro"
```

`demo-r1-n2` brings up:
1. A Modbus emulator on `localhost:1502` with 5 PLCs addressed by `device_id` 1..5.
2. The `modbus_collector` in parallel, polling each machine once per second.

When done, it refreshes the continuous aggregates one last time so the dashboard is populated.

## Tier 2 stack

| Component | Version | Purpose |
|---|---|---|
| Postgres + TimescaleDB | 16 + 2.x | Relational + time-series + continuous aggregates |
| Mosquitto | 2.0 | MQTT broker (reused from Tier 1 for non-PLC sensors) |
| Grafana | 11 | Dashboards |
| pymodbus | 3.7+ | Async Modbus TCP client |
| asyncua | 1.x | (In progress — OPC-UA collector) |
| Apprise | 1.9+ | (In progress — multi-channel alerts) |

## Holding-register map (per machine)

| Address | Content |
|---|---|
| HR 1 | State: 0 stopped, 1 running, 2 idle, 3 fault, 4 setup, 5 cleaning |
| HR 11 | `shift_count` — units produced this shift (16-bit) |
| HR 21 | `temperature_c × 10` — internal temperature (245 = 24.5 °C) |
| HR 22 | `ambient_temp_c × 10` — line ambient temperature |

The `modbus_collector` reads the first 30 holding registers from each `device_id` and decodes them into these 4 metrics. The `modbus_emulator` serves these values from the synthetic dataset.

## OEE — real-time availability

```sql
SELECT machine, ROUND(availability_24h::numeric, 2) AS availability
FROM machine_availability_last_24h
ORDER BY availability_24h ASC;
```

Typical output after the demo:

```
      machine      | availability
-------------------+--------------
 linha-1.maquina-1 |         0.78
 linha-1.maquina-2 |         0.96
 linha-1.maquina-3 |         0.94
 linha-1.maquina-4 |         0.95
 linha-2.maquina-1 |         0.88
```

The refresh policy keeps `machine_availability_1m` up to date every 30 seconds and `machine_availability_1h` every 5 minutes. On short demos (<2 min) the script calls `refresh_continuous_aggregate(...)` manually — `make demo-r1-n2` already does this.

## When Tier 2 isn't enough

Chapter 1 names the limits:
- More than one factory → Tier 3 (multi-site, BI).
- Bidirectional ERP integration → also Tier 3.
- Predictive analytics (RUL, anomalies) → Chapter 2 (Recipe 2).

Back to [Recipe 1](../README.en.md).
