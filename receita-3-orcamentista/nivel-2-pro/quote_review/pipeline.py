"""Recipe 3 Tier 2 — review pipeline demo (offline by default).

PT: Demonstra o ciclo do Nível 2: semeia a memória vectorial com orçamentos
passados, recebe um pedido novo, precifica-o, recupera os mais parecidos e
sinaliza desvios de preço — o que o revisor humano veria antes de aprovar.
EN: Demonstrates the Tier 2 loop: seeds the vector memory with past quotes,
takes a new RFQ, prices it, retrieves the most similar and flags price
deviations — what the human reviewer would see before approving.

Run with::

    uv run python receita-3-orcamentista/nivel-2-pro/quote_review/pipeline.py
"""

from __future__ import annotations

import argparse
import sys

from lib_comum.data_synth import rfq as rfq_data
from lib_comum.llm import make_provider
from lib_comum.quote_memory import QuoteMemory
from lib_comum.quote_pricing import price_quote, render_quote_text
from lib_comum.quote_review import record_approved, review_rfq


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="offline", choices=["offline", "anthropic"])
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260509)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    catalogue = rfq_data.load_catalogue()
    provider = make_provider(args.provider)
    samples = rfq_data.generate_samples(n=args.samples, seed=args.seed)
    memory = QuoteMemory()

    # Seed the memory with the approved quotes of all but the last sample.
    for sample in samples[:-1]:
        extraction = provider.extract_rfq(sample.body)
        quote = price_quote(
            items=extraction.items,
            catalogue=catalogue,
            rfq_id=sample.rfq_id,
            customer=sample.customer,
            deadline_days=sample.deadline_days,
        )
        record_approved(memory, sample.rfq_id, sample.body, quote)

    target = samples[-1]
    result = review_rfq(
        body=target.body,
        rfq_id=target.rfq_id,
        catalogue=catalogue,
        provider=provider,
        memory=memory,
    )

    print(f"--- RFQ {target.rfq_id} ({target.channel}) ---")
    print(target.body)
    print("\n--- review ---")
    print(f"  provider: {result.extraction.provider}")
    print(f"  similar past quotes in memory: {len(memory)} stored, {len(result.similar)} shown")
    for sim in result.similar:
        print(f"    {sim.rfq_id}: total €{sim.total_eur:.2f} (similarity={sim.similarity:.2f})")
    print(f"  price flag [{result.flag.kind}]: {result.flag.message}")
    print("\n--- quote ---")
    print(render_quote_text(result.quote))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
