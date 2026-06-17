"""Recipe 3 Tier 2 — vector memory and review-flag tests (offline, no network).

PT: Testa a memória vectorial e o flag de coerência de preço de forma
determinística, sem rede nem chaves de API.
EN: Tests the vector memory and the price-consistency flag deterministically,
without network or API keys.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lib_comum.data_synth import rfq as rfq_data
from lib_comum.llm import OfflineProvider
from lib_comum.quote_memory import QuoteMemory, SimilarQuote, embed
from lib_comum.quote_pricing import Quote, price_quote
from lib_comum.quote_review import flag_price, review_rfq

_RESOLVED_BODY = (
    "Corte laser em aço inox 304, espessura 2 mm, 30 m de corte\n"
    "Dobragem de aço inox 304, espessura 2 mm, 5 dobras\n"
    "Prazo: 14 dias"
)


def _price(catalogue: pd.DataFrame, body: str, rfq_id: str) -> Quote:
    extraction = OfflineProvider().extract_rfq(body)
    return price_quote(
        items=extraction.items,
        catalogue=catalogue,
        rfq_id=rfq_id,
        customer=None,
        deadline_days=None,
    )


def test_embed_is_deterministic_and_normalised() -> None:
    vec = embed("corte laser em aço inox 304")
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-9
    assert np.array_equal(embed("abc def"), embed("abc def"))


def test_find_similar_returns_the_matching_quote_first() -> None:
    catalogue = rfq_data.load_catalogue()
    samples = rfq_data.generate_samples(n=6, seed=20260509)
    memory = QuoteMemory()
    for sample in samples:
        memory.add_quote(sample.rfq_id, sample.body, _price(catalogue, sample.body, sample.rfq_id))

    target = samples[2]
    similar = memory.find_similar(target.body, k=3)
    assert similar
    assert similar[0].rfq_id == target.rfq_id
    assert similar[0].similarity > 0.9


def test_find_similar_empty_memory_returns_nothing() -> None:
    assert QuoteMemory().find_similar("qualquer pedido", k=3) == []


def test_flag_price_classifies_high_low_ok_and_no_history() -> None:
    catalogue = rfq_data.load_catalogue()
    quote = _price(catalogue, _RESOLVED_BODY, "RFQ-TEST")
    total = quote.total_eur
    assert total > 0.0

    low_history = [SimilarQuote("a", "", total / 4.0, 0.9), SimilarQuote("b", "", total / 4.0, 0.8)]
    assert flag_price(quote, low_history).kind == "high"

    aligned_history = [SimilarQuote("a", "", total, 0.9), SimilarQuote("b", "", total * 1.1, 0.8)]
    assert flag_price(quote, aligned_history).kind == "ok"

    high_history = [SimilarQuote("a", "", total * 4.0, 0.9)]
    assert flag_price(quote, high_history).kind == "low"

    assert flag_price(quote, []).kind == "no_history"


def test_review_rfq_runs_end_to_end_offline() -> None:
    catalogue = rfq_data.load_catalogue()
    provider = OfflineProvider()
    samples = rfq_data.generate_samples(n=5, seed=20260509)
    memory = QuoteMemory()
    for sample in samples[:-1]:
        memory.add_quote(sample.rfq_id, sample.body, _price(catalogue, sample.body, sample.rfq_id))

    target = samples[-1]
    result = review_rfq(
        body=target.body,
        rfq_id=target.rfq_id,
        catalogue=catalogue,
        provider=provider,
        memory=memory,
    )
    assert result.extraction.provider == "offline"
    assert result.quote.total_eur >= 0.0
    assert result.flag.kind in {"ok", "high", "low", "no_history"}
