# lib_comum

Shared helpers used across recipes: MQTT, TimescaleDB / Postgres, LLM abstraction (provider-agnostic), synthetic data generators, Mosquitto/Grafana provisioning files.

This package is installable as `moredevs-ebook-001-code` (see `pyproject.toml`). Receitas import from `lib_comum.*`.

| Path | Purpose |
|---|---|
| `sql/init/` | TimescaleDB extension + base schema, mounted at first boot. |
| `mosquitto/` | Mosquitto broker config. |
| `grafana/provisioning/` | Auto-provisioned Grafana datasource + dashboards folder. |
| `data_synth/` | Per-sector synthetic data generators (alimentar, metalomecânica, têxtil, ...). |

**In development.** Populated during Phase 0–1.
