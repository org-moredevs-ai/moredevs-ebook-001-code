"""Recipe 4 Tier 2 — irregular nesting with grain and defect zones.

PT: Encaixa polígonos irregulares numa folha respeitando o **grão** (apenas
certas rotações permitidas) e evitando **zonas de defeito**. Usa uma variante
por rasterização do *bottom-left*: discretiza a folha numa grelha, infla cada
peça por *spacing* (com ``pyclipper``) e coloca-a na posição mais baixa e mais à
esquerda onde cabe sem chocar com outra peça nem com um defeito.

EN: Nests irregular polygons into a sheet while honouring the **grain** (only
certain rotations allowed) and avoiding **defect zones**. Uses a raster variant
of bottom-left placement: discretises the sheet into a grid, inflates each piece
by *spacing* (with ``pyclipper``) and drops it into the lowest, left-most spot
where it overlaps neither a placed piece nor a defect.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pyclipper

Polygon = list[tuple[float, float]]


@dataclass(frozen=True, slots=True)
class IrregularPiece:
    """An irregular piece given by its polygon (mm), to cut *quantity* times."""

    id: str
    polygon: Polygon
    quantity: int = 1


@dataclass(frozen=True, slots=True)
class IrregularSheet:
    """Stock sheet dimensions (a single sheet/roll segment)."""

    width_mm: float
    height_mm: float


@dataclass(frozen=True, slots=True)
class IrregularPlacement:
    """A placed piece: bbox origin (x, y), rotation, and absolute polygon."""

    piece_id: str
    x: float
    y: float
    angle: float
    polygon: Polygon


@dataclass(frozen=True, slots=True)
class IrregularResult:
    """Outcome of an irregular nesting run."""

    sheet: IrregularSheet
    placements: list[IrregularPlacement]
    utilisation: float
    unplaced: list[str]


def polygon_area(polygon: Polygon) -> float:
    """Shoelace area (absolute) of *polygon*."""
    n = len(polygon)
    acc = 0.0
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        acc += x1 * y2 - x2 * y1
    return abs(acc) / 2.0


def _rotate(polygon: Polygon, angle_deg: float) -> Polygon:
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return [(x * cos_a - y * sin_a, x * sin_a + y * cos_a) for x, y in polygon]


def _bbox(polygon: Polygon) -> tuple[float, float, float, float]:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _translate(polygon: Polygon, dx: float, dy: float) -> Polygon:
    return [(x + dx, y + dy) for x, y in polygon]


def _offset(polygon: Polygon, delta_mm: float) -> Polygon:
    """Outward polygon offset by *delta_mm* using pyclipper (for spacing/kerf)."""
    if delta_mm <= 0.0:
        return list(polygon)
    scale = 1000.0
    pco = pyclipper.PyclipperOffset()
    path = [(round(x * scale), round(y * scale)) for x, y in polygon]
    pco.AddPath(path, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    solution = pco.Execute(delta_mm * scale)
    if not solution:
        return list(polygon)
    return [(x / scale, y / scale) for x, y in solution[0]]


def _point_in_polygon(px: float, py: float, polygon: Polygon) -> bool:
    """Ray-casting point-in-polygon test."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _mask_cells(polygon: Polygon, raster_mm: float) -> tuple[list[tuple[int, int]], int, int]:
    """Rasterise *polygon* (with bbox at origin) into occupied (row, col) cells."""
    _, _, maxx, maxy = _bbox(polygon)
    cols = max(1, math.ceil(maxx / raster_mm))
    rows = max(1, math.ceil(maxy / raster_mm))
    cells: list[tuple[int, int]] = []
    for r in range(rows):
        cy = (r + 0.5) * raster_mm
        for c in range(cols):
            cx = (c + 0.5) * raster_mm
            if _point_in_polygon(cx, cy, polygon):
                cells.append((r, c))
    return cells, rows, cols


@dataclass(frozen=True, slots=True)
class _Prepared:
    cells: list[tuple[int, int]]
    rows: int
    cols: int
    draw_polygon: Polygon


