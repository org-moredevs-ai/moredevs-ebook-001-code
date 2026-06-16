"""Synthetic dataset — moulds SME (Marinha Grande cluster).

PT: Caso de campo da Receita 2 — fábrica de moldes na Marinha Grande,
6 máquinas (1 prensa de 250 t, 3 fresadoras CNC, 2 electroerosões). A
prensa-1 desenvolve um defeito de chumaceira nos últimos 12 dias do
período, com o RMS de vibração a subir gradualmente e a frequência
dominante a deslocar-se para a banda BPFO (fault frequency da pista
externa). O Capítulo 2 do livro descreve este caso de campo
(detectado 11 dias antes da falha catastrófica, ~€18.000 evitados).

EN: Recipe 2 field case — moulds plant in Marinha Grande, Portugal,
6 machines (1x 250-tonne press, 3x CNC mills, 2x EDMs). Press-1
develops a bearing fault over the last 12 days of the period: vibration
RMS climbs gradually and the dominant FFT frequency shifts toward the
outer-race fault band (BPFO). The signal is discoverable from the FFT
in Chapter 2 Tier 1 and from an Isolation Forest in Tier 2.

Outputs four tables:

- ``machine_states``: change-based state log (running, idle, ...).
- ``sensor_readings``: ambient temperature, motor current.
- ``vibration_metrics``: per-minute 3-axis RMS / peak / kurtosis /
  dominant frequency, the core signal for Recipe 2.
- ``production_events``: hourly part counts and rejects.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, TypedDict

import numpy as np
import pandas as pd

from lib_comum.data_synth.base import (
    DEFAULT_SEED,
    make_rng,
    time_window,
    write_table,
)
from lib_comum.data_synth.schemas import (
    MACHINE_STATES_COLUMNS,
    MACHINE_STATES_DTYPES,
    PRODUCTION_EVENTS_COLUMNS,
    PRODUCTION_EVENTS_DTYPES,
    SENSOR_READINGS_COLUMNS,
    SENSOR_READINGS_DTYPES,
    VIBRATION_METRICS_COLUMNS,
    VIBRATION_METRICS_DTYPES,
    apply_dtypes,
)

SECTOR: Final[str] = "moldes"


class MachineConfig(TypedDict):
    family: str
    rpm: int
    healthy_rms_g: float
    healthy_dom_hz: float
    fault_bearing: bool


# Marinha Grande mould-making roster. RPM and base vibration profile per family.
# Bearing fault is seeded only on `prensa-250t.maquina-1`.
MACHINES: Final[dict[str, MachineConfig]] = {
    "prensa-250t.maquina-1": {
        "family": "press",
        "rpm": 1500,
        "healthy_rms_g": 0.45,
        "healthy_dom_hz": 25.0,
        "fault_bearing": True,
    },
    "fresadora-cnc.maquina-1": {
        "family": "cnc_mill",
        "rpm": 9000,
        "healthy_rms_g": 0.25,
        "healthy_dom_hz": 150.0,
        "fault_bearing": False,
    },
    "fresadora-cnc.maquina-2": {
        "family": "cnc_mill",
        "rpm": 9000,
        "healthy_rms_g": 0.22,
        "healthy_dom_hz": 150.0,
        "fault_bearing": False,
    },
    "fresadora-cnc.maquina-3": {
        "family": "cnc_mill",
        "rpm": 12000,
        "healthy_rms_g": 0.28,
        "healthy_dom_hz": 200.0,
        "fault_bearing": False,
    },
    "edm.maquina-1": {
        "family": "edm",
        "rpm": 0,  # EDM has no rotating spindle; sensor reads pump vibration
        "healthy_rms_g": 0.15,
        "healthy_dom_hz": 60.0,
        "fault_bearing": False,
    },
    "edm.maquina-2": {
        "family": "edm",
        "rpm": 0,
        "healthy_rms_g": 0.18,
        "healthy_dom_hz": 60.0,
        "fault_bearing": False,
    },
}

MACHINE_IDS: Final[list[str]] = list(MACHINES.keys())

# State weights per machine family. EDMs idle more between cycles; presses
# spend more time running once set up.
STATE_WEIGHTS_BY_FAMILY: Final[dict[str, dict[str, float]]] = {
    "press": {
        "running": 0.72,
        "idle": 0.10,
        "setup": 0.10,
        "stopped": 0.06,
        "fault": 0.02,
    },
    "cnc_mill": {
        "running": 0.65,
        "idle": 0.12,
        "setup": 0.16,
        "stopped": 0.05,
        "fault": 0.02,
    },
    "edm": {
        "running": 0.55,
        "idle": 0.30,
        "setup": 0.10,
        "stopped": 0.04,
        "fault": 0.01,
    },
}

SHIFT_HOURS: Final[dict[str, tuple[int, int]]] = {
    "manha": (6, 14),
    "tarde": (14, 22),
    "noite": (22, 30),  # wraps midnight
}

AXES: Final[tuple[str, str, str]] = ("x", "y", "z")

# Bearing fault parameters.
#
# The case study runs over the last `WEAR_WINDOW_DAYS` days of the period.
# RMS grows logistically from baseline to roughly 3x at the fault point.
# The dominant frequency drifts from 25 Hz (1x rotation of the press) to the
# BPFO band (~83 Hz for a typical large press bearing), reproducing what a
# reader sees in the FFT panel of Chapter 2.
WEAR_WINDOW_DAYS: Final[int] = 12
BPFO_HZ: Final[float] = 83.0  # outer-race fault frequency (typical large press)
FAULT_RMS_GAIN: Final[float] = 3.0
FAULT_KURTOSIS_PEAK: Final[float] = 12.0

VIBRATION_METRICS_PERIOD_MIN: Final[int] = 1
"""Per-minute roll-ups — matches the cadence the Chapter 2 dashboards consume."""


# ---------------------------------------------------------------------------
# Wear curve
# ---------------------------------------------------------------------------


def _wear_progress(sim_ts: datetime, end: datetime) -> float:
    """Wear progress in [0, 1] for *sim_ts* given the period *end*.

    PT: Progresso do desgaste no intervalo [0, 1]. 0 = saudável,
    1 = falha catastrófica.
    EN: Wear progress on [0, 1]. 0 = healthy, 1 = catastrophic failure.

    Returns 0 outside the WEAR_WINDOW_DAYS window leading up to *end*.
    """
    window_start = end - timedelta(days=WEAR_WINDOW_DAYS)
    if sim_ts <= window_start:
        return 0.0
    if sim_ts >= end:
        return 1.0
    delta_s = (sim_ts - window_start).total_seconds()
    window_s = (end - window_start).total_seconds()
    return delta_s / window_s


def _logistic(x: float, k: float = 6.0) -> float:
    """Logistic curve giving a smooth S-shape on [0, 1]."""
    return float(1.0 / (1.0 + np.exp(-k * (x - 0.5))))


# ---------------------------------------------------------------------------
# Machine state events
# ---------------------------------------------------------------------------


def _state_duration_s(state: str, rng: np.random.Generator) -> int:
    if state == "running":
        return int(rng.integers(900, 3600))  # 15-60 min
    if state == "idle":
        return int(rng.integers(120, 900))  # 2-15 min
    if state == "stopped":
        return int(rng.integers(180, 1200))  # 3-20 min
    if state == "fault":
        return int(rng.integers(600, 2400))  # 10-40 min
    if state == "setup":
        return int(rng.integers(300, 1800))  # 5-30 min
    return 120


def _sample_state(weights: dict[str, float], rng: np.random.Generator) -> str:
    states = list(weights.keys())
    probs = np.array(list(weights.values()))
    probs = probs / probs.sum()
    idx = rng.choice(len(states), p=probs)
    return states[int(idx)]


def _shift_window(day: datetime, shift: str) -> tuple[datetime, datetime]:
    start_h, end_h = SHIFT_HOURS[shift]
    s = day.replace(hour=start_h % 24, minute=0, second=0, microsecond=0)
    if shift == "noite":
        e = s + timedelta(hours=8)
    else:
        e = day.replace(hour=end_h, minute=0, second=0, microsecond=0)
    return s, e


def _states_for_machine(
    machine_id: str,
    days: int,
    period_start: datetime,
    period_end: datetime,
    rng: np.random.Generator,
) -> list[dict[str, object]]:
    family = MACHINES[machine_id]["family"]
    weights = STATE_WEIGHTS_BY_FAMILY[family]
    events: list[dict[str, object]] = []
    for d in range(days):
        day = period_start + timedelta(days=d)
        for shift in SHIFT_HOURS:
            s, e = _shift_window(day, shift)
            t = s
            while t < e:
                state = _sample_state(weights, rng)
                duration = _state_duration_s(state, rng)
                if t + timedelta(seconds=duration) > e:
                    duration = int((e - t).total_seconds())
                    if duration <= 0:
                        break
                events.append(
                    {
                        "timestamp": t,
                        "machine_id": machine_id,
                        "state": state,
                        "state_reason": None,
                        "duration_s": duration,
                    }
                )
                t += timedelta(seconds=duration)

    # On the fault-seeded machine, force a final fault event at period_end.
    if MACHINES[machine_id]["fault_bearing"]:
        events.append(
            {
                "timestamp": period_end - timedelta(minutes=5),
                "machine_id": machine_id,
                "state": "fault",
                "state_reason": "bearing_failure",
                "duration_s": 300,
            }
        )
    return events


# ---------------------------------------------------------------------------
# Ambient + motor-current sensor readings
# ---------------------------------------------------------------------------


def _sensor_readings(
    machine_id: str,
    period_start: datetime,
    period_end: datetime,
    states_df: pd.DataFrame,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Per-5-minute ambient temperature and motor current per machine."""
    rows: list[dict[str, object]] = []
    step = timedelta(minutes=5)
    t = period_start
    while t < period_end:
        ambient = 19.0 + float(rng.normal(0, 1.5))
        rows.append(
            {
                "timestamp": t,
                "machine_id": machine_id,
                "sensor": "ambient_temp_c",
                "value": round(ambient, 2),
                "unit": "C",
            }
        )
        # Motor current: depends on the current state.
        state = _state_at(states_df, machine_id, t)
        family = MACHINES[machine_id]["family"]
        current = _current_for(family, state, rng)
        rows.append(
            {
                "timestamp": t,
                "machine_id": machine_id,
                "sensor": "motor_current_a",
                "value": round(current, 2),
                "unit": "A",
            }
        )
        t += step
    df = pd.DataFrame(rows, columns=SENSOR_READINGS_COLUMNS)
    return apply_dtypes(df, SENSOR_READINGS_DTYPES)


