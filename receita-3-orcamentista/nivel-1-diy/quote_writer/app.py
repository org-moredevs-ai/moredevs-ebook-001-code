"""Streamlit review UI for Recipe 3 Tier 1.

PT: Cola um RFQ, escolhe o fornecedor (Anthropic ou offline), vê os
itens extraídos lado a lado com o catálogo e exporta o orçamento.
EN: Paste an RFQ, pick the provider (Anthropic or offline), see the
extracted items next to the catalogue and export the quote.

Run with::

    uv run streamlit run receita-3-orcamentista/nivel-1-diy/quote_writer/app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Allow the script to be invoked directly with `streamlit run`. The pricing
# module lives in lib_comum; for the pipeline module we import via path.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib_comum.data_synth import rfq as rfq_data  # noqa: E402
from lib_comum.llm import ProviderName, make_provider  # noqa: E402
from lib_comum.quote_pricing import (  # noqa: E402
    DEFAULT_MARGIN_PCT,
    DEFAULT_VAT_PCT,
    price_quote,
    render_quote_text,
)

st.set_page_config(
    page_title="Orçamentista que não dorme",
    page_icon="🧮",
    layout="wide",
)

st.title("🧮 Orçamentista que não dorme")
st.caption(
    "Cola um pedido de orçamento (RFQ) — o sistema extrai os itens, "
    "cruza com o catálogo e devolve um orçamento totalizado."
)


with st.sidebar:
    st.header("Definições")
    default_provider: ProviderName = (
        "offline" if not os.environ.get("ANTHROPIC_API_KEY") else "anthropic"
    )
    provider_name = st.selectbox(
        "Fornecedor LLM",
        options=["anthropic", "offline"],
        index=0 if default_provider == "anthropic" else 1,
        help=(
            "Anthropic precisa de ANTHROPIC_API_KEY no ambiente. O fornecedor "
            "offline usa regex e funciona sem rede."
        ),
    )
    margin_pct = st.slider(
        "Margem (%)", min_value=5.0, max_value=40.0, value=DEFAULT_MARGIN_PCT, step=0.5
    )
    vat_pct = st.slider("IVA (%)", min_value=6.0, max_value=23.0, value=DEFAULT_VAT_PCT, step=0.5)
    seed = st.number_input("Seed para RFQ sintético", min_value=0, value=20260509, step=1)

st.subheader("Pedido (RFQ)")
sample_choice = st.radio(
    "Origem do RFQ",
    options=["Gerar sintético", "Colar texto"],
    horizontal=True,
)
body = ""
rfq_id = "RFQ-LIVE"
if sample_choice == "Gerar sintético":
    samples = rfq_data.generate_samples(n=8, seed=int(seed))
    labels = [f"{s.rfq_id} · {s.channel} · {len(s.items)} itens" for s in samples]
    idx = st.selectbox(
        "Escolhe um exemplo", options=list(range(len(samples))), format_func=lambda i: labels[i]
    )
    sample = samples[idx]
    body = sample.body
    rfq_id = sample.rfq_id
else:
    body = st.text_area(
        "Texto do RFQ",
        height=240,
        placeholder="Olá, preciso de orçamento para...",
    )
    rfq_id = st.text_input("ID do RFQ", value="RFQ-LIVE")

st.code(body, language="text")

if st.button("Gerar orçamento", type="primary", disabled=not body.strip()):
    provider = make_provider(provider_name)
    extraction = provider.extract_rfq(body)
    catalogue = rfq_data.load_catalogue()
    quote = price_quote(
        items=extraction.items,
        catalogue=catalogue,
        rfq_id=rfq_id,
        customer=extraction.customer,
        deadline_days=extraction.deadline_days,
        margin_pct=margin_pct,
        vat_pct=vat_pct,
    )

    col_left, col_right = st.columns([1, 1])
    with col_left:
        st.subheader("Extracção")
        st.caption(f"Fornecedor: **{extraction.provider}**")
        st.caption(f"Cliente: **{extraction.customer or '(?)'}**")
        st.caption(f"Prazo: **{extraction.deadline_days or '(?)'} dias**")
        if extraction.items:
            df = pd.DataFrame(
                [
                    {
                        "operação": it.operation,
                        "material": it.material,
                        "espessura_mm": it.thickness_mm,
                        "qtd": it.quantity,
                    }
                    for it in extraction.items
                ]
            )
            st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            st.warning("Sem itens extraídos.")
    with col_right:
        st.subheader("Orçamento")
        if quote.items:
            df = pd.DataFrame(
                [
                    {
                        "operação": item.operation,
                        "material": item.material,
                        "qtd": item.quantity,
                        "unidade": item.unit,
                        "preço unit. (€)": item.unit_price_eur,
                        "subtotal (€)": item.subtotal_eur,
                    }
                    for item in quote.items
                ]
            )
            st.dataframe(df, hide_index=True, use_container_width=True)
            st.metric("Subtotal", f"€ {quote.subtotal_eur:,.2f}")
            st.metric(
                f"Margem ({quote.margin_pct:.0f}%)",
                f"€ {quote.margin_eur:,.2f}",
            )
            st.metric(f"IVA ({quote.vat_pct:.0f}%)", f"€ {quote.vat_eur:,.2f}")
            st.metric("Total", f"€ {quote.total_eur:,.2f}")
        if quote.unresolved_items:
            st.warning(
                f"{len(quote.unresolved_items)} itens não foram encontrados no catálogo — revisão humana necessária."
            )

    st.subheader("Texto pronto a enviar")
    quote_text = render_quote_text(quote)
    st.code(quote_text, language="text")
    st.download_button(
        "📄 Descarregar (.txt)",
        data=quote_text.encode("utf-8"),
        file_name=f"{quote.rfq_id}.txt",
        mime="text/plain",
    )
