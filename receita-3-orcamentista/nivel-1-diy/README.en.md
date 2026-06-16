# Recipe 3 — Tier 1 (DIY)

> RFQ over email → LLM extracts the items → catalogue → quote ready to ship, in minutes. **~€0.05 per quote.**

🇬🇧 EN (this file) · [🇵🇹 PT](README.md)

## What it does

A customer sends a request by email, WhatsApp or form. The system reads the text, identifies the operations (laser cutting, bending, welding, drilling, painting, assembly), the material (stainless 304/316L, carbon S235/S275, aluminium 5754/6082), thickness and quantity. It crosses against the price catalogue, applies margin and VAT, and returns a quote in the browser — ready for the director to review and ship in two clicks.

The Chapter 3 field case: a sheet-metal shop near Vale do Sousa now answers in minutes RFQs that used to take 1–2 days. Same-day response went from 35% to 92%.

## Components

| Path / module | Purpose |
|---|---|
| [`quote_writer/app.py`](quote_writer/app.py) | Streamlit review and export UI. |
| [`quote_writer/pipeline.py`](quote_writer/pipeline.py) | CLI orchestrator (no UI). |

Support in `lib_comum`:

- [`lib_comum/data_synth/rfq.py`](../../lib_comum/data_synth/rfq.py) — synthetic PT-PT RFQ generator (formal email, WhatsApp, web form) + price catalogue (58 rows).
- [`lib_comum/llm.py`](../../lib_comum/llm.py) — provider-agnostic interface with two backends: **Anthropic Claude** (Sonnet 4.6 by default) and **offline** (regex for tests and air-gapped environments).
- [`lib_comum/quote_pricing.py`](../../lib_comum/quote_pricing.py) — pricing engine (hierarchical catalogue lookup, totals with margin and VAT, unresolved items).

## Demo in <1 minute

```bash
make demo-r3          # opens Streamlit on http://localhost:8501
# or
make demo-r3-cli      # runs the pipeline in the terminal with the offline provider
```

To use Anthropic Claude:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
make demo-r3          # Streamlit picks Anthropic when the key is set
```

Without a key, the pipeline falls back to the `offline` provider (regex). Handy for tests, CI and air-gapped environments — not as accurate (~80–90% line-item match on the synthetic corpus) but useful as a working baseline without external dependencies.

## Catalogue

The catalogue is built in code (via `rfq.load_catalogue()`) with 58 rows covering the 7 operations × 6 materials × 4 thicknesses + flat-fee lines (drilling, deburring, painting, assembly). Prices are realistic for PT-PT 2026.

For production:
- Export `rfq.load_catalogue()` to CSV.
- Edit it with your supplier prices.
- Pass via `--catalogue path/to/your.csv` to the pipeline or mount it into Streamlit.

## Cost per quote

| Item | Per quote |
|---|---|
| Anthropic Claude Sonnet 4.6 — ~1–2 k tokens in, ~500 out | ~€0.04 |
| TimescaleDB / Postgres write | near-zero |
| Streamlit hosting (self-hosted) | near-zero |
| **Marginal total** | **~€0.05** |

At 50 quotes/day: **~€2.50/day** in LLM costs. Compared with 30 min of an engineer per quote (€20–30 each), the ROI is immediate.

## Tier 1 limits

- **No PDF / image input.** RFQs that carry a technical drawing need Vision (Tier 2).
- **No history.** Doesn't compare against previous quotes from the same customer. Tier 2 ships a vector DB (Chroma) with semantic similarity.
- **No automatic approval.** The quote goes back to a human before being sent. Auto-approval for simple cases lives in Tier 3.
- **Static catalogue.** Price changes via redeploy. For dynamic catalogue management see Tier 2 (Postgres-backed).

Back to [Recipe 3](../README.en.md).
