"""Synthetic data generators for the recipes.

PT: Geradores de dados sintéticos por sector.
EN: Sector synthetic data generators.

Implemented:

- ``alimentar`` — food processing (Recipe 1 case study).
- ``moldes`` — moulds / Marinha Grande (Recipe 2 case study).

Other sectors land in subsequent phases — see ``planeamento/01-plano-codigo-v1.md``.
"""

from __future__ import annotations

from lib_comum.data_synth import alimentar, moldes
from lib_comum.data_synth.base import DEFAULT_SEED, make_rng, time_window

__all__ = [
    "DEFAULT_SEED",
    "alimentar",
    "make_rng",
    "moldes",
    "time_window",
]
