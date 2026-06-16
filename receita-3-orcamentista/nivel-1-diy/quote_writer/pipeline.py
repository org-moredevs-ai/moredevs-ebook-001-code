"""Recipe 3 Tier 1 — RFQ → quote pipeline orchestrator.

PT: Junta os blocos: extracção (LLM ou offline) + catálogo de preços +
totalização + render. Usado pela UI Streamlit e pelos testes.
EN: Glues together extraction (LLM or offline) + price catalogue +
totalisation + rendering. Used by the Streamlit UI and the tests.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

import pandas as pd

from lib_comum.data_synth import rfq as rfq_data
from lib_comum.llm import LLMProvider, RfqExtraction, make_provider
from lib_comum.quote_pricing import (
    DEFAULT_MARGIN_PCT,
    DEFAULT_VAT_PCT,
    Quote,
    price_quote,
    render_quote_text,
)

DEFAULT_DATA_DIR: Final[Path] = (
    Path(__file__).resolve().parents[3]
    / "receita-3-orcamentista"
    / "data-exemplo"
    / "metalomecanica"
)


def process_rfq(
    *,
    body: str,
    rfq_id: str,
    catalogue: pd.DataFrame,
    provider: LLMProvider,
    margin_pct: float = DEFAULT_MARGIN_PCT,
    vat_pct: float = DEFAULT_VAT_PCT,
) -> tuple[RfqExtraction, Quote]:
    """Run extraction + pricing for one RFQ body. Returns both for auditing.

    PT: Corre a extracção + a totalização. Devolve ambos.
    EN: Runs extraction + totalisation. Returns both.
    """
    extraction = provider.extract_rfq(body)
    quote = price_quote(
        items=extraction.items,
        catalogue=catalogue,
        rfq_id=rfq_id,
        customer=extraction.customer,
        deadline_days=extraction.deadline_days,
        margin_pct=margin_pct,
        vat_pct=vat_pct,
    )
    return extraction, quote


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rfq-file",
        type=Path,
        required=False,
        help="Path to an RFQ text file. If omitted, generates a synthetic one.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        choices=["anthropic", "offline"],
        help="LLM provider override. Defaults to LLM_PROVIDER env / anthropic.",
    )
    parser.add_argument("--margin-pct", type=float, default=DEFAULT_MARGIN_PCT)
    parser.add_argument("--vat-pct", type=float, default=DEFAULT_VAT_PCT)
    parser.add_argument(
        "--seed",
        type=int,
        default=20260509,
        help="Seed used when generating a synthetic RFQ on the fly.",
    )
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=None,
        help="CSV with the price catalogue. Defaults to the built-in one.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    catalogue = rfq_data.load_catalogue() if args.catalogue is None else pd.read_csv(args.catalogue)
    provider = make_provider(args.provider)

    if args.rfq_file is not None:
        body = Path(args.rfq_file).read_text(encoding="utf-8")
        rfq_id = args.rfq_file.stem
    else:
        sample = rfq_data.generate_samples(n=1, seed=args.seed)[0]
        body = sample.body
        rfq_id = sample.rfq_id
        print(f"--- synthetic RFQ ({sample.channel}) ---\n{body}\n")

    extraction, quote = process_rfq(
        body=body,
        rfq_id=rfq_id,
        catalogue=catalogue,
        provider=provider,
        margin_pct=args.margin_pct,
        vat_pct=args.vat_pct,
    )
    print("--- extraction summary ---")
    print(f"  provider: {extraction.provider}")
    print(f"  items extracted: {len(extraction.items)}")
    print(f"  customer: {extraction.customer or '(?)'}")
    print(f"  deadline: {extraction.deadline_days}")
    print("\n--- quote ---")
    print(render_quote_text(quote))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
