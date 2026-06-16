"""Tests for the Recipe 3 Tier 1 RFQ → quote pipeline.

Uses the offline regex provider so the suite has no network dependency and
the assertions are deterministic.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lib_comum.data_synth import rfq as rfq_data
from lib_comum.llm import OfflineProvider, make_provider
from lib_comum.quote_pricing import price_quote, render_quote_text


@pytest.fixture(scope="module")
def catalogue() -> pd.DataFrame:
    return rfq_data.load_catalogue()


@pytest.fixture(scope="module")
def samples() -> list[rfq_data.RFQSample]:
    return rfq_data.generate_samples(n=8, seed=20260509)


def test_catalogue_columns_and_dtypes(catalogue: pd.DataFrame) -> None:
    expected = {"operation", "material", "thickness_mm", "unit", "unit_price_eur"}
    assert set(catalogue.columns) == expected
    assert catalogue["unit_price_eur"].dtype.kind == "f"
    # Per-operation pricing should cover every operation we generate.
    assert set(catalogue["operation"].unique()) >= {
        "corte_laser",
        "dobragem",
        "soldadura",
        "furacao",
        "rebarbagem",
        "pintura_epoxy",
        "montagem",
    }


def test_offline_provider_extracts_majority_of_items(
    samples: list[rfq_data.RFQSample],
) -> None:
    """Offline regex provider must hit ≥80% of items across the corpus."""
    provider = OfflineProvider()
    total = 0
    matched = 0
    for sample in samples:
        extraction = provider.extract_rfq(sample.body)
        for gt, ex in zip(sample.items, extraction.items, strict=False):
            total += 1
            if gt.operation == ex.operation and gt.quantity == ex.quantity:
                matched += 1
    assert total > 0
    assert matched / total >= 0.80, f"Offline accuracy too low: {matched}/{total}"


def test_offline_provider_recovers_form_customer(
    samples: list[rfq_data.RFQSample],
) -> None:
    provider = OfflineProvider()
    form_samples = [s for s in samples if s.channel == "form"]
    assert form_samples, "the corpus should include at least one form-channel sample"
    extraction = provider.extract_rfq(form_samples[0].body)
    assert extraction.customer == form_samples[0].customer


def test_offline_provider_extracts_deadline(samples: list[rfq_data.RFQSample]) -> None:
    provider = OfflineProvider()
    for sample in samples:
        extraction = provider.extract_rfq(sample.body)
        assert extraction.deadline_days == sample.deadline_days


def test_pricing_engine_totals_match_manual(catalogue: pd.DataFrame) -> None:
    items = [
        # 30 m of laser cut on 2 mm 304 stainless: catalogue says €0.80/m
        # -> 30 * 0.80 = 24.00
        rfq_data.GroundTruthItem(
            operation="corte_laser",
            material="aço inox 304",
            thickness_mm=2.0,
            quantity=30,
        ),
    ]
    # Map ground truth to the extraction shape for price_quote().
    from lib_comum.llm import ExtractedLineItem

    extracted = [
        ExtractedLineItem(
            operation=it.operation,
            material=it.material,
            thickness_mm=it.thickness_mm,
            quantity=it.quantity,
        )
        for it in items
    ]
    quote = price_quote(
        items=extracted,
        catalogue=catalogue,
        rfq_id="RFQ-TEST",
        customer="Teste Lda.",
        deadline_days=10,
        margin_pct=20.0,
        vat_pct=23.0,
    )
    assert len(quote.items) == 1
    assert quote.subtotal_eur == pytest.approx(24.00, abs=0.01)
    # margin 20% on 24 = 4.80; pre-VAT = 28.80; VAT 23% on 28.80 = 6.62
    # total = 28.80 + 6.62 = 35.42
    assert quote.margin_eur == pytest.approx(4.80, abs=0.01)
    assert quote.pre_vat_total_eur == pytest.approx(28.80, abs=0.01)
    assert quote.vat_eur == pytest.approx(6.62, abs=0.01)
    assert quote.total_eur == pytest.approx(35.42, abs=0.01)


def test_pricing_engine_logs_unresolved_items(catalogue: pd.DataFrame) -> None:
    from lib_comum.llm import ExtractedLineItem

    quote = price_quote(
        items=[
            ExtractedLineItem(
                operation="operacao_inexistente",
                material="",
                thickness_mm=0.0,
                quantity=5,
            )
        ],
        catalogue=catalogue,
        rfq_id="RFQ-UNK",
        customer=None,
        deadline_days=None,
    )
    assert quote.items == []
    assert len(quote.unresolved_items) == 1
    assert quote.subtotal_eur == 0.0
    assert quote.total_eur == 0.0


def test_render_quote_text_contains_total(catalogue: pd.DataFrame) -> None:
    from lib_comum.llm import ExtractedLineItem

    quote = price_quote(
        items=[
            ExtractedLineItem(
                operation="furacao",
                material="",
                thickness_mm=0.0,
                quantity=20,
            )
        ],
        catalogue=catalogue,
        rfq_id="RFQ-TXT",
        customer="Cliente",
        deadline_days=14,
    )
    text = render_quote_text(quote)
    assert "Orçamento RFQ-TXT" in text
    assert "TOTAL" in text
    assert "furacao" in text


def test_make_provider_offline_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")  # would normally pick anthropic
    provider = make_provider()
    # Without an API key, we must fall back to the offline provider.
    assert provider.name == "offline"
