"""Synthetic dataset — food processing SME.

PT: Caso de campo da Receita 1 — fábrica de pratos preparados no Ribatejo,
5 linhas, ~20 máquinas. A linha 3 (embalamento + refrigeração) sofre
paragens automáticas por protecção térmica quando a temperatura ambiente
sobe acima dos 27 °C nas tardes de verão. O dataset reproduz o sinal
que permite ao leitor descobrir a correlação no Capítulo 1.

EN: Recipe 1 field case — prepared meals factory in Ribatejo, Portugal,
5 lines, ~20 machines. Line 3 (packing + cold chain) trips on thermal
protection when ambient temperature on the line exceeds 27 °C during
summer afternoons. The dataset reproduces the signal that lets the
reader discover the correlation in Chapter 1.

Outputs three tables — :data:`MACHINE_STATES_COLUMNS`,
:data:`SENSOR_READINGS_COLUMNS`, :data:`PRODUCTION_EVENTS_COLUMNS` — under
``receita-1-olho-da-fabrica/data-exemplo/alimentar/``.
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
    apply_dtypes,
)

SECTOR: Final[str] = "alimentar"


class LineConfig(TypedDict):
    machines: int
    function: str
    thermal_sensitive: bool


LINES: Final[dict[str, LineConfig]] = {
    "linha-1": {"machines": 4, "function": "preparacao", "thermal_sensitive": False},
    "linha-2": {"machines": 4, "function": "corte", "thermal_sensitive": False},
    "linha-3": {"machines": 4, "function": "embalamento", "thermal_sensitive": True},
    "linha-4": {"machines": 4, "function": "paletizacao", "thermal_sensitive": False},
    "linha-5": {"machines": 4, "function": "limpeza", "thermal_sensitive": False},
}

SHIFT_HOURS: Final[dict[str, tuple[int, int]]] = {
    "manha": (6, 14),
    "tarde": (14, 22),
    "noite": (22, 30),  # wraps midnight
}

# Probability mass for state transitions during a normal operating shift.
STATE_WEIGHTS: Final[dict[str, float]] = {
    "running": 0.815,
    "idle": 0.08,
    "setup": 0.05,
    "cleaning": 0.04,
    "stopped": 0.02,
    "fault": 0.005,
}

THERMAL_THRESHOLD_C: Final[float] = 27.0
"""Ambient temperature above which line-3 protection kicks in."""

THERMAL_EXTRA_STOPS_PER_TARDE_HOT_DAY: Final[tuple[int, int]] = (7, 10)
"""Range of thermal-protection stoppages on a hot line-3 summer afternoon."""

AMBIENT_MICRO_OFFSET_C: Final[dict[str, float]] = {
    "linha-1": -0.6,
    "linha-2": 0.4,
    "linha-4": 0.1,
    "linha-5": -0.3,
}
"""Tiny per-line microclimate offsets so the non-thermal lines render as distinct
traces (instead of one overlapping line) on the dashboard. All stay well below 27 °C."""


# ---------------------------------------------------------------------------
# Machine roster
# ---------------------------------------------------------------------------


def _machine_ids() -> list[str]:
    out: list[str] = []
    for line, cfg in LINES.items():
        for m in range(1, cfg["machines"] + 1):
            out.append(f"{line}.maquina-{m}")
    return out


MACHINE_IDS: Final[list[str]] = _machine_ids()


# ---------------------------------------------------------------------------
# Ambient temperature
# ---------------------------------------------------------------------------


def _daily_temp_profile(start: datetime, days: int, rng: np.random.Generator) -> pd.DataFrame:
    """Per-day ambient temperature stats over the window.

    Returns one row per day with mean, amplitude, and the resulting max.
    Late-June / early-July in central Portugal: ~22 °C average, ~5 °C
    amplitude over the day, occasional heat waves.
    """
    rows: list[dict[str, object]] = []
    for d in range(days):
        day = start + timedelta(days=d)
        base = 20.0 + rng.normal(0, 1.0)  # daily mean on the shop floor
        amplitude = 4.0 + rng.normal(0, 0.6)  # daily swing
        # Peak of a Ribatejo summer: most afternoons are hot. The first and last few
        # days are always hot so both demos reliably show the signal — demo-r1 replays
        # near the end, demo-r1-n2's emulator sweeps from the start (day 0).
        heat_wave = (d == 0) or (d >= days - 3) or (rng.random() < 0.6)
        # The shared floor stays comfortable (peaks ~24 °C) even on hot days: the heat
        # that trips line 3 is *local* to its spot by the cold-chain condenser and is
        # modelled per line in `_ambient_temp_series`, not baked into the floor peak.
        peak = base + amplitude
        rows.append(
            {
                "date": day.date(),
                "mean_c": round(base, 2),
                "amplitude_c": round(amplitude, 2),
                "peak_c": round(peak, 2),
                "hot_day": heat_wave,
            }
        )
    return pd.DataFrame(rows)


def _ambient_temp_series(
    start: datetime, end: datetime, profile: pd.DataFrame, rng: np.random.Generator
) -> pd.DataFrame:
    """5-minute ambient temperature readings for each line.

    The shop floor shares one comfortable ambient (peaks ~24 °C). Line 3 sits
    beside the cold-chain condenser, which vents heat: on hot summer afternoons
    its local ambient surges several degrees above the rest of the floor,
    climbing past 27 °C — the signal the reader correlates with the protective
    stops in Chapter 1. The other lines carry tiny microclimate offsets so they
    render as distinct traces, all staying well below 27 °C.
    """
    rows: list[dict[str, object]] = []
    step = timedelta(minutes=5)
    profile_by_date = profile.set_index("date")
    t = start
    while t < end:
        day = t.date()
        if day not in profile_by_date.index:
            t += step
            continue
        mean_c = float(profile_by_date.at[day, "mean_c"])
        peak_c = float(profile_by_date.at[day, "peak_c"])
        hot_day = bool(profile_by_date.at[day, "hot_day"])
        # Sinusoid: 0 at 06h, peaks around midday, back to 0 by 18h.
        hour = t.hour + t.minute / 60.0
        heat = max(0.0, np.sin(np.pi * (hour - 6) / 12.0))
        base_value = mean_c + (peak_c - mean_c) * heat
        for line, cfg in LINES.items():
            if cfg["thermal_sensitive"]:
                # Base +2 °C from the condenser, plus a strong daytime surge on hot
                # days that carries line 3 alone past the 27 °C threshold.
                offset = 2.0 + (5.0 * heat if hot_day else 0.0)
            else:
                offset = AMBIENT_MICRO_OFFSET_C.get(line, 0.0)
            noise = rng.normal(0, 0.3)  # independent per-sensor noise
            rows.append(
                {
                    "timestamp": t,
                    "machine_id": f"{line}.ambient",
                    "sensor": "ambient_temp_c",
                    "value": round(base_value + offset + noise, 2),
                    "unit": "C",
                }
            )
        t += step
    df = pd.DataFrame(rows, columns=SENSOR_READINGS_COLUMNS)
    return apply_dtypes(df, SENSOR_READINGS_DTYPES)


# ---------------------------------------------------------------------------
# Machine state events
# ---------------------------------------------------------------------------


def _sample_state(rng: np.random.Generator) -> str:
    states = list(STATE_WEIGHTS.keys())
    weights = np.array(list(STATE_WEIGHTS.values()))
    weights = weights / weights.sum()
    idx = rng.choice(len(states), p=weights)
    return states[int(idx)]


def _state_duration_s(state: str, rng: np.random.Generator) -> int:
    """Pick a plausible duration in seconds for a state segment."""
    if state == "running":
        return int(rng.integers(600, 3600))  # 10-60 min
    if state == "idle":
        return int(rng.integers(60, 600))  # 1-10 min
    if state == "stopped":
        return int(rng.integers(120, 900))  # 2-15 min
    if state == "fault":
        return int(rng.integers(300, 1800))  # 5-30 min
    if state == "setup":
        return int(rng.integers(180, 1200))  # 3-20 min
    if state == "cleaning":
        return int(rng.integers(900, 1800))  # 15-30 min
    return 60


def _shift_window(day: datetime, shift: str) -> tuple[datetime, datetime]:
    start_h, end_h = SHIFT_HOURS[shift]
    s = day.replace(hour=start_h % 24, minute=0, second=0, microsecond=0)
    if shift == "noite":
        e = s + timedelta(hours=8)
    else:
        e = day.replace(hour=end_h, minute=0, second=0, microsecond=0)
    return s, e


def _generate_machine_shift(
    machine_id: str,
    line: str,
    day: datetime,
    shift: str,
    is_hot_day: bool,
    rng: np.random.Generator,
) -> list[dict[str, object]]:
    """Generate state events for one machine over one shift."""
    s, e = _shift_window(day, shift)
    events: list[dict[str, object]] = []
    t = s
    while t < e:
        state = _sample_state(rng)
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

    # Inject the case-study signal: line-3 (cold-chain packing) trips on thermal
    # protection on hot summer afternoons, when ambient on line 3 climbs past 27 C —
    # the temperature correlation the reader discovers in Chapter 1.
    is_thermal_sensitive = LINES[line]["thermal_sensitive"]
    if is_thermal_sensitive and shift == "tarde" and is_hot_day:
        low, high = THERMAL_EXTRA_STOPS_PER_TARDE_HOT_DAY
        extras = int(rng.integers(low, high + 1))
        for _ in range(extras):
            offset_min = int(rng.integers(60, 7 * 60))
            ts = s + timedelta(minutes=offset_min)
            events.append(
                {
                    "timestamp": ts,
                    "machine_id": machine_id,
                    "state": "stopped",
                    "state_reason": "thermal_protection",
                    "duration_s": int(rng.integers(150, 300)),
                }
            )
    return events


# ---------------------------------------------------------------------------
# Production events
# ---------------------------------------------------------------------------


SKUS: Final[list[str]] = ["BCL-200", "BCL-400", "LZN-300", "ARV-250", "MNH-180"]


def _production_events(states_df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Aggregate hourly production per machine, using time-in-running as proxy."""
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
        # ~ 6 units per minute of running for a packaging line, with variance.
        produced = int(running_seconds / 60.0 * float(rng.uniform(5.0, 7.0)))
        rejection_rate = float(rng.uniform(0.005, 0.025))
        rejected = int(produced * rejection_rate)
        sku = SKUS[int(rng.integers(0, len(SKUS)))]
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
    """Generate the food-processing sector dataset.

    PT: Gera o dataset do sector alimentar.
    EN: Generates the food-processing sector dataset.

    Args:
        days: number of days to synthesise. Defaults to 30.
        seed: RNG seed for reproducibility. Defaults to
            :data:`~lib_comum.data_synth.base.DEFAULT_SEED`.

    Returns:
        Dict with three DataFrames: ``machine_states``, ``sensor_readings``,
        ``production_events``.
    """
    rng = make_rng(seed)
    start, end = time_window(days)
    profile = _daily_temp_profile(start, days, rng)
    sensors_df = _ambient_temp_series(start, end, profile, rng)

    profile_by_date = profile.set_index("date")
    state_rows: list[dict[str, object]] = []
    for line, cfg in LINES.items():
        for m in range(1, cfg["machines"] + 1):
            machine_id = f"{line}.maquina-{m}"
            for d in range(days):
                day = start + timedelta(days=d)
                hot = bool(profile_by_date.at[day.date(), "hot_day"])
                for shift in SHIFT_HOURS:
                    state_rows.extend(
                        _generate_machine_shift(machine_id, line, day, shift, hot, rng)
                    )

    states_df = pd.DataFrame(state_rows, columns=MACHINE_STATES_COLUMNS)
    states_df["timestamp"] = pd.to_datetime(states_df["timestamp"], utc=True)
    states_df = states_df.sort_values(["timestamp", "machine_id"]).reset_index(drop=True)
    states_df = apply_dtypes(states_df, MACHINE_STATES_DTYPES)

    production_df = _production_events(states_df, rng)

    return {
        "machine_states": states_df,
        "sensor_readings": sensors_df,
        "production_events": production_df,
    }


