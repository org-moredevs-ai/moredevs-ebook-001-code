"""Common utilities for synthetic data generators.

PT: Utilitários partilhados pelos geradores sintéticos.
EN: Shared utilities for synthetic data generators — RNG construction,
output writers, time-window helpers.

All generators must be deterministic given the same seed. This module
exposes :func:`make_rng` to enforce that.
"""

from __future__ import annotations

import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_SEED: int = 20260509
"""Fixed seed for reproducibility. Date of project kickoff."""


def make_rng(seed: int = DEFAULT_SEED) -> np.random.Generator:
    """Construct a numpy ``Generator`` from a seed.

    PT: Constrói um ``Generator`` numpy a partir de uma seed.
    EN: Constructs a numpy ``Generator`` from a seed.
    """
    return np.random.default_rng(seed)


def time_window(days: int, end: datetime | None = None) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` UTC timestamps spanning *days* full days, ending at *end*.

    PT: Devolve a janela ``(início, fim)`` em UTC com a duração pedida.
    EN: Returns the UTC ``(start, end)`` window with the requested span.

    If *end* is omitted, anchors at a deterministic UTC midnight so the
    generated dataset stays stable across runs.
    """
    if end is None:
        end = datetime(2026, 7, 1, tzinfo=UTC)
    start = end - timedelta(days=days)
    return start, end


def write_table(
    df: pd.DataFrame,
    out_dir: Path,
    name: str,
    *,
    formats: tuple[str, ...] = ("parquet", "csv.gz"),
) -> list[Path]:
    """Persist *df* under ``out_dir/{name}.{fmt}`` for each requested format.

    PT: Persiste *df* em ``out_dir`` nos formatos pedidos. Devolve os
    caminhos escritos.
    EN: Persists *df* under ``out_dir`` in the requested formats.
    Returns the written paths.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for fmt in formats:
        if fmt == "parquet":
            path = out_dir / f"{name}.parquet"
            df.to_parquet(path, index=False, compression="zstd")
        elif fmt == "csv.gz":
            path = out_dir / f"{name}.csv.gz"
            with gzip.open(path, "wt") as f:
                df.to_csv(f, index=False)
        elif fmt == "csv":
            path = out_dir / f"{name}.csv"
            df.to_csv(path, index=False)
        else:
            raise ValueError(f"Unsupported format: {fmt}")
        written.append(path)
    return written


def shift_label(ts: pd.Series) -> pd.Series:
    """Tag each timestamp with a shift label.

    PT: Marca cada timestamp com o turno correspondente.
    EN: Tags each timestamp with its shift label (manha / tarde / noite).

    Shifts (local-ish, ignoring DST since the dataset is UTC-aligned):
    - ``manha``: 06:00-14:00
    - ``tarde``: 14:00-22:00
    - ``noite``: 22:00-06:00
    """
    hour = ts.dt.hour
    return pd.Series(
        np.where(
            (hour >= 6) & (hour < 14),
            "manha",
            np.where((hour >= 14) & (hour < 22), "tarde", "noite"),
        ),
        index=ts.index,
        dtype="category",
    )
