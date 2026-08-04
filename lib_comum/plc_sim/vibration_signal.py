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
    FAULT_RMS_GAIN,
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
    wear = _logistic(_wear_progress(sim_ts, period_end)) if cfg["fault_bearing"] else 0.0

    # Random phase per snapshot so the spectrum looks like real-world stationary
    # noise from minute to minute.
    phase = float(rng.uniform(0, 2 * np.pi))

    # Build the waveform SHAPE with relative amplitudes; the overall level is
    # normalised at the end so the measured RMS follows the same wear curve as
    # the ``vibration_metrics`` table in ``lib_comum.data_synth.moldes`` — that
    # way the live feature_extractor recovers the RMS and kurtosis the book cites.
    #
    # Broadband friction noise DOMINATES a healthy signal, so its kurtosis sits
    # near the Gaussian value of 3 (a pure tone alone would give ~1.5).
    shape = rng.normal(0.0, 0.75, n)
    # Rotation fundamental (1x) plus a small 2x harmonic: the clean FFT peak that
    # marks the dominant frequency at 25 Hz while the machine is healthy.
    shape += 0.60 * np.sin(2 * np.pi * fundamental_hz * t + phase)
    shape += 0.15 * np.sin(4 * np.pi * fundamental_hz * t + phase)

    if wear > 0.0:
        # BPFO tone with rotation sidebands, growing with wear. As it grows it
        # overtakes the rotation peak, drifting the dominant frequency 25 -> 83 Hz.
        bpfo_signal = (1.1 * wear) * np.sin(2 * np.pi * BPFO_HZ * t + phase)
        bpfo_signal *= 1.0 + 0.6 * np.sin(2 * np.pi * fundamental_hz * t)
        shape += bpfo_signal

        # Sparse, tall impulses — the characteristic bearing "ringing". They are
        # rare (a few per window) and sharp, so they push kurtosis from ~3 towards
        # ~12 at the fault point, AHEAD of the RMS. We size them to carry a
        # wear-dependent fraction of the signal energy, which is what actually
        # controls the kurtosis a reader sees in the feature table.
        pulse_len = 2
        pulse_shape = np.exp(-np.arange(pulse_len) / 1.0)  # tall, decays fast
        n_impulses = max(1, round(0.014 * n))  # ~14 per 1 kHz window -> genuinely rare
        impulses = np.zeros(n)
        starts = rng.integers(0, n - pulse_len, size=n_impulses)
        signs = rng.choice(np.array([-1.0, 1.0]), size=n_impulses)
        for start_i, sign in zip(starts, signs, strict=False):
            impulses[start_i : start_i + pulse_len] += sign * pulse_shape
        # Scale the impulse train so it holds energy fraction ``frac`` of the
        # background. The kurtosis grows convexly with ``frac``, so a sqrt law
        # tracks the target curve (kurtosis ~= 3 + 9*wear) across the whole ramp.
        frac = min(0.5, 0.40 * float(np.sqrt(wear)))
        bg_energy = float(np.sum(shape**2))
        imp_energy = float(np.sum(impulses**2))
        if frac > 0.0 and imp_energy > 0.0 and bg_energy > 0.0:
            scale = float(np.sqrt(frac / (1.0 - frac) * bg_energy / imp_energy))
            shape += scale * impulses

    # Normalise to the analytic target RMS from the moldes wear model
    # (rms = base_rms * (1 + (FAULT_RMS_GAIN - 1) * wear)). Scaling is RMS-only and
    # leaves the kurtosis — set by the noise/tone/impulse mix above — untouched.
    base_rms = _axis_amplitude(axis, float(cfg["healthy_rms_g"]))
    target_rms = base_rms * (1.0 + (FAULT_RMS_GAIN - 1.0) * wear)
    current_rms = float(np.sqrt(np.mean(shape**2)))
    if current_rms > 0.0:
        shape *= target_rms / current_rms

    return shape.astype(np.float64)


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
