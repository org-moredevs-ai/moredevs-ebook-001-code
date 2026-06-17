"""Recipe 3 Tier 2 — review pipeline with price-consistency flags.

PT: Junta a extracção, o motor de preços e a memória vectorial. Para cada
pedido, devolve a extracção, o orçamento, os orçamentos passados mais parecidos,
e um *flag* que sinaliza se o total se desvia demasiado do histórico — o sinal
que o revisor humano vê antes de aprovar.

EN: Ties extraction, the pricing engine and the vector memory together. For each
RFQ it returns the extraction, the quote, the most similar past quotes, and a
flag that signals whether the total deviates too far from history — the cue the
human reviewer sees before approving.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from lib_comum.llm import LLMProvider, RfqExtraction
from lib_comum.quote_memory import QuoteMemory, SimilarQuote
from lib_comum.quote_pricing import (
    DEFAULT_MARGIN_PCT,
    DEFAULT_VAT_PCT,
    Quote,
    price_quote,
)

DEFAULT_DEVIATION_FACTOR = 2.0
"""A total >= factor x (or <= 1/factor x) the median of similar quotes is flagged."""


@dataclass(frozen=True, slots=True)
class PriceFlag:
    """Verdict on whether a quote total is consistent with history.

    ``kind`` is one of: ``ok``, ``high``, ``low``, ``no_history``.
    """

    kind: str
    ratio: float | None
    reference_total_eur: float | None
    message: str


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """Everything the human reviewer needs to decide in two clicks."""

    extraction: RfqExtraction
    quote: Quote
    similar: list[SimilarQuote]
    flag: PriceFlag


def flag_price(
    quote: Quote,
    similar: list[SimilarQuote],
    *,
    deviation_factor: float = DEFAULT_DEVIATION_FACTOR,
) -> PriceFlag:
    """Compare *quote*'s total to the median of *similar* totals.

    PT: Compara o total com a mediana dos pedidos semelhantes.
    EN: Compares the total to the median of similar quotes.
    """
    totals = [s.total_eur for s in similar if s.total_eur > 0.0]
    if not totals:
        return PriceFlag(
            kind="no_history",
            ratio=None,
            reference_total_eur=None,
            message="Sem histórico semelhante — rever manualmente.",
        )
    reference = float(np.median(totals))
    if reference <= 0.0:
        return PriceFlag("no_history", None, None, "Sem referência de preço utilizável.")
    ratio = quote.total_eur / reference
    if ratio >= deviation_factor:
        return PriceFlag(
            kind="high",
            ratio=ratio,
            reference_total_eur=reference,
            message=(
                f"Total {ratio:.1f}x acima de pedidos semelhantes "
                f"(~€{reference:.2f}). Verificar quantidades extraídas."
            ),
        )
    if ratio <= 1.0 / deviation_factor:
        return PriceFlag(
            kind="low",
            ratio=ratio,
            reference_total_eur=reference,
            message=(
                f"Total {ratio:.1f}x abaixo de pedidos semelhantes "
                f"(~€{reference:.2f}). Verificar se faltam linhas."
            ),
        )
    return PriceFlag(
        kind="ok",
        ratio=ratio,
        reference_total_eur=reference,
        message=f"Coerente com o histórico (~€{reference:.2f}).",
    )


def review_rfq(
    *,
    body: str,
    rfq_id: str,
    catalogue: pd.DataFrame,
    provider: LLMProvider,
    memory: QuoteMemory,
    k: int = 3,
    margin_pct: float = DEFAULT_MARGIN_PCT,
    vat_pct: float = DEFAULT_VAT_PCT,
    deviation_factor: float = DEFAULT_DEVIATION_FACTOR,
) -> ReviewResult:
    """Extract, price, retrieve similar quotes and flag the total.

    PT: Extrai, precifica, recupera semelhantes e sinaliza o total.
    EN: Extracts, prices, retrieves similar quotes and flags the total.
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
    similar = memory.find_similar(body, k=k)
    flag = flag_price(quote, similar, deviation_factor=deviation_factor)
    return ReviewResult(extraction=extraction, quote=quote, similar=similar, flag=flag)


def record_approved(memory: QuoteMemory, rfq_id: str, body: str, quote: Quote) -> None:
    """Persist an approved quote into the memory (closes the learning loop).

    PT: Guarda um orçamento aprovado na memória.
    EN: Stores an approved quote into the memory.
    """
    memory.add_quote(rfq_id, body, quote)
