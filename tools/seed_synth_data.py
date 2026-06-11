"""Generate synthetic datasets for every recipe.

PT: Orquestra os geradores sintéticos por sector e por receita.
EN: Orchestrates per-sector synthetic data generators.

Usage::

    uv run python -m tools.seed_synth_data --all
    uv run python -m tools.seed_synth_data --recipe 1 --sector alimentar
    uv run python -m tools.seed_synth_data --recipe 1 --sector alimentar --days 7

Outputs to ``receita-<N>-.../data-exemplo/<sector>/`` next to the recipe.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

from lib_comum.data_synth import alimentar
from lib_comum.data_synth.base import DEFAULT_SEED

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

RECIPE_DIRS: dict[int, str] = {
    1: "receita-1-olho-da-fabrica",
    2: "receita-2-maquina-avisa",
    3: "receita-3-orcamentista",
    4: "receita-4-corte-sem-desperdicio",
    5: "receita-5-promessa-prazo",
}

SECTORS_BY_RECIPE: dict[int, list[str]] = {
    1: ["alimentar"],  # metalomecanica + textil land in a subsequent iteration
}


def _generator(sector: str):
    if sector == "alimentar":
        return alimentar
    raise ValueError(f"Unknown sector: {sector}")


def _seed_one(recipe: int, sector: str, days: int, seed: int) -> None:
    if recipe not in RECIPE_DIRS:
        raise ValueError(f"Unknown recipe: {recipe}")
    out_dir = REPO_ROOT / RECIPE_DIRS[recipe] / "data-exemplo" / sector
    print(f"  → {recipe=} {sector=} days={days} seed={seed} out={out_dir}")
    written = _generator(sector).write(out_dir, days=days, seed=seed)
    for table, paths in written.items():
        for p in paths:
            try:
                rel = p.relative_to(REPO_ROOT)
            except ValueError:
                rel = p
            print(f"      {table}: {rel} ({p.stat().st_size:_} bytes)")
    summary = _generator(sector).case_summary(_generator(sector).generate(days=days, seed=seed))
    print(f"      summary: {summary}")


def _expand_targets(
    recipes: Iterable[int] | None, sectors: Iterable[str] | None
) -> list[tuple[int, str]]:
    targets: list[tuple[int, str]] = []
    iter_recipes = list(recipes) if recipes else list(SECTORS_BY_RECIPE.keys())
    for r in iter_recipes:
        available = SECTORS_BY_RECIPE.get(r, [])
        chosen = list(sectors) if sectors else available
        for s in chosen:
            if s in available:
                targets.append((r, s))
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Generate every implemented sector.")
    parser.add_argument(
        "--recipe",
        type=int,
        choices=list(RECIPE_DIRS.keys()),
        action="append",
        help="Target recipe(s). May be passed multiple times.",
    )
    parser.add_argument(
        "--sector",
        type=str,
        action="append",
        help="Target sector(s). May be passed multiple times.",
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    if not args.all and not args.recipe:
        parser.error("Pass --all or at least one --recipe N.")

    targets = _expand_targets(
        recipes=None if args.all else args.recipe,
        sectors=None if args.all else args.sector,
    )

    if not targets:
        print("Nothing to do — no (recipe, sector) targets matched.", file=sys.stderr)
        return 1

    print(f"Seeding {len(targets)} dataset(s):")
    for recipe, sector in targets:
        _seed_one(recipe, sector, days=args.days, seed=args.seed)

    print("Done.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
