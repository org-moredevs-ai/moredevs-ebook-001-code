"""Tests for the synthetic raw vibration waveform generator."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from lib_comum.plc_sim.vibration_signal import (
    BPFO_HZ,
    DEFAULT_SAMPLE_RATE_HZ,
    compute_spectrum_band_amp,
    default_period_end_from_window,
    synthesise_snapshot,
)


@pytest.fixture(scope="module")
def period_end():  # type: ignore[no-untyped-def]
    return default_period_end_from_window(days=30)


def test_snapshot_shape_and_payload(period_end) -> None:
    snap = synthesise_snapshot(
        machine_id="fresadora-cnc.maquina-1",
        sim_ts=period_end - timedelta(days=20),
        period_end=period_end,
        running=True,
    )
    n = DEFAULT_SAMPLE_RATE_HZ  # 1 second window
    assert snap.x.shape == (n,)
    assert snap.y.shape == (n,)
    assert snap.z.shape == (n,)
    assert snap.duration_s == pytest.approx(1.0)
    payload = snap.to_payload()
    assert payload["machine"] == "fresadora-cnc.maquina-1"
    assert payload["sample_rate_hz"] == n
    assert isinstance(payload["x"], list)
    assert len(payload["x"]) == n


def test_idle_machine_low_amplitude(period_end) -> None:
    snap = synthesise_snapshot(
        machine_id="prensa-250t.maquina-1",
        sim_ts=period_end - timedelta(days=2),  # would be faulty if running
        period_end=period_end,
        running=False,
    )
    rms = float(np.sqrt((snap.x**2).mean()))
    assert rms < 0.1, f"expected idle RMS < 0.1g, got {rms}"


def test_determinism_same_machine_same_ts(period_end) -> None:
    ts = period_end - timedelta(days=10)
    a = synthesise_snapshot(
        machine_id="fresadora-cnc.maquina-1",
        sim_ts=ts,
        period_end=period_end,
        running=True,
    )
    b = synthesise_snapshot(
        machine_id="fresadora-cnc.maquina-1",
        sim_ts=ts,
        period_end=period_end,
        running=True,
    )
    np.testing.assert_array_equal(a.x, b.x)
    np.testing.assert_array_equal(a.y, b.y)
    np.testing.assert_array_equal(a.z, b.z)


def test_press_bpfo_grows_with_wear(period_end) -> None:
    """The BPFO band must climb from near-zero to a clearly elevated level."""
    healthy_snap = synthesise_snapshot(
        machine_id="prensa-250t.maquina-1",
        sim_ts=period_end - timedelta(days=20),  # well before wear window
        period_end=period_end,
        running=True,
    )
    fault_snap = synthesise_snapshot(
        machine_id="prensa-250t.maquina-1",
        sim_ts=period_end - timedelta(hours=2),
        period_end=period_end,
        running=True,
    )
    healthy_bpfo = compute_spectrum_band_amp(
        healthy_snap.x, healthy_snap.sample_rate_hz, BPFO_HZ - 4, BPFO_HZ + 4
    )
    fault_bpfo = compute_spectrum_band_amp(
        fault_snap.x, fault_snap.sample_rate_hz, BPFO_HZ - 4, BPFO_HZ + 4
    )
    assert healthy_bpfo < 0.05, f"healthy BPFO amplitude was {healthy_bpfo}"
    assert fault_bpfo > 5 * healthy_bpfo, (
        f"BPFO must grow >5x; healthy={healthy_bpfo:.3f} fault={fault_bpfo:.3f}"
    )


def test_other_machines_do_not_show_bpfo(period_end) -> None:
    snap = synthesise_snapshot(
        machine_id="fresadora-cnc.maquina-1",
        sim_ts=period_end - timedelta(hours=2),
        period_end=period_end,
        running=True,
    )
    bpfo = compute_spectrum_band_amp(snap.x, snap.sample_rate_hz, BPFO_HZ - 4, BPFO_HZ + 4)
    assert bpfo < 0.05, f"healthy machine showed BPFO leak {bpfo}"


def test_band_amp_zero_outside_band(period_end) -> None:
    """A pure 25 Hz tone should not produce energy at 80 Hz."""
    sr = 1000
    t = np.arange(sr) / float(sr)
    tone = 0.5 * np.sin(2 * np.pi * 25.0 * t)
    in_band = compute_spectrum_band_amp(tone, sr, 23, 27)
    out_band = compute_spectrum_band_amp(tone, sr, 78, 82)
    assert in_band > 0.2
    assert out_band < 1e-3


def test_press_one_x_amplitude_stays_through_wear(period_end) -> None:
    """The 1x rotation harmonic is intrinsic to the machine — it should
    persist whether the bearing is healthy or faulty.
    """
    early_snap = synthesise_snapshot(
        machine_id="prensa-250t.maquina-1",
        sim_ts=period_end - timedelta(days=20),
        period_end=period_end,
        running=True,
    )
    late_snap = synthesise_snapshot(
        machine_id="prensa-250t.maquina-1",
        sim_ts=period_end - timedelta(hours=2),
        period_end=period_end,
        running=True,
    )
    early_1x = compute_spectrum_band_amp(early_snap.x, early_snap.sample_rate_hz, 23, 27)
    late_1x = compute_spectrum_band_amp(late_snap.x, late_snap.sample_rate_hz, 23, 27)
    # 1x band shouldn't collapse; allow plenty of jitter from the BPFO modulation.
    assert late_1x > 0.5 * early_1x
