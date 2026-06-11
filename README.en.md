# Smart Factory — AI Recipes · Companion code

> Public companion repository for the ebook *"Smart Factory: AI Recipes"* (MoreDevs.ai).
> Status: **in development.** Launch expected Q4 2026.
>
> 🇬🇧 EN (this file) · [🇵🇹 PT](README.md)

---

## What this repository is

Five AI recipes for industrial SMEs, with **code that runs** — not pedagogical code. Each recipe has three tiers:

- **Tier 1 — DIY** (€): ESP32 / Raspberry Pi, Python scripts, local dashboards.
- **Tier 2 — Pro** (€€): full stack with TimescaleDB, Postgres, Grafana, alerting, Docker.
- **Tier 3 — Premium** (€€€): reference architecture, ERP/MES/PLC integration. No complete code — this is where MoreDevs.ai comes in.

| # | Recipe | Folder |
|---|---|---|
| 1 | The Eye on the Floor | [`receita-1-olho-da-fabrica/`](receita-1-olho-da-fabrica/) |
| 2 | The Machine That Warns Before It Breaks | [`receita-2-maquina-avisa/`](receita-2-maquina-avisa/) |
| 3 | The Quote Writer That Never Sleeps | [`receita-3-orcamentista/`](receita-3-orcamentista/) |
| 4 | The Cut That Doesn't Waste | [`receita-4-corte-sem-desperdicio/`](receita-4-corte-sem-desperdicio/) |
| 5 | The Delivery Promise That Holds | [`receita-5-promessa-prazo/`](receita-5-promessa-prazo/) |

Folder names stay in Portuguese to keep paths stable across languages.

## Get running in <30 minutes

```bash
git clone https://github.com/org-moredevs-ai/moredevs-ebook-001-code
cd moredevs-ebook-001-code

# 1. Python environment
make setup

# 2. Base stack (TimescaleDB + Mosquitto + Grafana)
make up

# 3. Seed example data for all recipes
make seed-data

# 4. Recipe 1 demo
make demo-r1
```

Open `http://localhost:3000` (Grafana, admin/admin local) to see data flowing.

## Prerequisites

- **Python 3.13** (3.12 also tested).
- **uv** ≥ 0.5 — package manager ([install](https://docs.astral.sh/uv/getting-started/installation/)).
- **Docker** + **Docker Compose v2** — required for Tier 2.
- **PlatformIO** — only for ESP32 flashing (Tier 1 of R1/R2).

Recommended: **VS Code with the Dev Containers extension**. `Reopen in Container` handles everything in <5 min.

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.13 |
| Package manager | `uv` |
| Time-series DB | **TimescaleDB** (Postgres 16 extension) |
| Relational DB | Postgres 16 (part of TimescaleDB) |
| MQTT broker | Eclipse Mosquitto |
| Dashboards | Grafana 11 |
| Optimisation (R4, R5) | OR-Tools |
| LLM (R3) | Anthropic Claude (Sonnet 4.6 default) |
| Tier 2 UI (R3, R4, R5) | Streamlit + FastAPI |
| Containers | Docker + Compose v2 |

## Licence

Code under [MIT](LICENSE). Ebook prose (manuscript, marketing) lives in a separate private repository and is under MoreDevs.ai copyright.

## Status

**In development.** Companion code for the *Smart Factory: AI Recipes* ebook.

- Ebook launch: Q4 2026.
- Marketplaces: Amazon KDP, Apple Books, Google Play, Kobo, LeanPub.
- Get it at [moredevs.ai/ebook-001](https://moredevs.ai/ebook-001) (soon).

## Contributing

Issues and PRs welcome, but scope is bounded by the ebook. For larger discussions, open an issue before submitting a PR.

## About

Produced by [MoreDevs.ai](https://moredevs.ai). Applied AI consultancy for European industrial SMEs.
