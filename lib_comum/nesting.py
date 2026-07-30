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


@dataclass(frozen=True, slots=True)
class ManualStats:
    """Outcome of scoring a hand-made layout (drag-and-drop game)."""

    utilisation: float
    valid_indices: list[int]  # pieces inside the sheet and not overlapping
    invalid_indices: list[int]  # pieces off the sheet or overlapping another


def _aabb_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    tol: float = 1.0,
) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw <= bx + tol or bx + bw <= ax + tol or ay + ah <= by + tol or by + bh <= ay + tol
    )


def manual_placement_stats(
    rects: list[tuple[float, float, float, float]],
    sheet: Sheet,
) -> ManualStats:
    """Score a hand-made layout: which pieces are validly placed, and the area used.

    PT: Cada peça é ``(x, y, largura, altura)`` em mm numa folha. Uma peça só
    conta para o aproveitamento se estiver **dentro** da folha e **sem se
    sobrepor** a outra — as sobreposições e as peças fora não contam, como no
    corte real. Serve o jogo "coloca tu vs o computador".
    EN: Each piece is ``(x, y, width, height)`` in mm on a sheet. A piece counts
    towards utilisation only if it is **inside** the sheet and does **not
    overlap** another — overlaps and off-sheet pieces do not count, as in a real
    cut. Powers the "place it yourself vs the computer" game.
    """
    w_sheet, h_sheet = sheet.width_mm, sheet.height_mm
    tol = 1.0
    inside = [
        (x >= -tol and y >= -tol and x + w <= w_sheet + tol and y + h <= h_sheet + tol)
        for (x, y, w, h) in rects
    ]
    valid: list[int] = []
    invalid: list[int] = []
    for i, rect in enumerate(rects):
        if not inside[i]:
            invalid.append(i)
            continue
        overlaps = any(
            j != i and inside[j] and _aabb_overlap(rect, rects[j]) for j in range(len(rects))
        )
        (invalid if overlaps else valid).append(i)
    used_area = sum(rects[i][2] * rects[i][3] for i in valid)
    sheet_area = w_sheet * h_sheet
    util = used_area / sheet_area if sheet_area > 0 else 0.0
    return ManualStats(utilisation=util, valid_indices=valid, invalid_indices=invalid)


def pack_naive(
    pieces: list[Piece],
    sheet: Sheet,
    *,
    kerf_mm: float = 3.0,
) -> NestingResult:
    """Pack pieces the naive way: left-to-right in rows, no sorting, no rotation.

    PT: A disposição "à mão" — coloca as peças por filas, na ordem dada, sem
    rodar nem ordenar por tamanho, abrindo uma folha nova quando a actual
    esgota. Serve de linha de base para mostrar quanto a heurística de
    ``pack_rectangles`` melhora o aproveitamento (e poupa folhas).
    EN: The by-hand layout — places pieces in rows, in input order, without
    rotating or sorting by size, opening a new sheet when the current one fills
    up. A baseline that shows how much pack_rectangles lifts utilisation (and
    saves whole sheets).
    """
    placements: list[Placement] = []
    area_by_id = {p.id: p.area_mm2 for p in pieces}
    placed_area = 0.0
    unplaced: list[str] = []

    max_sheets = max(1, sheet.count)
    sheet_index = 0
    cursor_x = 0.0
    cursor_y = 0.0
    shelf_h = 0.0

    for piece in pieces:
        w = piece.width_mm + kerf_mm
        h = piece.height_mm + kerf_mm
        for _ in range(piece.quantity):
            if w > sheet.width_mm or h > sheet.height_mm:
                unplaced.append(piece.id)  # bigger than any sheet
                continue
            if cursor_x + w > sheet.width_mm:  # row full → next row
                cursor_x = 0.0
                cursor_y += shelf_h
                shelf_h = 0.0
            if cursor_y + h > sheet.height_mm:  # sheet full → next sheet
                sheet_index += 1
                cursor_x = 0.0
                cursor_y = 0.0
                shelf_h = 0.0
            if sheet_index >= max_sheets:  # ran out of stock sheets
                unplaced.append(piece.id)
                continue
            placements.append(
                Placement(
                    piece_id=piece.id,
                    sheet_index=sheet_index,
                    x=cursor_x,
                    y=cursor_y,
                    width=piece.width_mm,
                    height=piece.height_mm,
                    rotated=False,
                )
            )
            placed_area += area_by_id.get(piece.id, 0.0)
            cursor_x += w
            shelf_h = max(shelf_h, h)

    used_bins = {p.sheet_index for p in placements}
    return NestingResult(
        sheet=sheet,
        placements=placements,
        sheets_used=len(used_bins),
        placed_piece_area_mm2=placed_area,
        unplaced=unplaced,
    )


def demo_order() -> tuple[list[Piece], Sheet]:
    """Return a deterministic demo order (wardrobe panels) + a stock sheet.

    PT: Encomenda de demonstração (painéis de um guarda-roupa), escolhida para o
    encaixe optimizado dar ~90% de aproveitamento em 3 folhas, contra ~54% e 5
    folhas na disposição ingénua — e para a rotação fazer diferença (sem
    rotação sobe para 4 folhas). São os números que o leitor vê em ``demo-r4``.
    EN: Deterministic demo order (wardrobe panels), tuned so the optimised
    packing reaches ~90% utilisation on 3 sheets versus ~54% and 5 sheets for
    the naive layout — and so rotation matters (without it, 4 sheets are
    needed). These are the numbers the reader sees in ``demo-r4``.
    """
    catalogue = [
        ("lateral", 600.0, 2000.0, 4),
        ("prateleira", 864.0, 400.0, 8),
        ("tampo", 1200.0, 600.0, 2),
        ("porta", 596.0, 1960.0, 3),
        ("gaveta-frente", 560.0, 180.0, 10),
        ("divisoria", 564.0, 1960.0, 2),
    ]
    pieces = [
        Piece(id=name, width_mm=w, height_mm=h, quantity=qty) for name, w, h, qty in catalogue
    ]
    sheet = Sheet(width_mm=2800.0, height_mm=2070.0, count=10)  # standard MDF board
    return pieces, sheet
