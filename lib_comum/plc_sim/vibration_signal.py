"""Synthetic raw vibration waveform generator.

PT: Gera 1 segundo de amostras brutas de acelerómetro (3 eixos, 1 kHz por
omissão) para cada máquina do dataset de moldes. As amostras incluem a
harmónica fundamental de rotação, fricção de fundo e — para a prensa-1 ao
longo do desgaste — a componente BPFO (chumaceira da pista externa) com
sidebands e impulsos. O receptor Python (Receita 2 Nível 1) pode correr
FFT sobre estes snapshots como faria sobre dados reais do ADXL345.
EN: Generates 1 second of raw accelerometer samples (3 axes, 1 kHz by
default) for each moulds-dataset machine. Samples include the 1x
rotation fundamental, background friction, and — for press-1 along the
wear curve — the BPFO component (outer-race bearing fault) with sidebands
and impulses. The Python receiver (Recipe 2 Tier 1) can run FFT on these
snapshots just as it would on real ADXL345 data.

The waveform model is intentionally simple but physically plausible:

- Healthy machine: a sinusoid at the rotation frequency (``healthy_dom_hz``)
  with small amplitude, plus low-frequency 1/f noise.
- Faulty bearing: that same fundamental keeps existing, *plus* a growing
  BPFO sinusoid at ``BPFO_HZ`` modulated by the 1x rotation (sidebands at
  BPFO ± rotation), *plus* periodic impulses (the characteristic bearing
  "ringing"). Amplitude follows the same logistic wear curve as the
  ``vibration_metrics`` table in ``lib_comum.data_synth.moldes``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from lib_comum.data_synth.moldes import (
    BPFO_HZ,
    MACHINES,
    WEAR_WINDOW_DAYS,
    _logistic,
    _wear_progress,
)

DEFAULT_SAMPLE_RATE_HZ: int = 1000
"""Default sample rate — matches the ADXL345 sampling cadence the firmware uses."""

DEFAULT_WINDOW_S: float = 1.0
"""Window length per snapshot in seconds."""


@dataclass(frozen=True, slots=True)
class WaveformSnapshot:
    """A 1-second 3-axis raw acceleration snapshot.

    PT: Snapshot de 1 segundo de aceleração nos 3 eixos.
    EN: 1-second 3-axis raw-acceleration snapshot.

    Attributes:
        machine_id: machine the snapshot belongs to.
        sim_ts: simulated UTC timestamp the snapshot represents.
        sample_rate_hz: number of samples per second per axis.
        x, y, z: float arrays of length ``round(sample_rate_hz * window_s)``.
    """

    machine_id: str
    sim_ts: datetime
    sample_rate_hz: int
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray

    @property
    def duration_s(self) -> float:
        return float(len(self.x)) / float(self.sample_rate_hz)

    def to_payload(self) -> dict[str, object]:
        """Encode as a JSON-friendly dict for MQTT transport.

        PT: Codifica para um dicionário compatível com JSON.
        EN: Encodes as a JSON-friendly dict.
        """
        return {
            "machine": self.machine_id,
            "ts_iso": self.sim_ts.isoformat(),
            "sample_rate_hz": self.sample_rate_hz,
            "x": [round(float(v), 5) for v in self.x],
            "y": [round(float(v), 5) for v in self.y],
            "z": [round(float(v), 5) for v in self.z],
        }


def _axis_amplitude(axis: str, base: float) -> float:
    """Apply a per-axis scaling factor matching the moldes generator."""
    return {"x": 1.0, "y": 0.85, "z": 0.6}[axis] * base


def synthesise_axis(
    *,
    machine_id: str,
    axis: str,
    sim_ts: datetime,
    period_end: datetime,
    running: bool,
    sample_rate_hz: int,
    window_s: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate a single-axis waveform for one snapshot.

    PT: Gera a forma-de-onda de um eixo para um snapshot.
    EN: Builds the single-axis waveform for one snapshot.
    """
    cfg = MACHINES[machine_id]
    n = round(sample_rate_hz * window_s)
    t = np.arange(n, dtype=np.float64) / float(sample_rate_hz)

    if not running:
        # Stopped / idle machines: only thermal-electrical noise floor.
        noise_amp = _axis_amplitude(axis, 0.04)
        return rng.normal(0, noise_amp, n).astype(np.float64)

    fundamental_hz = float(cfg["healthy_dom_hz"])
    fundamental_amp = _axis_amplitude(axis, float(cfg["healthy_rms_g"]))

    # Random phase per snapshot so the spectrum looks like real-world stationary
    # noise from minute to minute.
    phase = float(rng.uniform(0, 2 * np.pi))
    waveform = fundamental_amp * np.sin(2 * np.pi * fundamental_hz * t + phase)

    # Small 2x harmonic, present in healthy machines too (gear meshing, motor).
    waveform += 0.25 * fundamental_amp * np.sin(4 * np.pi * fundamental_hz * t + phase)

    # Friction noise floor (white, scaled to the machine's baseline RMS).
    waveform += rng.normal(0, 0.15 * fundamental_amp, n)

    if cfg["fault_bearing"]:
        wear = _logistic(_wear_progress(sim_ts, period_end))
        if wear > 0.0:
            # BPFO component scaled by wear progress.
            bpfo_amp = fundamental_amp * 2.2 * wear
            bpfo_signal = bpfo_amp * np.sin(2 * np.pi * BPFO_HZ * t + phase)
            # Amplitude-modulate the BPFO by the rotation harmonic to produce
            # realistic sidebands at BPFO ± fundamental.
            modulation = 1.0 + 0.6 * np.sin(2 * np.pi * fundamental_hz * t)
            waveform += bpfo_signal * modulation

            # Periodic impulses — the characteristic bearing "ringing" — at
            # the BPFO rate. They drive kurtosis up. Amplitude grows with wear.
            impulse_period_samples = max(1, round(sample_rate_hz / BPFO_HZ))
            impulse_amp = fundamental_amp * 4.0 * wear
            # Decaying-exponential pulse so it looks like a damped ring.
            pulse_len = max(2, impulse_period_samples // 3)
            pulse_idx = np.arange(pulse_len)
            pulse_shape = np.exp(-pulse_idx / max(1.0, pulse_len / 4.0)) * np.sin(
                2 * np.pi * (BPFO_HZ * 3) * pulse_idx / sample_rate_hz
            )
            impulses = np.zeros(n)
            for start in range(0, n - pulse_len, impulse_period_samples):
                jitter = int(rng.integers(-3, 4))
                start_i = max(0, start + jitter)
                end_i = min(n, start_i + pulse_len)
                impulses[start_i:end_i] += pulse_shape[: end_i - start_i] * impulse_amp
            waveform += impulses

    return waveform.astype(np.float64)


def synthesise_snapshot(
    *,
    machine_id: str,
    sim_ts: datetime,
    period_end: datetime,
    running: bool,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    window_s: float = DEFAULT_WINDOW_S,
    rng: np.random.Generator | None = None,
) -> WaveformSnapshot:
    """Generate one :class:`WaveformSnapshot` for *machine_id* at *sim_ts*.

    PT: Gera um snapshot de waveform para a máquina.
    EN: Generates one waveform snapshot for the machine.

    *rng* lets the caller (simulator, tests) drive determinism explicitly.
    When omitted, a snapshot-stable RNG is derived from the timestamp.
    """
    if rng is None:
        # Deterministic seed from (machine, timestamp) so the same snapshot is
        # reproducible across runs without leaking state between machines.
        seed = abs(hash((machine_id, sim_ts.isoformat()))) % (2**32)
        rng = np.random.default_rng(seed)

    axes = {}
    for axis in ("x", "y", "z"):
        axes[axis] = synthesise_axis(
            machine_id=machine_id,
            axis=axis,
            sim_ts=sim_ts,
            period_end=period_end,
            running=running,
            sample_rate_hz=sample_rate_hz,
            window_s=window_s,
            rng=rng,
        )

    return WaveformSnapshot(
        machine_id=machine_id,
        sim_ts=sim_ts,
        sample_rate_hz=sample_rate_hz,
        x=axes["x"],
        y=axes["y"],
        z=axes["z"],
    )


def compute_spectrum_band_amp(
    signal: np.ndarray,
    sample_rate_hz: int,
    band_low_hz: float,
    band_high_hz: float,
) -> float:
    """Return the RMS amplitude inside ``[band_low_hz, band_high_hz]``.

    PT: Devolve a amplitude RMS dentro da banda indicada.
    EN: Returns the RMS amplitude inside the requested band.

    Used by the FFT alert receiver to track the 1x-rotation band and the
    BPFO band separately.
    """
    n = len(signal)
    if n == 0:
        return 0.0
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)
    mask = (freqs >= band_low_hz) & (freqs <= band_high_hz)
    if not np.any(mask):
        return 0.0
    # Convert FFT magnitude back to time-domain amplitude.
    amplitudes = (2.0 / n) * np.abs(spectrum[mask])
    return float(np.sqrt(np.mean(amplitudes**2)))


def default_period_end_from_window(days: int = 30) -> datetime:
    """Return the canonical period end for a *days*-day dataset.

    PT: Devolve o fim do período canónico para um dataset.
    EN: Returns the canonical period end for a *days*-day dataset.

    This mirrors :func:`lib_comum.data_synth.base.time_window`, used by
    simulators that want to align their snapshots with the moldes dataset.
    """
    from lib_comum.data_synth.base import time_window

    _, end = time_window(days=days)
    return end


__all__ = [
    "BPFO_HZ",
    "DEFAULT_SAMPLE_RATE_HZ",
    "DEFAULT_WINDOW_S",
    "WEAR_WINDOW_DAYS",
    "WaveformSnapshot",
    "compute_spectrum_band_amp",
    "default_period_end_from_window",
    "synthesise_axis",
    "synthesise_snapshot",
]
