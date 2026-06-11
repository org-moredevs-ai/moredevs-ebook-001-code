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
