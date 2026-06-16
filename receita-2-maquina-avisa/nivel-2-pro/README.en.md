# Recipe 2 — Tier 2 (Pro)

> Continuous vibration + Isolation Forest + multi-channel alerts.

🇬🇧 EN (this file) · [🇵🇹 PT](README.md)

## What changes versus Tier 1

| Aspect | Tier 1 (DIY) | Tier 2 (Pro) |
|---|---|---|
| Detector | BPFO band + fixed baseline | **Isolation Forest** over 21 features (7 × 3 axes) per machine |
| Robustness | Reacts to a single band; sensitive to noise | Learns the "shape" of a healthy machine; catches anomalous combinations |
| Alerts | Log only | Apprise: Telegram, email, Slack, MS Teams (via `APPRISE_URLS`) |
| False positives | Low (absolute floor protects quiet machines) | Very low: press-1 dominates 50× over healthy peers |
| Adaptation | Manual re-calibration after maintenance | Same (model is frozen by design) |

Tier 2 doesn't replace Tier 1 — they coexist. Tier 1 is a cheap, simple first line of defence; Tier 2 layers ML on top. In production they typically run in parallel and their alerts correlate.

## Components

| Path / module | Purpose |
|---|---|
| [`feature_extractor/extractor.py`](feature_extractor/extractor.py) | Subscribes raw vibration, computes 7 features per axis (RMS, peak, crest, kurtosis, dominant freq, 1× band, BPFO band), persists to `vibration_features`, re-publishes on `fabrica/<line>/<machine>/vibration-features`. |
| [`isoforest_detector/detector.py`](isoforest_detector/detector.py) | Subscribes features, trains an IsolationForest per machine, freezes the model after warmup, persists alerts. |
| [`grafana-dashboards/`](grafana-dashboards/) | Dashboard "Receita 2 N2 — Anomalia (Isolation Forest)". |

Added to `lib_comum`:

- [`lib_comum/alerting.py`](../../lib_comum/alerting.py) — Apprise wrapper.
- [`lib_comum/sql/init/05_vibration_features.sql`](../../lib_comum/sql/init/05_vibration_features.sql) — `vibration_features` hypertable (10 columns + `anomaly_score`).
- [`lib_comum/db.py`](../../lib_comum/db.py) — `VibrationFeatureRow` and `insert_vibration_features`.

## Demo in <2 minutes (no hardware)

```bash
make up                  # base stack
make seed-data           # alimentar + moldes
make demo-r2-n2          # simulator + extractor + detector, ~75 seconds
# → open http://localhost:3000
# → dashboard "Receita 2 N2 — Anomalia (Isolation Forest)"
```

`demo-r2-n2` replays **10 simulated days** starting 4 days before the press-1 wear window. The detector freezes its model during the first ~20 snapshots (healthy state) and then scores every new vector. As the bearing degrades, the press's score drops to -0.10/-0.14 while the other 5 machines stay above -0.07. The press typically fires >600 warning alerts vs <13 on healthy peers.

## Architecture

```
[ESP32+ADXL345]
      ▼ MQTT (raw vibration)
      ┌─────────────────┐
      │ Feature         │  → TimescaleDB (vibration_features)
      │ Extractor       │
      └────────┬────────┘
               ▼ MQTT (vibration-features)
      ┌─────────────────┐
      │ Isolation       │  → TimescaleDB (vibration_alerts band='anomaly')
      │ Forest          │  → Apprise (Telegram / email / Teams)
      └─────────────────┘
```

The `Extractor` ↔ `Detector` split scales vertically (more machines = more extractors behind the broker) and horizontally (several algorithms in parallel consuming the same features — IF, autoencoder, SVM).

## Feature vector (per machine × axis)

```
[ rms_g, peak_g, crest_factor, kurtosis,
  dominant_freq_hz, band_rotation_1x_g, band_bpfo_g ]
```

3 axes × 7 features = **21 dimensions per machine**. The IsolationForest fits this space.

## The IsolationForest model

Per machine:

- `n_estimators=80`, `contamination=0.05`, fixed `random_state` for reproducibility.
- Warmup: accumulates `--warmup-window` healthy snapshots, fits **once** and freezes.
- Online re-fit is **off by default** (`--refit-every 0`). Continuous re-training would let a slowly developing bearing fault be absorbed as the "new normal" — the exact opposite of what we want.
- To retrain after maintenance: stop the detector, clear in-memory state (restart), or pass `--refit-every N` when external knowledge confirms mechanical health.

## Multi-channel alerts

Configure via env:

```bash
export APPRISE_URLS="tgram://BOT_TOKEN/CHAT_ID,mailto://smtp.example.com?to=director@plant.example"
```

`lib_comum.alerting.AlertSender` handles dispatch. When `APPRISE_URLS` is unset (demo default), the alert is logged only — but still persisted in `vibration_alerts`.

## Tier 2 limits

- IsolationForest is unsupervised and unlabelled. Classifying the fault (BPFO vs BPFI vs FTF vs BSF) or estimating RUL needs **Tier 3** (autoencoder + supervision).
- The model is per-machine. Large fleets (50+) benefit from per-family shared models — also Tier 3.
- No "informed" automatic retraining (needs an external end-of-maintenance signal).

Back to [Recipe 2](../README.en.md).
