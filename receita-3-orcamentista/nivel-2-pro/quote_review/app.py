"""Recipe 3 Tier 2 — Streamlit review UI with two-click approval.

PT: Interface de revisão humana. Mostra a extracção, o orçamento, os orçamentos
passados mais parecidos e o *flag* de coerência de preço. O revisor aprova ou
rejeita em dois cliques; aprovar guarda o orçamento na memória e melhora o
próximo. Corre com ``streamlit run`` (ver ``make demo-r3-n2-ui``).
EN: Human review UI. Shows the extraction, the quote, the most similar past
quotes and the price-consistency flag. The reviewer approves or rejects in two
clicks; approving stores the quote in memory and improves the next one.
"""

from __future__ import annotations

import streamlit as st

from lib_comum.data_synth import rfq as rfq_data
from lib_comum.llm import make_provider
from lib_comum.quote_memory import QuoteMemory
from lib_comum.quote_pricing import render_quote_text
from lib_comum.quote_review import ReviewResult, record_approved, review_rfq

st.set_page_config(page_title="Revisão de orçamentos", page_icon="✅", layout="wide")


@st.cache_resource
def _catalogue() -> object:
    return rfq_data.load_catalogue()


def _memory() -> QuoteMemory:
    mem = st.session_state.get("memory")
    if not isinstance(mem, QuoteMemory):
        mem = QuoteMemory()
        st.session_state["memory"] = mem
    return mem


st.title("✅ Revisão de orçamentos — Nível 2")

with st.sidebar:
    st.header("Definições")
    provider_name = st.selectbox("Fornecedor de IA", ["offline", "anthropic"], index=0)
    seed = int(st.number_input("Seed dos pedidos sintéticos", value=20260509, step=1))
    st.caption(f"Orçamentos na memória: {len(_memory())}")

catalogue = _catalogue()
provider = make_provider("anthropic" if provider_name == "anthropic" else "offline")
samples = rfq_data.generate_samples(n=8, seed=seed)

labels = [f"{s.rfq_id} · {s.channel} · {len(s.items)} itens" for s in samples]
choice = st.selectbox("Pedido a rever", range(len(samples)), format_func=lambda i: labels[i])
sample = samples[choice]
st.code(sample.body)

if st.button("Rever orçamento", type="primary"):
    st.session_state["result"] = review_rfq(
        body=sample.body,
        rfq_id=sample.rfq_id,
        catalogue=catalogue,
        provider=provider,
        memory=_memory(),
    )

result = st.session_state.get("result")
if isinstance(result, ReviewResult):
    flag = result.flag
    if flag.kind == "high" or flag.kind == "low":
        st.warning(flag.message)
    elif flag.kind == "ok":
        st.success(flag.message)
    else:
        st.info(flag.message)

    left, right = st.columns(2)
    with left:
        st.subheader("Orçamento")
        st.metric("Total (c/ IVA)", f"€{result.quote.total_eur:.2f}")
        st.code(render_quote_text(result.quote))
    with right:
        st.subheader("Pedidos semelhantes (histórico)")
        if result.similar:
            st.table(
                {
                    "rfq": [s.rfq_id for s in result.similar],
                    "total €": [round(s.total_eur, 2) for s in result.similar],
                    "semelhança": [round(s.similarity, 2) for s in result.similar],
                }
            )
        else:
            st.caption("Sem histórico ainda — aprove alguns para começar a comparar.")

    approve, reject = st.columns(2)
    with approve:
        if st.button("✅ Aprovar e guardar"):
            record_approved(_memory(), result.quote.rfq_id, sample.body, result.quote)
            st.success(f"Aprovado. Memória: {len(_memory())} orçamentos.")
            st.session_state.pop("result", None)
    with reject:
        if st.button("✖ Rejeitar"):
            st.session_state.pop("result", None)
            st.info("Rejeitado — não foi guardado.")
