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


def demo_irregular_order(
    seed: int = 20260509,
) -> tuple[list[IrregularPiece], IrregularSheet, tuple[Polygon, ...]]:
    """Return a deterministic irregular order: pieces, sheet and a defect zone.

    PT: Encomenda irregular de demonstração (peças, folha e zona de defeito).
    EN: Deterministic irregular demo order (pieces, sheet and a defect zone).
    """
    rng = np.random.default_rng(seed)

    def _rect(w: float, h: float) -> Polygon:
        return [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]

    def _l_shape(w: float, h: float, cut: float) -> Polygon:
        return [(0.0, 0.0), (w, 0.0), (w, h - cut), (w - cut, h - cut), (w - cut, h), (0.0, h)]

    def _triangle(w: float, h: float) -> Polygon:
        return [(0.0, 0.0), (w, 0.0), (w / 2.0, h)]

    pieces = [
        IrregularPiece("painel", _rect(360.0, 240.0), quantity=2),
        IrregularPiece("cunha", _triangle(260.0, 200.0), quantity=3),
        IrregularPiece("ele", _l_shape(300.0, 300.0, 140.0), quantity=2),
        IrregularPiece("tira", _rect(120.0, 420.0), quantity=int(2 + rng.integers(0, 2))),
    ]
    sheet = IrregularSheet(width_mm=1200.0, height_mm=900.0)
    # A defect zone to avoid (e.g. a scar in the leather / oxidised patch).
    defect: Polygon = [(700.0, 100.0), (820.0, 100.0), (820.0, 220.0), (700.0, 220.0)]
    return pieces, sheet, (defect,)
