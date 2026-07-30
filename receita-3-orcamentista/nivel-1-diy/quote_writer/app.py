"""Streamlit UI for Recipe 3 Tier 1 — the quote writer.

PT: Cola (ou escolhe) um RFQ, escolhe o fornecedor (Claude ou offline), vê os
itens extraídos e o orçamento totalizado, e compara os dois fornecedores lado a
lado — para ver onde o regex offline fica aquém de um modelo de IA num pedido
escrito de qualquer maneira.
EN: Paste/pick an RFQ, pick the provider (Claude or offline), see the extracted
items and the priced quote, and compare both providers side by side.

Run with::

    uv run streamlit run receita-3-orcamentista/nivel-1-diy/quote_writer/app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib_comum.data_synth import rfq as rfq_data  # noqa: E402
from lib_comum.llm import RfqExtraction, make_provider  # noqa: E402
from lib_comum.quote_pricing import (  # noqa: E402
    DEFAULT_MARGIN_PCT,
    DEFAULT_VAT_PCT,
    price_quote,
    render_quote_text,
)

st.set_page_config(page_title="Orçamentista que não dorme", page_icon="🧮", layout="wide")

# ---------------------------------------------------------------------------
# Exemplos curados — de um pedido arrumado (o regex dá conta) a um pedido real,
# informal e com vários itens implícitos (onde só o modelo de IA acerta).
# ---------------------------------------------------------------------------
CURATED = {
    "🟢 Simples e arrumado (o offline dá conta)": (
        "Pedido de orçamento — Serralharia Costa, Lda.\n"
        "- corte laser em aço inox 304, espessura 2 mm, 30 m de corte\n"
        "- dobragem em aço inox 304, espessura 2 mm, 20 dobras\n"
        "- soldadura em aço inox 304, 12 m de cordão\n"
        "Prazo: 10 dias.\n"
        "Cumprimentos, Serralharia Costa"
    ),
    "🔴 Informal e complexo (o offline falha, o Claude resolve)": (
        "Bom dia! Precisávamos de uma cotação com alguma urgência.\n"
        "É assim: umas 40 chapas cortadas a laser em inox 304 de 3 mm, cada uma leva "
        "4 furos de 8 mm e depois é dobrada em U.\n"
        "Também uns 25 suportes soldados em aço S275, cada um com 2 cordões de soldadura.\n"
        "E depois pintar tudo, epoxy cinza RAL 7016, a área anda pelos 18 m².\n"
        "Isto era para termos até dia 20, senão fim do mês. Cliente: Metalúrgica Silva & "
        "Filhos. Obrigado!"
    ),
    "🔴 Email desorganizado (misturado, com ruído)": (
        "Olá boa tarde, na sequência da visita à fábrica envio o que falámos.\n"
        "Precisamos de umas guardas de proteção — chapa perfurada não, chapa lisa de "
        "alumínio 5754 de 2 mm, cortadas a laser, são 12 painéis de 2x1 m, e cada painel "
        "leva 6 dobras.\n"
        "Já agora aproveitem e orcem também a soldadura das cantoneiras (aço carbono S235), "
        "à volta de 60 metros de cordão no total.\n"
        "Não corre pressa mas se der para 3 semanas agradecia. Cumprimentos, Eng. Nuno "
        "Ferreira, Construções Metálicas do Vouga."
    ),
}


def _extraction_table(extraction: RfqExtraction) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "operação": it.operation,
                "material": it.material or "—",
                "esp. (mm)": it.thickness_mm,
                "qtd": it.quantity,
                "nota": it.note or "",
            }
            for it in extraction.items
        ]
    )


# ---------------------------------------------------------------------------
# Cabeçalho + definições
# ---------------------------------------------------------------------------
st.title("🧮 Orçamentista que não dorme")
st.caption(
    "Cola um pedido de orçamento (RFQ) — o sistema extrai os itens, cruza com o "
    "catálogo e devolve um orçamento totalizado. A **extracção** é feita por IA; a "
    "**aritmética** é código determinístico."
)

paid_available = bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
with st.sidebar:
    st.header("Definições")
    provider_name = st.selectbox(
        "Fornecedor de extracção",
        options=["anthropic", "offline"],
        index=0 if paid_available else 1,
        format_func=lambda p: (
            "Claude (nuvem, pago)" if p == "anthropic" else "Offline (regex, grátis)"
        ),
        help=(
            "Claude precisa de OPENROUTER_API_KEY (ou ANTHROPIC_API_KEY) no ambiente. "
            "O offline usa expressões regulares e funciona sem rede."
        ),
    )
    if provider_name == "anthropic" and not paid_available:
        st.warning("Sem chave de IA no ambiente — o Claude vai recorrer ao modo offline.")
    margin_pct = st.slider("Margem (%)", 5.0, 40.0, DEFAULT_MARGIN_PCT, 0.5)
    vat_pct = st.slider("IVA (%)", 6.0, 23.0, DEFAULT_VAT_PCT, 0.5)

# ---------------------------------------------------------------------------
# Escolha do pedido
# ---------------------------------------------------------------------------
st.subheader("Pedido (RFQ)")
source = st.radio(
    "Origem",
    ["Exemplos reais", "Sintético", "Colar texto"],
    horizontal=True,
    label_visibility="collapsed",
)
rfq_id = "RFQ-LIVE"
if source == "Exemplos reais":
    label = st.selectbox("Escolhe um exemplo", options=list(CURATED.keys()))
    body = CURATED[label]
    rfq_id = "RFQ-" + ("SIMPLES" if label.startswith("🟢") else "COMPLEXO")
elif source == "Sintético":
    seed = st.number_input("Seed", min_value=0, value=20260509, step=1)
    samples = rfq_data.generate_samples(n=8, seed=int(seed))
    idx = st.selectbox(
        "Escolhe um exemplo",
        options=list(range(len(samples))),
        format_func=lambda i: (
            f"{samples[i].rfq_id} · {samples[i].channel} · {len(samples[i].items)} itens"
        ),
    )
    body, rfq_id = samples[idx].body, samples[idx].rfq_id
else:
    body = st.text_area("Texto do RFQ", height=200, placeholder="Olá, preciso de orçamento para...")
    rfq_id = st.text_input("ID do RFQ", value="RFQ-LIVE")

st.text_area(
    "Pedido a processar", value=body, height=170, disabled=True, label_visibility="collapsed"
)

c1, c2 = st.columns(2)
go = c1.button(
    "Gerar orçamento", type="primary", use_container_width=True, disabled=not body.strip()
)
compare = c2.button(
    "⚖️  Comparar offline vs Claude", use_container_width=True, disabled=not body.strip()
)


def _render_quote(extraction: RfqExtraction) -> None:
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
    left, right = st.columns([3, 2])
    with left:
        st.markdown("##### Extracção")
        st.caption(
            f"Fornecedor: **{extraction.provider}** · Cliente: **{extraction.customer or '(?)'}** · "
            f"Prazo: **{extraction.deadline_days or '(?)'} dias** · Itens: **{len(extraction.items)}**"
        )
        if extraction.items:
            st.dataframe(_extraction_table(extraction), hide_index=True, use_container_width=True)
        else:
            st.error("Sem itens extraídos — o pedido escapou ao fornecedor.")
    with right:
        st.markdown("##### Orçamento")
        if quote.items:
            m1, m2 = st.columns(2)
            m1.metric("Subtotal", f"€ {quote.subtotal_eur:,.2f}")
            m2.metric("Total (c/ IVA)", f"€ {quote.total_eur:,.2f}")
            st.caption(f"Margem {quote.margin_pct:.0f}% · IVA {quote.vat_pct:.0f}%")
        if quote.unresolved_items:
            st.warning(
                f"{len(quote.unresolved_items)} itens não encontrados no catálogo — revisão humana."
            )
    st.markdown("##### Texto pronto a enviar")
    st.text_area("quote", value=render_quote_text(quote), height=240, label_visibility="collapsed")
    st.download_button(
        "📄 Descarregar (.txt)",
        data=render_quote_text(quote).encode("utf-8"),
        file_name=f"{quote.rfq_id}.txt",
        mime="text/plain",
    )


if go:
    with st.spinner("A extrair e a orçamentar…"):
        _render_quote(make_provider(provider_name).extract_rfq(body))

if compare:
    st.divider()
    st.subheader("⚖️  Offline (regex) vs Claude (IA)")
    with st.spinner("A correr os dois fornecedores…"):
        off = make_provider("offline").extract_rfq(body)
        ai = make_provider("anthropic").extract_rfq(body)
    a, b = st.columns(2)
    with a:
        st.markdown(f"#### 🔧 Offline — **{len(off.items)}** itens")
        st.caption(f"cliente: {off.customer or '(?)'} · prazo: {off.deadline_days or '(?)'} dias")
        st.dataframe(
            _extraction_table(off) if off.items else pd.DataFrame(),
            hide_index=True,
            use_container_width=True,
        )
    with b:
        st.markdown(f"#### 🤖 Claude — **{len(ai.items)}** itens")
        st.caption(
            f"cliente: {ai.customer or '(?)'} · prazo: {ai.deadline_days or '(?)'} dias · modelo: {ai.audit_metadata.get('model', '?')}"
        )
        st.dataframe(
            _extraction_table(ai) if ai.items else pd.DataFrame(),
            hide_index=True,
            use_container_width=True,
        )
    gained = len(ai.items) - len(off.items)
    if gained > 0:
        st.success(
            f"O modelo de IA extraiu **mais {gained} item(s)** e campos que o regex deixou "
            f"escapar — é a diferença entre um orçamento completo e um pela metade."
        )
