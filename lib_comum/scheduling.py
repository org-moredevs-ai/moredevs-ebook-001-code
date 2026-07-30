"""Recipe 5 Tier 1 — job-shop scheduling with a dispatching rule.

PT: Modela a fábrica como encomendas que passam por máquinas, em sequências e
tempos conhecidos, e calcula um plano realista com uma **regra de despacho**
(EDD — a data prometida mais próxima primeiro, por defeito). Sempre que uma
máquina fica livre, ataca a operação da encomenda mais urgente que esteja
pronta. Devolve as datas de saída previstas, o atraso de cada encomenda, e a
lista das que vão falhar o prazo.

EN: Models the factory as orders flowing through machines, in known sequences
and durations, and computes a realistic plan with a **dispatching rule** (EDD —
earliest due date by default). Whenever a machine frees up it takes the most
urgent ready operation. Returns predicted ship times, per-order tardiness and
the list of late orders.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Operation:
    """One step of an order: a machine and a duration (minutes)."""

    machine: str
    duration_min: int


@dataclass(frozen=True, slots=True)
class Order:
    """An order: an ordered list of operations, a due time and a release time."""

    id: str
    operations: list[Operation]
    due_min: int
    release_min: int = 0

    @property
    def total_work_min(self) -> int:
        return sum(op.duration_min for op in self.operations)


@dataclass(frozen=True, slots=True)
class ScheduledOp:
    """A placed operation on the timeline."""

    order_id: str
    op_index: int
    machine: str
    start_min: int
    end_min: int


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    """Outcome of a scheduling run."""

    scheduled: list[ScheduledOp]
    completion: dict[str, int]
    tardiness: dict[str, int]
    late_orders: list[str]
    makespan: int


_RULES: dict[str, Callable[[Order], int]] = {
    "EDD": lambda o: o.due_min,  # earliest due date
    "SPT": lambda o: o.total_work_min,  # shortest processing time
    "FIFO": lambda o: o.release_min,  # first in, first out
}


def total_tardiness(result: ScheduleResult) -> int:
    """Sum of tardiness across all orders (the headline KPI)."""
    return sum(result.tardiness.values())


def _result_from(
    orders: list[Order], scheduled: list[ScheduledOp], order_ready: dict[str, int]
) -> ScheduleResult:
    by_id = {o.id: o for o in orders}
    completion = {o.id: order_ready[o.id] for o in orders}
    tardiness = {oid: max(0, completion[oid] - by_id[oid].due_min) for oid in completion}
    late = sorted(oid for oid, t in tardiness.items() if t > 0)
    makespan = max(completion.values()) if completion else 0
    return ScheduleResult(
        scheduled=scheduled,
        completion=completion,
        tardiness=tardiness,
        late_orders=late,
        makespan=makespan,
    )


def schedule_dispatch(orders: list[Order], *, rule: str = "EDD") -> ScheduleResult:
    """List-scheduling with a dispatching *rule* (event-driven simulation).

    PT: A cada instante, cada máquina livre escolhe a operação pronta da
    encomenda mais urgente (segundo a regra). Avança o tempo até ao próximo
    evento quando ninguém pode progredir.
    EN: At each instant, every free machine picks the ready operation of the
    most urgent order (per the rule). Advances time to the next event when no
    one can progress.
    """
    key = _RULES.get(rule, _RULES["EDD"])
    by_id = {o.id: o for o in orders}
    next_idx = {o.id: 0 for o in orders}
    order_ready = {o.id: o.release_min for o in orders}
    machines = sorted({op.machine for o in orders for op in o.operations})
    machine_free = {m: 0 for m in machines}

    scheduled: list[ScheduledOp] = []
    remaining = sum(len(o.operations) for o in orders)
    time = min((o.release_min for o in orders), default=0)

    while remaining > 0:
        progressed = False
        for m in machines:
            if machine_free[m] > time:
                continue
            ready = [
                o
                for o in orders
                if next_idx[o.id] < len(o.operations)
                and o.operations[next_idx[o.id]].machine == m
                and order_ready[o.id] <= time
            ]
            if not ready:
                continue
            pick = min(ready, key=lambda o: (key(o), o.id))
            idx = next_idx[pick.id]
            op = by_id[pick.id].operations[idx]
            end = time + op.duration_min
            scheduled.append(ScheduledOp(pick.id, idx, m, time, end))
            machine_free[m] = end
            order_ready[pick.id] = end
            next_idx[pick.id] += 1
            remaining -= 1
            progressed = True
        if not progressed:
            future = [machine_free[m] for m in machines if machine_free[m] > time]
            future += [
                order_ready[o.id]
                for o in orders
                if next_idx[o.id] < len(o.operations) and order_ready[o.id] > time
            ]
            if not future:
                break
            time = min(future)

    return _result_from(orders, scheduled, order_ready)


def demo_orders(seed: int = 20260517) -> list[Order]:
    """Return a deterministic set of demo orders (auto-parts style).

    PT: 7 encomendas que seguem o **fluxo real da fábrica** — corte, CNC,
    soldadura, acabamento, por esta ordem (uma peça pode saltar uma etapa, mas
    nunca anda para trás: não se acaba antes de cortar). Os prazos (factor
    1.5-2.1x do trabalho) põem a fábrica sob pressão realista: a regra EDD deixa
    **2 encomendas claramente atrasadas** (o risco que o Nível 1 torna visível),
    o optimizador CP-SAT corta o atraso de 242 para 41 min, e ainda sobra folga
    para aceitar uma encomenda urgente sem atrasar mais ninguém.
    EN: 7 orders following the **real factory flow** — cutting, CNC, welding,
    finishing, in that order (a part may skip a stage but never goes backwards).
    Due dates (1.5-2.1x the work) put the shop under realistic pressure: EDD
    leaves **two clearly late orders**, CP-SAT cuts the tardiness from 242 to 41
    min, and there is still slack to accept an urgent order with no extra
    lateness.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    # Natural process flow: parts move forward through these stages.
    flow = ["corte", "cnc", "soldadura", "acabamento"]
    orders: list[Order] = []
    for i in range(7):
        n_ops = int(rng.integers(2, 5))
        # Pick a subset of stages and keep them in flow order — a physically valid
        # route (never "finish before cut"), unlike a random permutation.
        stage_idx = sorted(rng.choice(len(flow), size=n_ops, replace=False))
        operations = [
            Operation(machine=flow[j], duration_min=int(rng.integers(30, 120))) for j in stage_idx
        ]
        work = sum(op.duration_min for op in operations)
        due = int(work * rng.uniform(1.5, 2.1))
        orders.append(Order(id=f"OF-{4450 + i}", operations=operations, due_min=due))
    return orders
