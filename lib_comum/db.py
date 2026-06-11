"""TimescaleDB / Postgres async client helpers.

PT: Cliente assíncrono partilhado para a TimescaleDB. Inserções na hypertable
``telemetry``, batch writes, gestão de conexões.
EN: Shared async client for TimescaleDB. ``telemetry`` hypertable inserts,
batched writes, connection management.

The DSN is read from the ``DATABASE_URL`` env var by default::

    DATABASE_URL=postgresql://fabrica:change_me_local_only@localhost:5432/fabrica
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import dict_row


def default_dsn() -> str:
    """Return the connection DSN, deriving a sensible default from the env.

    PT: Devolve a DSN, derivando um valor por defeito a partir do ambiente.
    EN: Returns the connection DSN, falling back to the env-derived default.
    """
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        return explicit
    user = os.environ.get("POSTGRES_USER", "fabrica")
    password = os.environ.get("POSTGRES_PASSWORD", "change_me_local_only")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "fabrica")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@dataclass(frozen=True, slots=True)
class TelemetryRow:
    """One row in the ``telemetry`` hypertable.

    PT: Linha da hypertable ``telemetry``.
    EN: Single row of the ``telemetry`` hypertable.
    """

    ts: datetime
    machine: str
    metric: str
    value: float

    def as_tuple(self) -> tuple[datetime, str, str, float]:
        return (self.ts, self.machine, self.metric, self.value)


@asynccontextmanager
async def aconnect(
    dsn: str | None = None,
) -> AsyncIterator[psycopg.AsyncConnection]:
    """Async context manager around :class:`psycopg.AsyncConnection`.

    PT: Gestor de contexto assíncrono para uma conexão psycopg.
    EN: Async context manager wrapping a psycopg connection.
    """
    actual = dsn or default_dsn()
    async with await psycopg.AsyncConnection.connect(actual) as conn:
        yield conn


async def insert_telemetry_row(conn: psycopg.AsyncConnection, row: TelemetryRow) -> None:
    """Insert a single :class:`TelemetryRow`.

    PT: Insere uma única linha. Para volume use :func:`insert_telemetry_batch`.
    EN: Inserts a single row. Prefer :func:`insert_telemetry_batch` for volume.
    """
    await conn.execute(
        "INSERT INTO telemetry (ts, machine, metric, value) VALUES (%s, %s, %s, %s)",
        row.as_tuple(),
    )


async def insert_telemetry_batch(
    conn: psycopg.AsyncConnection, rows: Sequence[TelemetryRow]
) -> int:
    """Insert *rows* with ``executemany`` and return the row count.

    PT: Insere as linhas em batch. Devolve o número de linhas escritas.
    EN: Bulk-inserts the rows. Returns the count written.
    """
    if not rows:
        return 0
    async with conn.cursor() as cur:
        await cur.executemany(
            "INSERT INTO telemetry (ts, machine, metric, value) VALUES (%s, %s, %s, %s)",
            [r.as_tuple() for r in rows],
        )
    return len(rows)


async def fetch_recent_state(
    conn: psycopg.AsyncConnection,
    window: str = "5 minutes",
) -> list[dict[str, object]]:
    """Return current state per machine over the recent *window*.

    PT: Devolve o estado actual de cada máquina na janela indicada.
    EN: Returns the current state for each machine over the recent window.

    Mirrors the SQL the manuscript shows in Chapter 1.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT
              machine,
              CASE
                WHEN AVG(value) < 0.5 THEN 'parado'
                WHEN AVG(value) < 2.0 THEN 'em vazio'
                ELSE 'a produzir'
              END AS estado,
              AVG(value)::float AS corrente_media_a,
              COUNT(*) AS n_samples
            FROM telemetry
            WHERE metric = 'current_a'
              AND ts > NOW() - %s::interval
            GROUP BY machine
            ORDER BY machine
            """,
            (window,),
        )
        return await cur.fetchall()


async def count_rows(conn: psycopg.AsyncConnection, *, since: datetime | None = None) -> int:
    """Return the number of rows in ``telemetry``, optionally filtered.

    PT: Conta linhas em ``telemetry``, opcionalmente filtradas por timestamp.
    EN: Counts rows in ``telemetry``, optionally filtered by timestamp.
    """
    async with conn.cursor() as cur:
        if since is None:
            await cur.execute("SELECT COUNT(*) FROM telemetry")
        else:
            await cur.execute("SELECT COUNT(*) FROM telemetry WHERE ts >= %s", (since,))
        result = await cur.fetchone()
        return int(result[0]) if result else 0


async def truncate_telemetry(conn: psycopg.AsyncConnection) -> None:
    """Empty the ``telemetry`` hypertable. Useful for tests.

    PT: Esvazia a hypertable. Útil em testes.
    EN: Empties the hypertable. Useful in tests.
    """
    await conn.execute("TRUNCATE telemetry")


def telemetry_rows_from_payloads(
    payloads: Iterable[dict[str, object]],
    *,
    metric: str = "current_a",
    now: datetime | None = None,
) -> list[TelemetryRow]:
    """Convert MQTT JSON payloads into :class:`TelemetryRow` instances.

    PT: Converte payloads JSON de MQTT em linhas para inserção.
    EN: Converts MQTT JSON payloads into rows ready for insertion.

    Each payload is expected to carry at least ``machine`` and ``current_a``
    fields (matching what the ESP32 firmware publishes).
    """
    fallback = now or datetime.now().astimezone()
    out: list[TelemetryRow] = []
    for p in payloads:
        machine = str(p["machine"])
        current_raw = p["current_a"]
        if not isinstance(current_raw, int | float):
            continue
        value = float(current_raw)
        ts_raw = p.get("ts_iso")
        ts = datetime.fromisoformat(str(ts_raw)) if ts_raw else fallback
        out.append(TelemetryRow(ts=ts, machine=machine, metric=metric, value=value))
    return out