def write(
    out_dir: Path,
    *,
    days: int = 30,
    seed: int = DEFAULT_SEED,
    formats: tuple[str, ...] = ("parquet", "csv.gz"),
) -> dict[str, list[Path]]:
    """Generate and write the three tables to *out_dir*.

    PT: Gera e persiste as três tabelas. EN: Generates and writes the three
    tables to *out_dir*. Returns the paths written per table.
    """
    tables = generate(days=days, seed=seed)
    written: dict[str, list[Path]] = {}
    for name, df in tables.items():
        written[name] = write_table(df, out_dir, name, formats=formats)
    return written


def case_summary(tables: dict[str, pd.DataFrame]) -> str:
    """Human-readable summary of the case study signal embedded in *tables*.

    Used by tests and by ``tools/seed_synth_data.py`` to report what was
    generated.
    """
    states = tables["machine_states"]
    thermal = states[states["state_reason"] == "thermal_protection"]
    total_thermal_min = int(thermal["duration_s"].sum() / 60)
    n_machines = states["machine_id"].nunique()
    period_start = states["timestamp"].min()
    period_end = states["timestamp"].max()
    return (
        f"alimentar: {n_machines} machines, "
        f"{period_start:%Y-%m-%d} → {period_end:%Y-%m-%d}, "
        f"{len(thermal)} thermal-protection stops "
        f"(~{total_thermal_min} min total)"
    )


if __name__ == "__main__":  # pragma: no cover
    out = Path("receita-1-olho-da-fabrica/data-exemplo/alimentar")
    paths = write(out)
    for name, files in paths.items():
        print(f"{name}: {[str(p) for p in files]}")
