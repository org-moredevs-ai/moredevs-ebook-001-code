# tools/

Repo utilities — invoked via `make` targets or directly with `uv run python -m tools.<name>`.

| Script | Purpose |
|---|---|
| `seed_synth_data.py` | Generate synthetic datasets for all recipes (deterministic, seed=20260509) |
| `snapshot_dashboards.py` | Capture deterministic Grafana PNGs for slides and screenshots |
| `verify_ebook_sync.py` | Verify that snippets cited by the manuscript still exist and run |

**In development.**