def _current_for(family: str, state: str, rng: np.random.Generator) -> float:
    if state != "running":
        return max(0.0, float(rng.normal(0.5, 0.2)))
    base = {"press": 18.0, "cnc_mill": 9.0, "edm": 6.5}[family]
    return max(0.0, base + float(rng.normal(0, base * 0.05)))


def _state_at(df: pd.DataFrame, machine_id: str, ts: datetime) -> str:
    """Linear lookup of the state in force at *ts* — small datasets only."""
    subset = df[df["machine_id"] == machine_id]
    if subset.empty:
        return "stopped"
    pos_array = subset["timestamp"].searchsorted(pd.Timestamp(ts), side="right")
    pos = int(pos_array) - 1
    if pos < 0:
        return "stopped"
    return str(subset.iloc[pos]["state"])


# ---------------------------------------------------------------------------
# Vibration metrics
# ---------------------------------------------------------------------------


def _vibration_metrics_for_machine(
    machine_id: str,
    period_start: datetime,
    period_end: datetime,
    states_df: pd.DataFrame,
    rng: np.random.Generator,
) -> list[dict[str, object]]:
    cfg = MACHINES[machine_id]
    healthy_rms = cfg["healthy_rms_g"]
    healthy_dom = cfg["healthy_dom_hz"]
    has_fault = cfg["fault_bearing"]

    rows: list[dict[str, object]] = []
    step = timedelta(minutes=VIBRATION_METRICS_PERIOD_MIN)
    t = period_start
    while t < period_end:
        state = _state_at(states_df, machine_id, t)
        running = state == "running"
        wear = _logistic(_wear_progress(t, period_end)) if has_fault else 0.0
        for axis in AXES:
            # Slight per-axis offset so x/y/z aren't identical.
            axis_factor = {"x": 1.0, "y": 0.85, "z": 0.6}[axis]
            # When the machine is idle / stopped, only background noise.
            base_rms = healthy_rms * axis_factor if running else 0.04 * axis_factor
            rms = base_rms * (1.0 + (FAULT_RMS_GAIN - 1.0) * wear)
            rms += float(rng.normal(0, base_rms * 0.08))
            rms = max(0.0, rms)

            peak = rms * (1.6 + 1.4 * wear) + float(rng.normal(0, 0.05))
            peak = max(rms, peak)

            kurtosis_base = 3.0  # Gaussian baseline
            kurtosis = kurtosis_base + (FAULT_KURTOSIS_PEAK - kurtosis_base) * wear
            kurtosis += float(rng.normal(0, 0.3))

            if running:
                # Healthy: dominant freq stays at 1x rotation.
                # Faulty: drifts to BPFO band.
                dom = healthy_dom + (BPFO_HZ - healthy_dom) * wear
                dom += float(rng.normal(0, 1.0))
            else:
                dom = 0.0

            rows.append(
                {
                    "timestamp": t,
                    "machine_id": machine_id,
                    "axis": axis,
                    "rms_g": round(rms, 4),
                    "peak_g": round(peak, 4),
                    "kurtosis": round(kurtosis, 3),
                    "dominant_freq_hz": round(dom, 2),
                }
            )
        t += step
    return rows


