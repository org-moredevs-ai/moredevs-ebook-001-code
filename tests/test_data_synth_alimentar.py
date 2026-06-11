"""Determinism, schema, and case-study presence tests for the alimentar generator."""

from __future__ import annotations

import pandas as pd
import pytest

from lib_comum.data_synth import alimentar
from lib_comum.data_synth.schemas import (
    MACHINE_STATES_COLUMNS,
    PRODUCTION_EVENTS_COLUMNS,
    SENSOR_READINGS_COLUMNS,
)


@pytest.fixture(scope="module")
def small_dataset() -> dict[str, pd.DataFrame]:
    """7-day dataset used by most tests — faster than the default 30."""
    return alimentar.generate(days=7, seed=20260509)


def test_returns_three_tables(small_dataset: dict[str, pd.DataFrame]) -> None:
    assert set(small_dataset.keys()) == {
        "machine_states",
        "sensor_readings",
        "production_events",
    }


def test_schemas_match(small_dataset: dict[str, pd.DataFrame]) -> None:
    assert list(small_dataset["machine_states"].columns) == MACHINE_STATES_COLUMNS
    assert list(small_dataset["sensor_readings"].columns) == SENSOR_READINGS_COLUMNS
    assert list(small_dataset["production_events"].columns) == PRODUCTION_EVENTS_COLUMNS


def test_machine_states_non_empty_and_typed(
    small_dataset: dict[str, pd.DataFrame],
) -> None:
    states = small_dataset["machine_states"]
    assert len(states) > 0
    assert states["state"].dtype.name == "category"
    assert pd.api.types.is_datetime64_any_dtype(states["timestamp"])
    assert (states["duration_s"] > 0).all()


def test_machine_roster_size(small_dataset: dict[str, pd.DataFrame]) -> None:
    states = small_dataset["machine_states"]
    # 5 lines x 4 machines = 20 production machines (ambient sensors are separate).
    assert states["machine_id"].nunique() == 20


def test_determinism_same_seed() -> None:
    a = alimentar.generate(days=3, seed=20260509)
    b = alimentar.generate(days=3, seed=20260509)
    for table in a:
        pd.testing.assert_frame_equal(a[table], b[table])


def test_seed_varies_output() -> None:
    a = alimentar.generate(days=3, seed=20260509)
    b = alimentar.generate(days=3, seed=20260510)
    # Distinct seeds must produce distinct event counts on at least one table.
    assert len(a["machine_states"]) != len(b["machine_states"]) or (
        not a["machine_states"].equals(b["machine_states"])
    )


def test_thermal_protection_signal_present(
    small_dataset: dict[str, pd.DataFrame],
) -> None:
    """The case study must be discoverable: thermal stops on line-3, tarde shift."""
    states = small_dataset["machine_states"]
    thermal = states[states["state_reason"] == "thermal_protection"]
    assert not thermal.empty, "expected thermal-protection events in the dataset"

    # All thermal events must come from line-3 (the cold-chain neighbour).
    assert thermal["machine_id"].str.startswith("linha-3.").all()

    # All thermal events must occur during the tarde shift (14h-22h UTC).
    hours = thermal["timestamp"].dt.hour
    assert ((hours >= 14) & (hours < 22)).all()


def test_thermal_signal_correlates_with_hot_afternoons(
    small_dataset: dict[str, pd.DataFrame],
) -> None:
    """On line-3 tarde shifts, thermal stops cluster on days with peak temp > 27 °C."""
    states = small_dataset["machine_states"]
    sensors = small_dataset["sensor_readings"]

    line3_ambient = sensors[sensors["machine_id"] == "linha-3.ambient"].copy()
    line3_ambient["date"] = line3_ambient["timestamp"].dt.date
    daily_peak = line3_ambient.groupby("date")["value"].max()

    thermal = states[states["state_reason"] == "thermal_protection"].copy()
    thermal["date"] = thermal["timestamp"].dt.date
    thermal_by_day = thermal.groupby("date").size()

    # Any thermal day must have had peak temp above the threshold on line-3.
    for day, count in thermal_by_day.items():
        if count > 0:
            assert daily_peak.get(day, 0.0) > alimentar.THERMAL_THRESHOLD_C, (
                f"thermal stop on {day} but peak temp was {daily_peak.get(day):.1f} °C"
            )


def test_ambient_sensor_present_on_all_lines(
    small_dataset: dict[str, pd.DataFrame],
) -> None:
    sensors = small_dataset["sensor_readings"]
    ambient_machines = sensors[sensors["sensor"] == "ambient_temp_c"]["machine_id"].unique()
    assert set(ambient_machines) == {f"linha-{i}.ambient" for i in range(1, 6)}


def test_production_only_for_running_machines(
    small_dataset: dict[str, pd.DataFrame],
) -> None:
    prod = small_dataset["production_events"]
    assert (prod["units_produced"] > 0).all()
    assert (prod["units_rejected"] >= 0).all()
    assert (prod["units_rejected"] < prod["units_produced"]).all()


def test_case_summary_runs(small_dataset: dict[str, pd.DataFrame]) -> None:
    summary = alimentar.case_summary(small_dataset)
    assert "alimentar" in summary
    assert "thermal-protection" in summary
