"""Recipe 5 Tier 2 — optimal(ish) job-shop scheduling with OR-Tools CP-SAT.

PT: Optimiza o plano em vez de aplicar uma regra. Cada operação é um intervalo;
cada encomenda respeita a sua sequência; cada máquina só faz uma operação de
cada vez (NoOverlap). O objectivo é minimizar a soma dos atrasos. E responde à
pergunta que vale dinheiro — ``what_if_accept`` — quantificando o impacto de
aceitar uma encomenda nova: o que atrasa, e quanto.

EN: Optimises the plan instead of applying a rule. Each operation is an
interval; each order respects its sequence; each machine runs one operation at a
time (NoOverlap). The objective minimises total tardiness. And it answers the
money question — ``what_if_accept`` — quantifying the impact of accepting a new
order: what slips, and by how much.
"""

from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from lib_comum.scheduling import Order, ScheduledOp, ScheduleResult

DEFAULT_SEED = 20260509


def schedule_cpsat(orders: list[Order], *, max_time_s: float = 10.0) -> ScheduleResult:
    """Minimise total tardiness with CP-SAT. Returns the best schedule found.

    PT: Minimiza a soma dos atrasos dentro do orçamento de tempo.
    EN: Minimises total tardiness within the time budget.
    """
    by_id = {o.id: o for o in orders}
    if not orders:
        return ScheduleResult([], {}, {}, [], 0)

    horizon = sum(o.total_work_min for o in orders) + max(o.release_min for o in orders)
    model = cp_model.CpModel()

    starts: dict[tuple[str, int], cp_model.IntVar] = {}
    ends: dict[tuple[str, int], cp_model.IntVar] = {}
    machine_intervals: dict[str, list[cp_model.IntervalVar]] = {}
    last_end: dict[str, cp_model.IntVar] = {}

    for order in orders:
        prev_end: cp_model.IntVar | None = None
        for i, op in enumerate(order.operations):
            start = model.new_int_var(order.release_min, horizon, f"s_{order.id}_{i}")
            end = model.new_int_var(order.release_min, horizon, f"e_{order.id}_{i}")
            interval = model.new_interval_var(start, op.duration_min, end, f"iv_{order.id}_{i}")
            starts[(order.id, i)] = start
            ends[(order.id, i)] = end
            machine_intervals.setdefault(op.machine, []).append(interval)
            if prev_end is not None:
                model.add(start >= prev_end)
            prev_end = end
        if prev_end is not None:
            last_end[order.id] = prev_end

    for intervals in machine_intervals.values():
        model.add_no_overlap(intervals)

    tardies: list[cp_model.IntVar] = []
    for order in orders:
        if order.id not in last_end:
            continue
        tard = model.new_int_var(0, horizon, f"tard_{order.id}")
        model.add(tard >= last_end[order.id] - order.due_min)
        tardies.append(tard)

    # Lexicographic objective: first minimise total tardiness, then (as a
    # tie-breaker) finish every order as early as possible. Without the second
    # term the solver reshuffles freely among equal-tardiness optima, which
    # would make "what slips?" report spurious movements.
    big = len(orders) * horizon + 1
    completion_sum = sum(last_end.values())
    model.minimize(big * sum(tardies) + completion_sum)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_time_s
    solver.parameters.random_seed = DEFAULT_SEED
    # Single-threaded keeps results deterministic and avoids a worker-pool
    # deadlock seen on some macOS builds. Raise this in production for speed.
    solver.parameters.num_search_workers = 1
    solver.solve(model)

    scheduled: list[ScheduledOp] = []
    completion: dict[str, int] = {}
    for order in orders:
        for i, op in enumerate(order.operations):
            scheduled.append(
                ScheduledOp(
                    order_id=order.id,
                    op_index=i,
                    machine=op.machine,
                    start_min=int(solver.value(starts[(order.id, i)])),
                    end_min=int(solver.value(ends[(order.id, i)])),
                )
            )
        completion[order.id] = (
            int(solver.value(last_end[order.id])) if order.id in last_end else order.release_min
        )

    tardiness = {oid: max(0, completion[oid] - by_id[oid].due_min) for oid in completion}
    late = sorted(oid for oid, t in tardiness.items() if t > 0)
    makespan = max(completion.values()) if completion else 0
    return ScheduleResult(scheduled, completion, tardiness, late, makespan)


@dataclass(frozen=True, slots=True)
class OrderSlip:
    """How much an existing order's completion moves when a new one is accepted."""

    order_id: str
    baseline_completion: int
    new_completion: int
    slip_min: int


@dataclass(frozen=True, slots=True)
class WhatIfResult:
    """The data-backed answer to 'if I accept this order, what slips?'."""

    new_order_id: str
    new_order_completion: int
    new_order_tardiness: int
    slips: list[OrderSlip]
    total_tardiness_before: int
    total_tardiness_after: int


def what_if_accept(
    orders: list[Order], new_order: Order, *, max_time_s: float = 10.0
) -> WhatIfResult:
    """Quantify the impact of accepting *new_order* on the existing *orders*.

    PT: Optimiza com e sem a encomenda nova e reporta, por encomenda, quanto a
    sua saída desliza — transformando "conseguimos?" numa resposta com dados.
    EN: Optimises with and without the new order and reports, per order, how much
    its completion slips — turning "can we do it?" into a data-backed answer.
    """
    before = schedule_cpsat(orders, max_time_s=max_time_s)
    after = schedule_cpsat([*orders, new_order], max_time_s=max_time_s)

    slips: list[OrderSlip] = []
    for order in orders:
        base = before.completion[order.id]
        now = after.completion[order.id]
        if now != base:
            slips.append(
                OrderSlip(
                    order_id=order.id,
                    baseline_completion=base,
                    new_completion=now,
                    slip_min=now - base,
                )
            )
    slips.sort(key=lambda s: s.slip_min, reverse=True)

    return WhatIfResult(
        new_order_id=new_order.id,
        new_order_completion=after.completion[new_order.id],
        new_order_tardiness=after.tardiness[new_order.id],
        slips=slips,
        total_tardiness_before=sum(before.tardiness.values()),
        total_tardiness_after=sum(after.tardiness.values()),
    )