# ---------------------------------------------------------------------------
# Production events
# ---------------------------------------------------------------------------


SKUS_BY_FAMILY: Final[dict[str, list[str]]] = {
    "press": ["MOLD-FRONT-A", "MOLD-FRONT-B", "MOLD-INSERT-S"],
    "cnc_mill": ["MOLD-CAVITY-X", "MOLD-CORE-Y", "INSERT-MICRO-7"],
    "edm": ["EDM-FINISH-1", "EDM-DEEP-2"],
}


def _production_events(states_df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    if states_df.empty:
        return pd.DataFrame(columns=PRODUCTION_EVENTS_COLUMNS)

    running = states_df[states_df["state"] == "running"].copy()
    running["timestamp"] = pd.to_datetime(running["timestamp"], utc=True)
    running["hour"] = running["timestamp"].dt.floor("h")
    grouped = running.groupby(["hour", "machine_id"], observed=True)["duration_s"].sum()

    rows: list[dict[str, object]] = []
    for (hour, machine_id), running_seconds in grouped.items():
        if running_seconds <= 0:
            continue
        family = MACHINES[machine_id]["family"]
        # Press: ~12 parts/hour while running. CNC: ~1/hour (long cycles). EDM: ~0.5/hour.
        rate_per_hour = {"press": 12.0, "cnc_mill": 1.2, "edm": 0.5}[family]
        produced = max(
            1, int(running_seconds / 3600.0 * float(rng.uniform(0.85, 1.15)) * rate_per_hour)
        )
        rejection_rate = float(rng.uniform(0.01, 0.03))
        rejected = int(produced * rejection_rate)
        sku = SKUS_BY_FAMILY[family][int(rng.integers(0, len(SKUS_BY_FAMILY[family])))]
        rows.append(
            {
                "timestamp": hour,
                "machine_id": machine_id,
                "sku": sku,
                "units_produced": produced,
                "units_rejected": rejected,
            }
        )
    df = pd.DataFrame(rows, columns=PRODUCTION_EVENTS_COLUMNS)
    return apply_dtypes(df, PRODUCTION_EVENTS_DTYPES)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate(days: int = 30, seed: int = DEFAULT_SEED) -> dict[str, pd.DataFrame]:
    """Generate the moulds-sector dataset.

    PT: Gera o dataset do sector de moldes.
    EN: Generates the moulds sector dataset.

    Args:
        days: number of days to synthesise. Defaults to 30.
        seed: RNG seed for reproducibility. Defaults to
            :data:`~lib_comum.data_synth.base.DEFAULT_SEED`.

    Returns:
        Dict with four DataFrames: ``machine_states``, ``sensor_readings``,
        ``vibration_metrics``, ``production_events``.
    """
    rng = make_rng(seed)
    period_start, period_end = time_window(days)

    state_rows: list[dict[str, object]] = []
    for machine_id in MACHINES:
        state_rows.extend(_states_for_machine(machine_id, days, period_start, period_end, rng))
    states_df = pd.DataFrame(state_rows, columns=MACHINE_STATES_COLUMNS)
    states_df["timestamp"] = pd.to_datetime(states_df["timestamp"], utc=True)
    states_df = states_df.sort_values(["timestamp", "machine_id"]).reset_index(drop=True)
    states_df = apply_dtypes(states_df, MACHINE_STATES_DTYPES)

    sensor_frames: list[pd.DataFrame] = []
    for machine_id in MACHINES:
        sensor_frames.append(_sensor_readings(machine_id, period_start, period_end, states_df, rng))
    sensors_df = pd.concat(sensor_frames, ignore_index=True).sort_values(
        ["timestamp", "machine_id", "sensor"]
    )
    sensors_df = apply_dtypes(sensors_df, SENSOR_READINGS_DTYPES)

    vibration_rows: list[dict[str, object]] = []
    for machine_id in MACHINES:
        vibration_rows.extend(
            _vibration_metrics_for_machine(machine_id, period_start, period_end, states_df, rng)
        )
    vibration_df = pd.DataFrame(vibration_rows, columns=VIBRATION_METRICS_COLUMNS)
    vibration_df["timestamp"] = pd.to_datetime(vibration_df["timestamp"], utc=True)
    vibration_df = vibration_df.sort_values(["timestamp", "machine_id", "axis"]).reset_index(
        drop=True
    )
    vibration_df = apply_dtypes(vibration_df, VIBRATION_METRICS_DTYPES)

    production_df = _production_events(states_df, rng)

    return {
        "machine_states": states_df,
        "sensor_readings": sensors_df,
        "vibration_metrics": vibration_df,
        "production_events": production_df,
    }


def write(
    out_dir: Path,
    *,
    days: int = 30,
    seed: int = DEFAULT_SEED,
    formats: tuple[str, ...] = ("parquet", "csv.gz"),
) -> dict[str, list[Path]]:
    """Generate and write the four tables to *out_dir*.

    PT: Gera e persiste as quatro tabelas.
    EN: Generates and writes the four tables to *out_dir*.
    """
    tables = generate(days=days, seed=seed)
    written: dict[str, list[Path]] = {}
    for name, df in tables.items():
        written[name] = write_table(df, out_dir, name, formats=formats)
    return written


def case_summary(tables: dict[str, pd.DataFrame]) -> str:
    """Human-readable summary of the case study signal embedded in *tables*."""
    vib = tables["vibration_metrics"]
    press = vib[vib["machine_id"] == "prensa-250t.maquina-1"].copy()
    press = press.sort_values("timestamp")
    if press.empty:
        return "moldes: no vibration data generated"

    start_rms = float(press["rms_g"].head(60).mean())
    end_rms = float(press["rms_g"].tail(60).mean())
    gain = end_rms / start_rms if start_rms else float("inf")

    n_machines = vib["machine_id"].nunique()
    period_start = vib["timestamp"].min()
    period_end = vib["timestamp"].max()
    return (
        f"moldes: {n_machines} machines, "
        f"{period_start:%Y-%m-%d} -> {period_end:%Y-%m-%d}, "
        f"press-1 RMS x-axis grew {start_rms:.3f}g -> {end_rms:.3f}g ({gain:.1f}x)"
    )


if __name__ == "__main__":  # pragma: no cover
    out = Path("receita-2-maquina-avisa/data-exemplo/moldes")
    paths = write(out)
    for name, files in paths.items():
        print(f"{name}: {[str(p) for p in files]}")
