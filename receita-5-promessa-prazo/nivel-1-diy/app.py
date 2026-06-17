"""Recipe 5 — Streamlit scheduling UI (dispatch Tier 1 + CP-SAT Tier 2).

PT: Mostra o plano da fábrica como um Gantt, os atrasos previstos, e responde a
"se aceitar esta encomenda, o que atrasa?". O separador rápido usa a regra de
despacho (Nível 1); o optimizado usa o CP-SAT (Nível 2). Corre com
``streamlit run``.
EN: Shows the factory plan as a Gantt chart, the predicted lateness, and answers
"if I accept this order, what slips?". The fast tab uses the dispatching rule
(Tier 1); the optimised tab uses CP-SAT (Tier 2). Run with ``streamlit run``.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from lib_comum.scheduling import (
    Operation,
    Order,
    ScheduleResult,
    demo_orders,
    schedule_dispatch,
    total_tardiness,
)
from lib_comum.scheduling_cpsat import schedule_cpsat, what_if_accept

st.set_page_config(page_title="Promessa de prazo", page_icon="📅", layout="wide")
st.title("📅 A promessa de prazo que se cumpre")

_BASE = pd.Timestamp("2026-01-05 08:00")


def _gantt(result: ScheduleResult) -> None:
    if not result.scheduled:
        st.info("Sem operações para mostrar.")
        return
    rows = [
        {
            "Máquina": op.machine,
            "Encomenda": op.order_id,
            "Início": _BASE + pd.to_timedelta(op.start_min, unit="m"),
            "Fim": _BASE + pd.to_timedelta(op.end_min, unit="m"),
        }
        for op in result.scheduled
    ]
    fig = px.timeline(
        pd.DataFrame(rows), x_start="Início", x_end="Fim", y="Máquina", color="Encomenda"
    )
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)


orders = demo_orders()
st.caption(f"{len(orders)} encomendas em curso, a passar por corte, CNC, soldadura e acabamento.")

fast_tab, opt_tab = st.tabs(["Rápido — regra EDD (Nível 1)", "Optimizado — CP-SAT (Nível 2)"])

with fast_tab:
    result = schedule_dispatch(orders, rule="EDD")
    a, b, c = st.columns(3)
    a.metric("Atraso total (min)", total_tardiness(result))
    b.metric("Encomendas atrasadas", len(result.late_orders))
    c.metric("Makespan (min)", result.makespan)
    if result.late_orders:
        st.warning("Em risco de atraso: " + ", ".join(result.late_orders))
    _gantt(result)

with opt_tab:
    optimised = schedule_cpsat(orders, max_time_s=8.0)
    a, b, c = st.columns(3)
    a.metric("Atraso total (min)", total_tardiness(optimised))
    b.metric("Encomendas atrasadas", len(optimised.late_orders))
    c.metric("Makespan (min)", optimised.makespan)
    _gantt(optimised)

    st.subheader("E se aceitar esta encomenda?")
    col1, col2 = st.columns(2)
    due = col1.number_input("Prazo prometido (min a partir de agora)", value=200, step=10)
    cnc_min = col2.number_input("Trabalho de CNC (min)", value=90, step=15)
    if st.button("Calcular impacto", type="primary"):
        rush = Order(
            id="OF-NOVA",
            operations=[Operation("cnc", int(cnc_min)), Operation("acabamento", 45)],
            due_min=int(due),
        )
        impact = what_if_accept(orders, rush, max_time_s=8.0)
        on_time = (
            "a tempo"
            if impact.new_order_tardiness == 0
            else f"{impact.new_order_tardiness} min atrasada"
        )
        st.success(f"OF-NOVA sai aos {impact.new_order_completion} min ({on_time}).")
        if impact.slips:
            st.table(
                {
                    "Encomenda": [s.order_id for s in impact.slips],
                    "Saída antes (min)": [s.baseline_completion for s in impact.slips],
                    "Saída depois (min)": [s.new_completion for s in impact.slips],
                    "Desliza (min)": [s.slip_min for s in impact.slips],
                }
            )
        else:
            st.caption("Não atrasa nenhuma encomenda existente.")
