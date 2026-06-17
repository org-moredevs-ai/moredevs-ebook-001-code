"""Recipe 1 Tier 2 — alert rules.

PT: Avalia regras de alerta sobre os dados que o colector Modbus persiste na
TimescaleDB e despacha notificações multi-canal via :class:`AlertSender`
(``lib_comum.alerting``). Duas regras, exactamente as que o Capítulo 1 descreve:

  1. Máquina parada há mais de ``idle_minutes`` em horário produtivo
     (ainda online, mas sem reportar estado "a produzir").
  2. Disponibilidade acumulada das últimas 24h abaixo do alvo
     (lê a view ``machine_availability_last_24h`` definida em
     ``lib_comum/sql/init/03_oee.sql``).

EN: Evaluates alert rules over the data the Modbus collector persists to
TimescaleDB and dispatches multi-channel notifications via :class:`AlertSender`
(``lib_comum.alerting``). Two rules, exactly the ones Chapter 1 describes:

  1. A machine idle for more than ``idle_minutes`` during productive hours
     (still online, but no longer reporting a "running" state).
  2. Rolling 24h availability below target (reads the
     ``machine_availability_last_24h`` view from
     ``lib_comum/sql/init/03_oee.sql``).

Run with::

    uv run python receita-1-olho-da-fabrica/nivel-2-pro/alerting/rules.py --once
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys

import psycopg
from psycopg.rows import dict_row

from lib_comum.alerting import AlertSender
from lib_comum.db import aconnect

LOG = logging.getLogger("alerting.rules")

# A machine is "online but stopped" when it is still reporting state samples
# (so the collector can reach it) yet none of those recent samples is the
# running code (state = 1). These defaults mirror the manuscript.
DEFAULT_IDLE_MINUTES = 10
DEFAULT_ONLINE_WINDOW_MINUTES = 20
DEFAULT_AVAILABILITY_TARGET = 0.60

RUNNING_STATE_VALUE = 1.0
"""State code emitted by the Modbus emulator for a running machine."""


async def stopped_machines(
    conn: psycopg.AsyncConnection,
    *,
    idle_minutes: int = DEFAULT_IDLE_MINUTES,
    online_window_minutes: int = DEFAULT_ONLINE_WINDOW_MINUTES,
) -> list[dict[str, object]]:
    """Return machines that are online but have not run for *idle_minutes*.

    PT: Devolve máquinas online cuja última leitura "a produzir" é mais
    antiga do que ``idle_minutes`` — o sinal de paragem não planeada.
    EN: Returns online machines whose last "running" sample is older than
    ``idle_minutes`` — the unplanned-stop signal.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            WITH last_seen AS (
                SELECT machine, MAX(ts) AS last_seen_ts
                FROM telemetry
                WHERE metric = 'state'
                  AND ts > NOW() - make_interval(mins => %(window)s)
                GROUP BY machine
            ),
            last_running AS (
                SELECT machine, MAX(ts) AS last_running_ts
                FROM telemetry
                WHERE metric = 'state'
                  AND value = %(running)s
                  AND ts > NOW() - make_interval(mins => %(window)s)
                GROUP BY machine
            )
            SELECT
                s.machine,
                s.last_seen_ts,
                r.last_running_ts
            FROM last_seen s
            LEFT JOIN last_running r USING (machine)
            WHERE r.last_running_ts IS NULL
               OR r.last_running_ts < NOW() - make_interval(mins => %(idle)s)
            ORDER BY s.machine
            """,
            {
                "window": online_window_minutes,
                "idle": idle_minutes,
                "running": RUNNING_STATE_VALUE,
            },
        )
        return await cur.fetchall()


async def low_availability_machines(
    conn: psycopg.AsyncConnection,
    *,
    target: float = DEFAULT_AVAILABILITY_TARGET,
) -> list[dict[str, object]]:
    """Return machines whose rolling 24h availability is below *target*.

    PT: Lê a view ``machine_availability_last_24h`` e devolve as máquinas
    cuja disponibilidade está abaixo do alvo (componente de OEE).
    EN: Reads the ``machine_availability_last_24h`` view and returns the
    machines whose availability is below target (the OEE component).
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT machine, availability_24h
            FROM machine_availability_last_24h
            WHERE availability_24h < %(target)s
            ORDER BY availability_24h
            """,
            {"target": target},
        )
        return await cur.fetchall()


async def evaluate_rules(
    conn: psycopg.AsyncConnection,
    sender: AlertSender,
    *,
    idle_minutes: int = DEFAULT_IDLE_MINUTES,
    availability_target: float = DEFAULT_AVAILABILITY_TARGET,
) -> int:
    """Evaluate every rule once and dispatch alerts. Returns the alert count.

    PT: Avalia as regras uma vez e despacha os alertas. Devolve quantos.
    EN: Evaluates each rule once and dispatches alerts. Returns the count.
    """
    sent = 0

    for row in await stopped_machines(conn, idle_minutes=idle_minutes):
        machine = row["machine"]
        last_running = row["last_running_ts"]
        when = "nunca no período" if last_running is None else str(last_running)
        sender.send(
            title=f"Máquina parada: {machine}",
            body=f"Sem estado 'a produzir' há mais de {idle_minutes} min "
            f"(última produção: {when}).",
            severity="warning",
        )
        sent += 1

    for row in await low_availability_machines(conn, target=availability_target):
        machine = row["machine"]
        availability = float(row["availability_24h"])  # type: ignore[arg-type]
        sender.send(
            title=f"Disponibilidade baixa: {machine}",
            body=f"Disponibilidade 24h em {availability:.0%}, "
            f"abaixo do alvo de {availability_target:.0%}.",
            severity="critical",
        )
        sent += 1

    return sent


async def run(
    *,
    dsn: str | None = None,
    interval_s: float = 60.0,
    idle_minutes: int = DEFAULT_IDLE_MINUTES,
    availability_target: float = DEFAULT_AVAILABILITY_TARGET,
    once: bool = False,
    stop_after_seconds: float | None = None,
) -> int:
    """Loop that re-evaluates the rules every *interval_s* seconds.

    PT: Loop que reavalia as regras a cada ``interval_s`` segundos.
    EN: Loop that re-evaluates the rules every ``interval_s`` seconds.

    Returns the total number of alerts dispatched.
    """
    sender = AlertSender.from_env()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig_name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(getattr(signal, sig_name), stop_event.set)
    if stop_after_seconds is not None:
        loop.call_later(stop_after_seconds, stop_event.set)

    total = 0
    async with aconnect(dsn) as conn:
        while not stop_event.is_set():
            total += await evaluate_rules(
                conn,
                sender,
                idle_minutes=idle_minutes,
                availability_target=availability_target,
            )
            if once:
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
    return total


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=None, help="Postgres DSN (defaults to env).")
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between passes.")
    parser.add_argument("--idle-minutes", type=int, default=DEFAULT_IDLE_MINUTES)
    parser.add_argument("--availability-target", type=float, default=DEFAULT_AVAILABILITY_TARGET)
    parser.add_argument("--once", action="store_true", help="Evaluate once and exit.")
    parser.add_argument("--max-runtime-seconds", type=float, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    total = asyncio.run(
        run(
            dsn=args.dsn,
            interval_s=args.interval,
            idle_minutes=args.idle_minutes,
            availability_target=args.availability_target,
            once=args.once,
            stop_after_seconds=args.max_runtime_seconds,
        )
    )
    print(f"Alert rules stopped — {total} alerts dispatched.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
