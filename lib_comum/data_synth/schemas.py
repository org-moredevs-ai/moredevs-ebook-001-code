"""Shared schemas for synthetic factory data.

PT: Esquemas partilhados pelos geradores de dados sintéticos.
EN: Shared schemas used by all sector generators.

Three core tables are produced for every recipe:

- ``machine_states``: change-based log of machine operating state.
- ``sensor_readings``: time-series of environmental and electrical sensors.
- ``production_events``: per-unit production counters and rejects.

These map 1:1 onto TimescaleDB hypertables used by Recipe 1 onwards.
"""

from __future__ import annotations

from typing import Final, Literal

import pandas as pd

MachineState = Literal[
    "running",
    "idle",
    "stopped",
    "fault",
    "setup",
    "cleaning",
]

MACHINE_STATES: Final[tuple[str, ...]] = (
    "running",
    "idle",
    "stopped",
    "fault",
    "setup",
    "cleaning",
)

MACHINE_STATES_COLUMNS: Final[list[str]] = [
    "timestamp",
    "machine_id",
    "state",
    "state_reason",
    "duration_s",
]

MACHINE_STATES_DTYPES: Final[dict[str, str]] = {
    "machine_id": "string",
    "state": "category",
    "state_reason": "string",
    "duration_s": "int32",
}

SENSOR_READINGS_COLUMNS: Final[list[str]] = [
    "timestamp",
    "machine_id",
    "sensor",
    "value",
    "unit",
]

SENSOR_READINGS_DTYPES: Final[dict[str, str]] = {
    "machine_id": "string",
    "sensor": "category",
    "value": "float32",
    "unit": "category",
}

PRODUCTION_EVENTS_COLUMNS: Final[list[str]] = [
    "timestamp",
    "machine_id",
    "sku",
    "units_produced",
    "units_rejected",
]

PRODUCTION_EVENTS_DTYPES: Final[dict[str, str]] = {
    "machine_id": "string",
    "sku": "string",
    "units_produced": "int32",
    "units_rejected": "int32",
}


def apply_dtypes(df: pd.DataFrame, dtypes: dict[str, str]) -> pd.DataFrame:
    """Apply canonical dtypes to a DataFrame in place and return it.

    PT: Aplica os dtypes canónicos a um DataFrame.
    EN: Applies canonical dtypes to a DataFrame.
    """
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for col, dt in dtypes.items():
        if col in df.columns:
            df[col] = df[col].astype(dt)
    return df
