"""Recipe 4 Tier 1 — rectangular nesting (cutting-stock) with rectpack.

PT: Encaixe de peças rectangulares numa ou mais folhas, com largura de corte
(*kerf*) e medição de aproveitamento. Envolve a biblioteca ``rectpack`` (que
implementa heurísticas *bottom-left* / *skyline* / *guillotine*) e devolve as
posições e o aproveitamento — o número que importa ao dono da fábrica.

EN: Packs rectangular pieces into one or more sheets, with cut width (*kerf*)
and utilisation measurement. Wraps the ``rectpack`` library (bottom-left /
skyline / guillotine heuristics) and returns the placements and the utilisation
— the number the factory owner cares about.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from rectpack import newPacker


@dataclass(frozen=True, slots=True)
class Piece:
    """A rectangular piece to cut, *quantity* times."""

    id: str
    width_mm: float
    height_mm: float
    quantity: int = 1

    @property
    def area_mm2(self) -> float:
        return self.width_mm * self.height_mm


@dataclass(frozen=True, slots=True)
class Sheet:
    """Stock sheet (or roll) dimensions and how many are available."""

    width_mm: float
    height_mm: float
    count: int = 10

    @property
    def area_mm2(self) -> float:
        return self.width_mm * self.height_mm


@dataclass(frozen=True, slots=True)
class Placement:
    """Where one piece ended up on a sheet (dimensions exclude the kerf)."""

    piece_id: str
    sheet_index: int
    x: float
    y: float
    width: float
    height: float
    rotated: bool


@dataclass(frozen=True, slots=True)
class NestingResult:
    """Outcome of a packing run."""

    sheet: Sheet
    placements: list[Placement]
    sheets_used: int
    placed_piece_area_mm2: float
    unplaced: list[str]


def _is_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def pack_rectangles(
    pieces: list[Piece],
    sheet: Sheet,
    *,
    kerf_mm: float = 3.0,
    allow_rotation: bool = True,
) -> NestingResult:
    """Pack rectangular *pieces* into *sheet* copies (rectpack heuristic).

    PT: Cada peça é inflada por ``kerf_mm`` em largura e altura para os cortes
    adjacentes não se comerem. Devolve as posições e o aproveitamento.
    EN: Each piece is inflated by ``kerf_mm`` so adjacent cuts don't eat into
    each other. Returns placements and utilisation.
    """
    packer = newPacker(rotation=allow_rotation)
    area_by_id = {p.id: p.area_mm2 for p in pieces}
    width_by_id = {p.id: p.width_mm for p in pieces}

    added: Counter[str] = Counter()
    for piece in pieces:
        added[piece.id] += piece.quantity
        for _ in range(piece.quantity):
            packer.add_rect(piece.width_mm + kerf_mm, piece.height_mm + kerf_mm, rid=piece.id)
    packer.add_bin(sheet.width_mm, sheet.height_mm, count=max(1, sheet.count))
    packer.pack()

    placements: list[Placement] = []
    placed: Counter[str] = Counter()
    used_bins: set[int] = set()
    placed_area = 0.0
    for bin_index, x, y, w, h, rid in packer.rect_list():
        used_bins.add(int(bin_index))
        placed[rid] += 1
        placed_area += area_by_id.get(rid, 0.0)
        rotated = allow_rotation and not _is_close(w - kerf_mm, width_by_id.get(rid, w - kerf_mm))
        placements.append(
            Placement(
                piece_id=str(rid),
                sheet_index=int(bin_index),
                x=float(x),
                y=float(y),
                width=float(w) - kerf_mm,
                height=float(h) - kerf_mm,
                rotated=rotated,
            )
        )

    unplaced: list[str] = []
    for pid, n in added.items():
        unplaced.extend([pid] * (n - placed.get(pid, 0)))

    return NestingResult(
        sheet=sheet,
        placements=placements,
        sheets_used=len(used_bins),
        placed_piece_area_mm2=placed_area,
        unplaced=unplaced,
    )


def utilisation(result: NestingResult) -> float:
    """Fraction of used sheet area covered by real pieces (0..1).

    PT: Área das peças / área das folhas usadas.
    EN: Piece area / used sheet area.
    """
    used_sheet_area = result.sheets_used * result.sheet.area_mm2
    if used_sheet_area <= 0:
        return 0.0
    return result.placed_piece_area_mm2 / used_sheet_area


def demo_order(seed: int = 20260509) -> tuple[list[Piece], Sheet]:
    """Return a deterministic demo order (furniture-style panels) + a sheet.

    PT: Encomenda de demonstração determinística (painéis de mobiliário).
    EN: Deterministic demo order (furniture-style panels).
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    catalogue = [
        ("lateral", 600.0, 1800.0, 2),
        ("prateleira", 560.0, 300.0, 6),
        ("tampo", 900.0, 600.0, 1),
        ("fundo", 900.0, 1800.0, 1),
        ("gaveta-frente", 880.0, 180.0, 4),
        ("gaveta-lateral", 560.0, 180.0, 8),
    ]
    pieces = [
        Piece(id=name, width_mm=w, height_mm=h, quantity=int(qty)) for name, w, h, qty in catalogue
    ]
    # Jitter quantities slightly for variety, staying deterministic.
    pieces = [
        Piece(
            id=p.id,
            width_mm=p.width_mm,
            height_mm=p.height_mm,
            quantity=p.quantity + int(rng.integers(0, 2)),
        )
        for p in pieces
    ]
    sheet = Sheet(width_mm=2800.0, height_mm=2070.0, count=10)  # standard MDF board
    return pieces, sheet
