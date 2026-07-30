"""Recipe 5 — Streamlit scheduling UI (dispatch Tier 1 + CP-SAT Tier 2).

PT: Mostra o plano da fábrica como um Gantt, os atrasos previstos (a vermelho), e
responde a "se aceitar esta encomenda, o que atrasa?". O separador rápido usa a
regra de despacho (Nível 1); o optimizado usa o CP-SAT (Nível 2). Corre com
``streamlit run``.
EN: Shows the factory plan as a Gantt chart, the predicted lateness (in red), and
answers "if I accept this order, what slips?". The fast tab uses the dispatching
rule (Tier 1); the optimised tab uses CP-SAT (Tier 2). Run with ``streamlit run``.
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
_LATE = "⚠️ vai atrasar"
_ON_TIME = "a tempo"
# Fixed machine order = the real factory flow (cut -> CNC -> weld -> finish), so the
# rows stay in the SAME order in both the EDD and the CP-SAT Gantt (never reshuffled).
_MACHINE_FLOW = ["corte", "cnc", "soldadura", "acabamento"]


def _clock(minutes: int) -> str:
    """Minutes from the plan's 08:00 base -> 'DD/MM HH:MM' (a real clock time)."""
    return (_BASE + pd.to_timedelta(minutes, unit="m")).strftime("%d/%m %H:%M")


def _gantt(result: ScheduleResult) -> None:
    """Draw the plan: late orders in red, with ▶/● marking each order's first and
    last operation so a single order is easy to follow across the machines."""
    if not result.scheduled:
        st.info("Sem operações para mostrar.")
        return
    late = set(result.late_orders)
    last_idx: dict[str, int] = {}
    for op in result.scheduled:
        last_idx[op.order_id] = max(last_idx.get(op.order_id, -1), op.op_index)
    rows = []
    for op in result.scheduled:
        label = op.order_id
        if op.op_index == 0:
            label = "▶ " + label  # first operation (start)
        if op.op_index == last_idx[op.order_id]:
            label = label + " ●"  # last operation (delivery)
        rows.append(
            {
                "Máquina": op.machine,
                "Etapa": label,
                "Estado": _LATE if op.order_id in late else _ON_TIME,
                "Início": _BASE + pd.to_timedelta(op.start_min, unit="m"),
                "Fim": _BASE + pd.to_timedelta(op.end_min, unit="m"),
            }
        )
    fig = px.timeline(
        pd.DataFrame(rows),
        x_start="Início",
        x_end="Fim",
        y="Máquina",
        color="Estado",
        text="Etapa",
        color_discrete_map={_LATE: "#e03131", _ON_TIME: "#4c6ef5"},
        category_orders={"Estado": [_LATE, _ON_TIME], "Máquina": _MACHINE_FLOW},
    )
    # Keep the flow top-to-bottom (corte at the top); the fixed category order above
    # guarantees both Gantts use the same rows regardless of the schedule.
    fig.update_yaxes(categoryorder="array", categoryarray=list(reversed(_MACHINE_FLOW)))
    fig.update_traces(textposition="inside", insidetextanchor="middle")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "**▶** = 1ª operação (arranque) · **●** = última operação (entrega prevista). "
        "Barras **a vermelho** = encomendas que vão falhar o prazo."
    )


def _schedule_table(result: ScheduleResult) -> None:
    """A per-order board with clock times: when each order starts, its promised
    date, and its predicted ship date — so the minutes actually mean something."""
    if not result.scheduled:
        return
    starts: dict[str, int] = {}
    for op in result.scheduled:
        starts[op.order_id] = min(starts.get(op.order_id, op.start_min), op.start_min)

    rows = [
        {
            "Encomenda": oid,
            "Início": _clock(starts[oid]),
            "Entrega prevista": _clock(result.completion[oid]),
            "Prazo prometido": _clock(due_by_id[oid]),
            "Estado": (
                "✅ a tempo"
                if result.tardiness[oid] == 0
                else f"⚠️ atrasada +{result.tardiness[oid]} min"
            ),
        }
        for oid in sorted(starts, key=lambda o: due_by_id[o])
    ]
    st.caption(
        "Quadro das encomendas — por ordem de **prazo prometido** (a mais urgente "
        "primeiro), a prioridade de despacho da regra EDD. Compare com a coluna "
        "**Início**: o plano segue esta ordem, salvo quando a máquina necessária está "
        "ocupada. 08:00 do dia 05/01 é o instante zero."
    )
    board = pd.DataFrame(rows)
    # Bold the "Prazo prometido" column: it is the one the board is sorted by.
    styled = board.style.set_properties(subset=["Prazo prometido"], **{"font-weight": "bold"})
    st.dataframe(styled, hide_index=True, use_container_width=True)


