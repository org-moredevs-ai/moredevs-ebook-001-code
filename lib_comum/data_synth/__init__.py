"""Synthetic data generators for the recipes.

PT: Geradores de dados sintéticos por sector.
EN: Sector synthetic data generators.

Currently implemented: ``alimentar`` (Recipe 1). Other sectors land in
subsequent phases — see ``planeamento/01-plano-codigo-v1.md``.
"""

from __future__ import annotations

from lib_comum.data_synth import alimentar
from lib_comum.data_synth.base import DEFAULT_SEED, make_rng, time_window

__all__ = [
    "DEFAULT_SEED",
    "alimentar",
    "make_rng",
    "time_window",
]
