"""Determinism, schema and case-study presence tests for the moldes generator."""

from __future__ import annotations

import pandas as pd
import pytest

from lib_comum.data_synth import moldes
from lib_comum.data_synth.base import time_window
from lib_comum.data_synth.schemas import (
    MACHINE_STATES_COLUMNS,
    PRODUCTION_EVENTS_COLUMNS,
    SENSOR_READINGS_COLUMNS,
    VIBRATION_METRICS_COLUMNS,
)


@pytest.fixture(scope="module")
def small_dataset() -> dict[str, pd.DataFrame]:
    """7-day dataset used by most tests."""
    return moldes.generate(days=7, seed=20260509)


@pytest.fixture(scope="module")
def full_dataset() -> dict[str, pd.DataFrame]:
    """30-day dataset used to verify the case-study signal develops fully.

    Takes ~30 s on a recent laptop. Tests that need it are tagged ``slow``;
    ``make test`` skips them by default.
    """
    return moldes.generate(days=30, seed=20260509)


def test_returns_four_tables(small_dataset: dict[str, pd.DataFrame]) -> None:
    assert set(small_dataset.keys()) == {
        "machine_states",
        "sensor_readings",
        "vibration_metrics",
        "production_events",
    }


def test_schemas_match(small_dataset: dict[str, pd.DataFrame]) -> None:
    assert list(small_dataset["machine_states"].columns) == MACHINE_STATES_COLUMNS
    assert list(small_dataset["sensor_readings"].columns) == SENSOR_READINGS_COLUMNS
    assert list(small_dataset["vibration_metrics"].columns) == VIBRATION_METRICS_COLUMNS
    assert list(small_dataset["production_events"].columns) == PRODUCTION_EVENTS_COLUMNS


def test_machine_roster_size(small_dataset: dict[str, pd.DataFrame]) -> None:
    vib = small_dataset["vibration_metrics"]
    # 1 press + 3 CNC mills + 2 EDMs = 6 machines
    assert vib["machine_id"].nunique() == 6
    assert set(vib["axis"].unique()) == {"x", "y", "z"}


def test_determinism_same_seed() -> None:
    a = moldes.generate(days=3, seed=20260509)
    b = moldes.generate(days=3, seed=20260509)
    for table in a:
        pd.testing.assert_frame_equal(a[table], b[table])


def test_seed_varies_output() -> None:
    a = moldes.generate(days=3, seed=20260509)
    b = moldes.generate(days=3, seed=20260510)
    # Distinct seeds must produce distinct event counts on at least one table.
    assert len(a["machine_states"]) != len(b["machine_states"]) or (
        not a["machine_states"].equals(b["machine_states"])
    )


def test_vibration_metrics_dtypes(small_dataset: dict[str, pd.DataFrame]) -> None:
    vib = small_dataset["vibration_metrics"]
    assert vib["axis"].dtype.name == "category"
    assert pd.api.types.is_datetime64_any_dtype(vib["timestamp"])
    assert (vib["rms_g"] >= 0).all()
    assert (vib["peak_g"] >= vib["rms_g"]).all()
    assert (vib["kurtosis"] > 0).all()


@pytest.mark.slow
def test_press_bearing_signal_isolates_to_press(
    full_dataset: dict[str, pd.DataFrame],
) -> None:
    """The wear signal must climb only on the press, not on its neighbours."""
    vib = full_dataset["vibration_metrics"]
    x = vib[vib["axis"] == "x"].copy()

    growth_per_machine: dict[str, float] = {}
    for machine_id, group in x.groupby("machine_id", observed=True):
        group = group.sort_values("timestamp")
        # Use 1-day windows to smooth out noise.
        first_day = group.head(1440)
        last_day = group.tail(1440)
        first_rms = float(first_day["rms_g"].mean())
        last_rms = float(last_day["rms_g"].mean())
        growth_per_machine[str(machine_id)] = last_rms / first_rms if first_rms else float("inf")

    press_growth = growth_per_machine["prensa-250t.maquina-1"]
    other_growths = [v for k, v in growth_per_machine.items() if k != "prensa-250t.maquina-1"]

    # The press must show clearly elevated RMS (>2x baseline) at the end.
    assert press_growth >= 2.0, f"press RMS ratio was {press_growth:.2f} (<2.0)"

    # Other machines should remain within ~1.5x baseline (noise + slow drift).
    for ratio in other_growths:
        assert ratio < 1.6, f"non-press machine grew {ratio:.2f}x — leak?"


@pytest.mark.slow
def test_press_dominant_frequency_drifts_to_bpfo(
    full_dataset: dict[str, pd.DataFrame],
) -> None:
    """Dominant frequency on the press must migrate toward BPFO over the period."""
    vib = full_dataset["vibration_metrics"]
    press = (
        vib[(vib["machine_id"] == "prensa-250t.maquina-1") & (vib["axis"] == "x")]
        .copy()
        .sort_values("timestamp")
    )
    # Only look at samples taken while the press is running (dom_freq > 0).
    running = press[press["dominant_freq_hz"] > 0]
    first_500 = running.head(500)
    last_500 = running.tail(500)

    first_dom = float(first_500["dominant_freq_hz"].mean())
    last_dom = float(last_500["dominant_freq_hz"].mean())

    # Healthy press idles around 25 Hz (1x rotation). BPFO sits at 83 Hz.
    assert first_dom < 40.0, f"healthy press dominant freq was {first_dom:.1f} Hz"
    assert last_dom > 70.0, f"end-of-life dominant freq was {last_dom:.1f} Hz"


@pytest.mark.slow
def test_fault_event_seeded_at_end(full_dataset: dict[str, pd.DataFrame]) -> None:
    """The deterministic bearing-failure fault event must appear in machine_states."""
    states = full_dataset["machine_states"]
    fault = states[
        (states["machine_id"] == "prensa-250t.maquina-1")
        & (states["state_reason"] == "bearing_failure")
    ]
    assert len(fault) == 1
    assert fault["state"].iloc[0] == "fault"
    # It should land near the end of the configured period (within the last hour).
    # states.timestamp.max() can spill into the next morning because noite shifts
    # cross midnight, so use the canonical period end from time_window().
    _, period_end = time_window(days=30)
    fault_ts = pd.Timestamp(fault["timestamp"].iloc[0]).to_pydatetime()
    assert (period_end - fault_ts).total_seconds() < 3600


@pytest.mark.slow
def test_production_per_family_makes_sense(
    full_dataset: dict[str, pd.DataFrame],
) -> None:
    prod = full_dataset["production_events"]
    # Per machine: press produces many more parts than CNC mills (long cycles)
    # which produce more than EDMs (very long cycles).
    by_family = (
        prod.assign(family=prod["machine_id"].str.split(".").str[0])
        .groupby("family", observed=True)["units_produced"]
        .sum()
    )
    assert by_family["prensa-250t"] > by_family["fresadora-cnc"] > by_family["edm"]


def test_case_summary_runs(small_dataset: dict[str, pd.DataFrame]) -> None:
    summary = moldes.case_summary(small_dataset)
    assert "moldes" in summary
    assert "press-1" in summary