orders = demo_orders()
due_by_id = {o.id: o.due_min for o in orders}
st.caption(f"{len(orders)} encomendas em curso, a passar por corte, CNC, soldadura e acabamento.")

fast_tab, opt_tab = st.tabs(["Rápido — regra EDD (Nível 1)", "Optimizado — CP-SAT (Nível 2)"])

with fast_tab:
    result = schedule_dispatch(orders, rule="EDD")
    a, b, c = st.columns(3)
    a.metric("Atraso total (min)", total_tardiness(result))
    b.metric("Encomendas atrasadas", len(result.late_orders))
    c.metric("Makespan (min)", result.makespan)
    if result.late_orders:
        late_txt = " · ".join(
            f"**{oid}** (+{result.tardiness[oid]} min)" for oid in result.late_orders
        )
        st.error(
            f"⚠️ {len(result.late_orders)} encomenda(s) vão **falhar o prazo**: {late_txt}. "
            "São as barras **a vermelho** no plano — o atraso vê-se hoje, não no dia da entrega."
        )
    else:
        st.success("Todas as encomendas saem a tempo com a regra EDD.")
    _gantt(result)
    _schedule_table(result)

with opt_tab:
    optimised = schedule_cpsat(orders, max_time_s=8.0)
    edd_tard = total_tardiness(result)
    opt_tard = total_tardiness(optimised)
    a, b, c = st.columns(3)
    a.metric(
        "Atraso total (min)",
        opt_tard,
        delta=f"{opt_tard - edd_tard} vs EDD",
        delta_color="inverse",
    )
    b.metric(
        "Encomendas atrasadas",
        len(optimised.late_orders),
        delta=f"{len(optimised.late_orders) - len(result.late_orders)} vs EDD",
        delta_color="inverse",
    )
    c.metric("Makespan (min)", optimised.makespan)
    if opt_tard < edd_tard:
        st.success(
            f"O optimizador reduziu o atraso total de **{edd_tard}** para **{opt_tard} min** "
            f"({len(result.late_orders)} → {len(optimised.late_orders)} encomendas atrasadas) — "
            "a mesma fábrica, melhor plano."
        )
    _gantt(optimised)
    _schedule_table(optimised)

    st.divider()
    st.subheader("E se aceitar esta encomenda urgente?")
    col1, col2 = st.columns(2)
    due = col1.number_input("Prazo prometido (minutos a partir das 08:00)", value=560, step=10)
    col1.caption(f"↳ prazo = **{_clock(int(due))}**")
    cnc_min = col2.number_input("Trabalho de CNC (min)", value=90, step=15)
    if st.button("Calcular impacto", type="primary"):
        rush = Order(
            id="OF-NOVA",
            operations=[Operation("cnc", int(cnc_min)), Operation("acabamento", 45)],
            due_min=int(due),
        )
        with st.spinner("A optimizar o plano com e sem a OF-NOVA…"):
            impact = what_if_accept(orders, rush, max_time_s=8.0)
        added = impact.total_tardiness_after - impact.total_tardiness_before
        if impact.new_order_tardiness == 0 and added <= 0:
            st.success(
                f"✅ **Pode aceitar a OF-NOVA.** Sai a **{_clock(impact.new_order_completion)}** "
                f"(prazo {_clock(int(due))} — a tempo), e o atraso total das outras encomendas "
                f"**não aumenta** ({impact.total_tardiness_before} → {impact.total_tardiness_after} min)."
            )
        elif impact.new_order_tardiness == 0:
            st.warning(
                f"OF-NOVA sai a tempo ({_clock(impact.new_order_completion)}), mas aceitá-la faz o "
                f"atraso total das outras subir **+{added} min** "
                f"({impact.total_tardiness_before} → {impact.total_tardiness_after})."
            )
        else:
            st.error(
                f"OF-NOVA só sairia a {_clock(impact.new_order_completion)} — "
                f"**{impact.new_order_tardiness} min depois** do prazo. Renegocie a data ou recuse."
            )
        if impact.slips:
            st.caption(
                "Deslizar não é atrasar — veja se cada encomenda que se mexe continua no prazo:"
            )
            st.table(
                {
                    "Encomenda": [s.order_id for s in impact.slips],
                    "Saída antes": [_clock(s.baseline_completion) for s in impact.slips],
                    "Saída depois": [_clock(s.new_completion) for s in impact.slips],
                    "Desliza (min)": [f"+{s.slip_min}" for s in impact.slips],
                    "Continua a tempo?": [
                        "✅ sim"
                        if s.new_completion <= due_by_id.get(s.order_id, 10**9)
                        else "❌ passa a atrasada"
                        for s in impact.slips
                    ],
                }
            )
        else:
            st.caption("E não mexe em mais nenhuma encomenda.")