def _prepare(polygon: Polygon, angle: float, spacing_mm: float, raster_mm: float) -> _Prepared:
    rotated = _rotate(polygon, angle)
    inflated = _offset(rotated, spacing_mm)
    minx, miny, _, _ = _bbox(inflated)
    norm_inflated = _translate(inflated, -minx, -miny)
    norm_draw = _translate(rotated, -minx, -miny)
    cells, rows, cols = _mask_cells(norm_inflated, raster_mm)
    return _Prepared(cells=cells, rows=rows, cols=cols, draw_polygon=norm_draw)


def _block_polygon(grid: np.ndarray, polygon: Polygon, raster_mm: float) -> None:
    rows, cols = grid.shape
    minx, miny, maxx, maxy = _bbox(polygon)
    r0 = max(0, int(miny // raster_mm))
    r1 = min(rows, int(maxy // raster_mm) + 1)
    c0 = max(0, int(minx // raster_mm))
    c1 = min(cols, int(maxx // raster_mm) + 1)
    for r in range(r0, r1):
        cy = (r + 0.5) * raster_mm
        for c in range(c0, c1):
            cx = (c + 0.5) * raster_mm
            if _point_in_polygon(cx, cy, polygon):
                grid[r, c] = True


def place_irregular(
    pieces: list[IrregularPiece],
    sheet: IrregularSheet,
    *,
    allowed_angles: tuple[float, ...] = (0.0, 180.0),
    defects: tuple[Polygon, ...] = (),
    spacing_mm: float = 2.0,
    raster_mm: float = 5.0,
) -> IrregularResult:
    """Bottom-left raster nesting for irregular polygons.

    PT: Para cada peça (maior primeiro) tenta cada rotação permitida e varre a
    folha de baixo-à-esquerda até à primeira posição livre (sem chocar com peças
    nem defeitos). As rotações permitidas codificam o grão.
    EN: For each piece (largest first) tries each allowed rotation and scans the
    sheet bottom-left for the first free position (no overlap with pieces or
    defects). Allowed rotations encode the grain.
    """
    rows = int(sheet.height_mm // raster_mm)
    cols = int(sheet.width_mm // raster_mm)
    grid = np.zeros((rows, cols), dtype=bool)
    for defect in defects:
        _block_polygon(grid, defect, raster_mm)

    instances: list[IrregularPiece] = []
    for piece in pieces:
        instances.extend([piece] * piece.quantity)
    instances.sort(key=lambda p: polygon_area(p.polygon), reverse=True)

    placements: list[IrregularPlacement] = []
    unplaced: list[str] = []
    placed_area = 0.0

    for piece in instances:
        spot = _first_fit(grid, piece, allowed_angles, spacing_mm, raster_mm)
        if spot is None:
            unplaced.append(piece.id)
            continue
        placement, occupied = spot
        placements.append(placement)
        for r, c in occupied:
            grid[r, c] = True
        placed_area += polygon_area(piece.polygon)

    sheet_area = sheet.width_mm * sheet.height_mm
    util = placed_area / sheet_area if sheet_area > 0 else 0.0
    return IrregularResult(sheet=sheet, placements=placements, utilisation=util, unplaced=unplaced)


def _first_fit(
    grid: np.ndarray,
    piece: IrregularPiece,
    allowed_angles: tuple[float, ...],
    spacing_mm: float,
    raster_mm: float,
) -> tuple[IrregularPlacement, list[tuple[int, int]]] | None:
    rows, cols = grid.shape
    for angle in allowed_angles:
        prep = _prepare(piece.polygon, angle, spacing_mm, raster_mm)
        if not prep.cells:
            continue
        for base_r in range(rows - prep.rows + 1):
            for base_c in range(cols - prep.cols + 1):
                if all(not grid[base_r + r, base_c + c] for r, c in prep.cells):
                    px = base_c * raster_mm
                    py = base_r * raster_mm
                    abs_poly = _translate(prep.draw_polygon, px, py)
                    placement = IrregularPlacement(
                        piece_id=piece.id, x=px, y=py, angle=angle, polygon=abs_poly
                    )
                    occupied = [(base_r + r, base_c + c) for r, c in prep.cells]
                    return placement, occupied
    return None


def _normalise(polygon: Polygon) -> Polygon:
    """Shift a polygon so its bounding box starts at the origin."""
    minx = min(x for x, _ in polygon)
    miny = min(y for _, y in polygon)
    return [(x - minx, y - miny) for x, y in polygon]


def _egg(width: float, height: float, back: float = 0.62, n: int = 26) -> Polygon:
    """Asymmetric oval: rounded toe, tapered heel — a shoe vamp (gáspea)."""
    pts: Polygon = []
    for i in range(n):
        t = 2.0 * math.pi * i / n
        cos_t = math.cos(t)
        rx = (width / 2.0) * (1.0 if cos_t >= 0.0 else back)  # taper the heel side
        pts.append((rx * cos_t, (height / 2.0) * math.sin(t)))
    return _normalise(pts)


def _dome(width: float, height: float, n: int = 16) -> Polygon:
    """Half-oval with a flat base — a toe cap (biqueira)."""
    pts: Polygon = [
        (
            (width / 2.0) * (1.0 + math.cos(math.pi * i / (n - 1))),
            height * math.sin(math.pi * i / (n - 1)),
        )
        for i in range(n)
    ]
    return _normalise(pts)


def _tongue(width: float, height: float, n: int = 12) -> Polygon:
    """Straight sides with a rounded top — a shoe tongue (lingueta)."""
    r = width / 2.0
    arc: Polygon = [
        (
            r + r * math.cos(math.pi * i / (n - 1)),
            (height - r) + r * math.sin(math.pi * i / (n - 1)),
        )
        for i in range(n)
    ]
    return _normalise([(0.0, 0.0), (width, 0.0), *arc])


def _crescent(width: float, height: float, dip: float, n: int = 18) -> Polygon:
    """Curved band: concave top, gently convex bottom — a quarter/heel counter."""
    top: Polygon = [
        (width * i / (n - 1), height - dip * math.sin(math.pi * i / (n - 1))) for i in range(n)
    ]
    bottom: Polygon = [
        (width * i / (n - 1), (dip * 0.4) * math.sin(math.pi * i / (n - 1))) for i in range(n)
    ]
    return _normalise([*top, *bottom[::-1]])


def demo_irregular_order() -> tuple[list[IrregularPiece], IrregularSheet, tuple[Polygon, ...]]:
    """Return a deterministic order of footwear pattern pieces from a hide.

    PT: Peças de calçado a cortar de um segmento de pele — gáspea, traseiro,
    biqueira, lingueta e contraforte —, com uma cicatriz a evitar. As formas
    são curvas e assimétricas, como as verdadeiras peças de um sapato, ao
    contrário de rectângulos. É o caso de campo da cena de abertura.
    EN: Footwear pattern pieces to cut from a leather segment — vamp, quarter,
    toe cap, tongue and heel counter — with a scar to avoid. The shapes are
    curved and asymmetric, like real shoe parts, not rectangles. It is the
    field case from the opening scene.
    """
    # Quantities chosen so the hide fills to the raster nester's ceiling (~58%):
    # 34 of 35 parts fit — one more will not — so the utilisation reflects real
    # packing quality, not just "how many parts we asked for".
    pieces = [
        IrregularPiece("gáspea", _egg(300.0, 175.0), quantity=7),
        IrregularPiece("traseiro", _crescent(280.0, 150.0, 78.0), quantity=7),
        IrregularPiece("biqueira", _dome(150.0, 95.0), quantity=7),
        IrregularPiece("lingueta", _tongue(95.0, 165.0), quantity=7),
        IrregularPiece("contraforte", _crescent(150.0, 120.0, 62.0), quantity=7),
    ]
    sheet = IrregularSheet(width_mm=1200.0, height_mm=900.0)
    # A scar in the leather to avoid (the reader can move it in the demo).
    defect: Polygon = [(700.0, 100.0), (820.0, 100.0), (820.0, 220.0), (700.0, 220.0)]
    return pieces, sheet, (defect,)


def place_in_order(
    ordered_pieces: list[IrregularPiece],
    sheet: IrregularSheet,
    *,
    allowed_angles: tuple[float, ...] = (0.0, 180.0),
    defects: tuple[Polygon, ...] = (),
    spacing_mm: float = 2.0,
    raster_mm: float = 5.0,
) -> IrregularResult:
    """Bottom-left raster nesting that places pieces in the **given** order.

    PT: Como :func:`place_irregular`, mas sem ordenar por área — coloca na ordem
    recebida. Serve para experimentar muitas ordens numa procura por reinícios
    aleatórios (o "computador" do jogo replay uma ordem pré-encontrada).
    EN: Like :func:`place_irregular` but without the largest-first sort — places
    in the order given. Lets a random-restart search try many orders (the game's
    "computer" replays a pre-found best order).
    """
    rows = int(sheet.height_mm // raster_mm)
    cols = int(sheet.width_mm // raster_mm)
    grid = np.zeros((rows, cols), dtype=bool)
    for defect in defects:
        _block_polygon(grid, defect, raster_mm)

    placements: list[IrregularPlacement] = []
    unplaced: list[str] = []
    placed_area = 0.0
    for piece in ordered_pieces:
        spot = _first_fit(grid, piece, allowed_angles, spacing_mm, raster_mm)
        if spot is None:
            unplaced.append(piece.id)
            continue
        placement, occupied = spot
        placements.append(placement)
        for r, c in occupied:
            grid[r, c] = True
        placed_area += polygon_area(piece.polygon)

    sheet_area = sheet.width_mm * sheet.height_mm
    util = placed_area / sheet_area if sheet_area > 0 else 0.0
    return IrregularResult(sheet=sheet, placements=placements, utilisation=util, unplaced=unplaced)


def game_leather_order() -> tuple[list[IrregularPiece], IrregularSheet, Polygon]:
    """An *over-full* footwear order for the "place it yourself" game.

    PT: 10 peças curvas — **mais do que cabem** numa pele com uma cicatriz. Nem o
    óptimo as encaixa todas: o melhor arranjo mete 9 (~66%); o bottom-left
    ganancioso só 7 (~55%); à mão fica-se ainda mais abaixo. O que conta não é
    "sem sobrepor" (isso empataria), é *quantas* peças se conseguem lá meter — e
    encaixar 9 formas curvas exige testar milhares de disposições. Fácil para o
    computador, difícil para a pessoa. Índices 0-3 são gáspeas, 4-6 traseiros,
    7-9 biqueiras (a ordem importa para :data:`_GAME_BEST_ORDER`).
    EN: 10 curved parts — **more than fit** in one hide with a scar. Not even the
    optimum fits them all: the best layout packs 9 (~66%), greedy bottom-left
    only 7 (~55%), and by hand you land lower still. What counts is not "no
    overlap" (that would tie) but *how many* parts you fit — and fitting 9 curved
    shapes needs thousands of trials. Easy for the computer, hard for a person.
    """
    pieces = [
        IrregularPiece("gáspea", _egg(300.0, 175.0), 1),
        IrregularPiece("gáspea", _egg(300.0, 175.0), 1),
        IrregularPiece("gáspea", _egg(300.0, 175.0), 1),
        IrregularPiece("gáspea", _egg(300.0, 175.0), 1),
        IrregularPiece("traseiro", _crescent(280.0, 150.0, 78.0), 1),
        IrregularPiece("traseiro", _crescent(280.0, 150.0, 78.0), 1),
        IrregularPiece("traseiro", _crescent(280.0, 150.0, 78.0), 1),
        IrregularPiece("biqueira", _dome(150.0, 95.0), 1),
        IrregularPiece("biqueira", _dome(150.0, 95.0), 1),
        IrregularPiece("biqueira", _dome(150.0, 95.0), 1),
    ]
    sheet = IrregularSheet(580.0, 520.0)
    defect: Polygon = [(300.0, 210.0), (410.0, 210.0), (410.0, 300.0), (300.0, 300.0)]
    return pieces, sheet, defect


# Placement order found offline by a random-restart search (see the r4 test): it
# lets the raster nester fit 9 of the 10 game parts (~66%), far above greedy
# largest-first (~55%). Replaying it is instant, so the game needs no live search.
_GAME_BEST_ORDER: tuple[int, ...] = (3, 2, 6, 9, 7, 0, 4, 5, 1, 8)


def game_computer_solution() -> IrregularResult:
    """The computer's near-optimal packing of the game order — computed instantly.

    PT: Replay da melhor ordem pré-encontrada — o "adversário" forte do jogo, que
    uma pessoa dificilmente iguala à mão.
    EN: Replays the pre-found best order — the game's strong opponent, which a
    person can rarely match by hand.
    """
    pieces, sheet, defect = game_leather_order()
    ordered = [pieces[i] for i in _GAME_BEST_ORDER]
    return place_in_order(
        ordered,
        sheet,
        allowed_angles=(0.0, 90.0, 180.0, 270.0),
        defects=(defect,),
        spacing_mm=2.0,
        raster_mm=5.0,
    )


@dataclass(frozen=True, slots=True)
class ManualIrregularStats:
    """Outcome of scoring a hand-made irregular layout (drag-and-drop game)."""

    utilisation: float
    valid_indices: list[int]  # inside the hide, not overlapping a piece or the defect
    invalid_indices: list[int]


def _polygons_overlap(a: Polygon, b: Polygon, tol_area_mm2: float = 1.0) -> bool:
    """True if polygons *a* and *b* share more than *tol_area_mm2* of area."""
    scale = 100.0
    clipper = pyclipper.Pyclipper()
    clipper.AddPath(
        [(round(x * scale), round(y * scale)) for x, y in a], pyclipper.PT_SUBJECT, True
    )
    clipper.AddPath([(round(x * scale), round(y * scale)) for x, y in b], pyclipper.PT_CLIP, True)
    solution = clipper.Execute(
        pyclipper.CT_INTERSECTION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO
    )
    if not solution:
        return False
    area = sum(abs(pyclipper.Area(path)) for path in solution) / (scale * scale)
    return bool(area > tol_area_mm2)


def manual_irregular_stats(
    polygons: list[Polygon],
    sheet: IrregularSheet,
    defects: tuple[Polygon, ...] = (),
) -> ManualIrregularStats:
    """Score a hand-made leather layout of *polygons* (already placed, in mm).

    PT: Uma peça só conta para o aproveitamento se estiver **dentro** da pele e
    **sem se sobrepor** a outra peça nem a um defeito (cicatriz). As formas são
    curvas — muito mais difíceis de arrumar à mão do que rectângulos. Serve o
    jogo "coloca tu vs o computador" no cenário de calçado.
    EN: A piece counts towards utilisation only if it is **inside** the hide and
    does **not overlap** another piece or a defect (scar). The shapes are curved
    — far harder to arrange by hand than rectangles. Powers the "place it
    yourself vs the computer" game in the footwear scenario.
    """
    w_sheet, h_sheet = sheet.width_mm, sheet.height_mm
    tol = 1.0
    inside = [
        all(-tol <= x <= w_sheet + tol and -tol <= y <= h_sheet + tol for x, y in poly)
        for poly in polygons
    ]
    valid: list[int] = []
    invalid: list[int] = []
    for i, poly in enumerate(polygons):
        if not inside[i]:
            invalid.append(i)
            continue
        hits_defect = any(_polygons_overlap(poly, defect) for defect in defects)
        hits_piece = any(
            j != i and inside[j] and _polygons_overlap(poly, polygons[j])
            for j in range(len(polygons))
        )
        (invalid if (hits_defect or hits_piece) else valid).append(i)
    used_area = sum(polygon_area(polygons[i]) for i in valid)
    sheet_area = w_sheet * h_sheet
    util = used_area / sheet_area if sheet_area > 0 else 0.0
    return ManualIrregularStats(utilisation=util, valid_indices=valid, invalid_indices=invalid)
