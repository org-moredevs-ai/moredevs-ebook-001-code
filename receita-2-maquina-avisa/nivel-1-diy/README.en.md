# Recipe 2 — Tier 1 (DIY)

> ESP32 + ADXL345 → MQTT (raw snapshots) → Python FFT → alert. **~€50 per machine.**

🇬🇧 EN (this file) · [🇵🇹 PT](README.md)

## What it does

Each important machine gets an ADXL345 accelerometer wired to an ESP32. Every few seconds the ESP32 captures 1 second of 1 kHz 3-axis samples and ships the raw bundle over MQTT. A small Python service runs the FFT, extracts amplitude in the BPFO bearing band, freezes a healthy baseline, and fires an alert when the band climbs more than 30–40% above that baseline.

The Chapter 2 field case: a 250-tonne press develops a bearing fault 11 days before catastrophic stoppage. The synthetic `moldes` dataset injects that exact signal; the pipeline here catches it with zero false positives on the other 5 machines.

## Components

| Folder | Purpose |
|---|---|
| [`firmware-esp32/`](firmware-esp32/) | ESP32 + ADXL345 firmware (PlatformIO). |
| [`simulator/`](simulator/) | Replaces physical ESP32s in demos and tests. Publishes synthesised snapshots from the `moldes` dataset. |
| [`fft_alert/`](fft_alert/) | MQTT subscriber, Python FFT, frozen-baseline alerter. |
| [`grafana-dashboards/`](grafana-dashboards/) | Dashboard "Receita 2 N1 — Vibração & FFT". |

Support in `lib_comum`:

- [`lib_comum/plc_sim/vibration_signal.py`](../../lib_comum/plc_sim/vibration_signal.py) — synthetic waveform generator shared by the simulator and the tests.
- [`lib_comum/sql/init/04_vibration.sql`](../../lib_comum/sql/init/04_vibration.sql) — `vibration_bands` and `vibration_alerts` tables.
- [`lib_comum/db.py`](../../lib_comum/db.py) — batch insert helpers.

## Bill of materials (per machine)

| Item | Unit price |
|---|---|
| ESP32 DevKitC-32E | €12 |
| ADXL345 breakout | €4 |
| IP54 enclosure + magnetic mount / industrial adhesive | €15 |
| USB-C 5 V 1 A PSU + cable | €10 |
| Terminals, wires | €5 |
| **Subtotal per machine** | **~€46** |

For 10 monitored motors: ~€460 in hardware. Server shared with Recipe 1 (no extra cost).

## Demo in <2 minutes (no hardware)

From the repo root:

```bash
make up                  # Postgres + TimescaleDB + Mosquitto + Grafana
make seed-data           # alimentar + moldes datasets
make demo-r2             # simulator + FFT receiver in parallel, 60 seconds
# → open http://localhost:3000 (admin/admin)
# → dashboard "Receita 2 N1 — Vibração & FFT"
```

`demo-r2` replays 3 simulated days of the `moldes` dataset starting 1 day before the press-1 wear window. In ~60 wall seconds the receiver freezes the baseline for the healthy machines and watches the press BPFO band climb 2–4× above it. Alerts concentrate exclusively on press-1, on all three axes.

## Architecture

```
[Motor]  ─glue/magnet─►  [ADXL345]  ─I²C─►  [ESP32]  ─WiFi/MQTT─►  [Mosquitto]
                                                                       │
                                                                       ▼
                                                    [Python FFT receiver]
                                                                       │
                                                            ┌──────────┴──────────┐
                                                            ▼                     ▼
                                                  [TimescaleDB]            Apprise alert
                                                  vibration_bands           Telegram / email
                                                  vibration_alerts          (Tier 2)
                                                            │
                                                            ▼
                                                       [Grafana]
```

## MQTT topic and payload

Topic:

```
fabrica/<line>/<machine>/vibration
```

JSON payload (1 second @ 1 kHz):

```json
{
  "machine": "prensa-250t.maquina-1",
  "sample_rate_hz": 1000,
  "uptime_ms": 13420,
  "x": [0.018, 0.022, -0.011, ...],
  "y": [-0.005, 0.014, ...],
  "z": [0.001, 0.008, ...]
}
```

## What the receiver does

1. Subscribes to `fabrica/+/+/vibration`.
2. For every snapshot, runs `numpy.fft.rfft` per axis and computes the RMS amplitude inside two bands:
   - **`rotation_1x`** — 22–28 Hz (1× rotation for the press).
   - **`bpfo`** — 79–87 Hz (bearing band for the press; a typical value for a large bearing).
3. Persists each amplitude into `vibration_bands`.
4. Builds a baseline over `--warmup-samples` snapshots; then **freezes** it.
5. When a sample exceeds `baseline × (1 + threshold_pct/100)`, fires an alert:
   - severity `info` for ≥1.5× baseline, `warning` for ≥2×, `critical` for ≥3×.
   - configurable cooldown to avoid flapping.
   - minimum absolute amplitude (`--min-amplitude-g`) protects against false positives on quiet machines.

## Tier 1 limits

- Only two pre-defined bands. To classify the fault (BPFO vs BPFI vs FTF vs BSF) you need the actual bearing geometry.
- A frozen baseline assumes the machine starts healthy. In production you re-calibrate after every maintenance.
- No learning (Isolation Forest, autoencoder). That's Recipe 2 Tier 2.
- Alerts go to the log only. To wire Telegram/email, plug in Apprise — the base is already in `lib_comum`.

Back to [Recipe 2](../README.en.md).
