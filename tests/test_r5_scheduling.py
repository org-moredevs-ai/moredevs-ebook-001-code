"""Recipe 5 — scheduling tests (dispatch + CP-SAT + what-if), deterministic.

PT: Testa a regra de despacho, o optimizador CP-SAT e a função de impacto de
aceitação. Verifica viabilidade (precedência e não-sobreposição de máquinas) e
que o optimizador nunca é pior do que a regra.
EN: Tests the dispatching rule, the CP-SAT optimiser and the acceptance-impact
function. Checks feasibility (precedence and machine non-overlap) and that the
optimiser is never worse than the rule.
"""

from __future__ import annotations

from itertools import pairwise

from lib_comum.scheduling import (
    Operation,
    Order,
    ScheduledOp,
    demo_orders,
    schedule_dispatch,
    total_tardiness,
)
from lib_comum.scheduling_cpsat import schedule_cpsat, what_if_accept


def _no_machine_overlap(scheduled: list[ScheduledOp]) -> bool:
    by_machine: dict[str, list[tuple[int, int]]] = {}
    for op in scheduled:
        by_machine.setdefault(op.machine, []).append((op.start_min, op.end_min))
    for intervals in by_machine.values():
        intervals.sort()
        for (_s1, e1), (s2, _e2) in pairwise(intervals):
            if s2 < e1:
                return False
    return True


def _precedence_ok(scheduled: list[ScheduledOp], orders: list[Order]) -> bool:
    by_order: dict[str, dict[int, tuple[int, int]]] = {}
    for op in scheduled:
        by_order.setdefault(op.order_id, {})[op.op_index] = (op.start_min, op.end_min)
    for order in orders:
        steps = by_order.get(order.id, {})
        for i in range(len(order.operations) - 1):
            if steps[i + 1][0] < steps[i][1]:
                return False
    return True


def test_dispatch_is_feasible() -> None:
    orders = demo_orders()
    result = schedule_dispatch(orders, rule="EDD")
    assert len(result.scheduled) == sum(len(o.operations) for o in orders)
    assert _no_machine_overlap(result.scheduled)
    assert _precedence_ok(result.scheduled, orders)
    assert result.makespan > 0


def test_cpsat_is_feasible_and_not_worse_than_dispatch() -> None:
    orders = demo_orders()
    dispatch = schedule_dispatch(orders, rule="EDD")
    optimised = schedule_cpsat(orders, max_time_s=8.0)
    assert _no_machine_overlap(optimised.scheduled)
    assert _precedence_ok(optimised.scheduled, orders)
    assert total_tardiness(optimised) <= total_tardiness(dispatch)


def test_what_if_accept_reports_impact() -> None:
    orders = demo_orders()
    rush = Order(
        id="OF-RUSH",
        operations=[Operation("cnc", 90), Operation("acabamento", 45)],
        due_min=200,
    )
    result = what_if_accept(orders, rush, max_time_s=8.0)
    # Accepting an order cannot reduce total tardiness of the existing set.
    assert result.total_tardiness_after >= result.total_tardiness_before
    # The new order can't finish before its own work content.
    assert result.new_order_completion >= 90 + 45
    # Every reported slip refers to an existing order.
    existing_ids = {o.id for o in orders}
    for slip in result.slips:
        assert slip.order_id in existing_ids
        assert slip.slip_min == slip.new_completion - slip.baseline_completion


def test_dispatch_rules_are_accepted() -> None:
    orders = demo_orders()
    for rule in ("EDD", "SPT", "FIFO"):
        result = schedule_dispatch(orders, rule=rule)
        assert len(result.scheduled) == sum(len(o.operations) for o in orders)
