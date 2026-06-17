"""Recipe 4 — nesting tests (rectangular + irregular), deterministic, no I/O.

PT: Testa o encaixe rectangular (rectpack) e o irregular (rasterização com grão
e zonas de defeito) de forma determinística.
EN: Tests rectangular (rectpack) and irregular (raster with grain and defect
zones) nesting deterministically.
"""

from __future__ import annotations

import itertools

from lib_comum.nesting import Placement, demo_order, pack_rectangles, utilisation
from lib_comum.nesting_irregular import (
    _point_in_polygon,
    demo_irregular_order,
    place_irregular,
    polygon_area,
)


def _overlap(a: Placement, b: Placement) -> bool:
    return not (
        a.x + a.width <= b.x
        or b.x + b.width <= a.x
        or a.y + a.height <= b.y
        or b.y + b.height <= a.y
    )


def test_pack_rectangles_places_all_demo_pieces() -> None:
    pieces, sheet = demo_order()
    result = pack_rectangles(pieces, sheet, kerf_mm=3.0)
    assert result.unplaced == []
    assert result.sheets_used >= 1
    assert 0.0 < utilisation(result) <= 1.0


def test_pack_rectangles_no_overlap_within_a_sheet() -> None:
    pieces, sheet = demo_order()
    result = pack_rectangles(pieces, sheet, kerf_mm=3.0)
    by_sheet: dict[int, list[Placement]] = {}
    for placement in result.placements:
        by_sheet.setdefault(placement.sheet_index, []).append(placement)
    for placements in by_sheet.values():
        for a, b in itertools.combinations(placements, 2):
            assert not _overlap(a, b)


def test_more_kerf_never_improves_utilisation() -> None:
    pieces, sheet = demo_order()
    low_kerf = utilisation(pack_rectangles(pieces, sheet, kerf_mm=0.0))
    high_kerf = utilisation(pack_rectangles(pieces, sheet, kerf_mm=8.0))
    assert high_kerf <= low_kerf + 1e-9


def test_polygon_area_of_rectangle() -> None:
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)]
    assert abs(polygon_area(square) - 50.0) < 1e-6


def test_place_irregular_places_pieces_and_avoids_defects() -> None:
    pieces, sheet, defects = demo_irregular_order()
    result = place_irregular(pieces, sheet, defects=defects, spacing_mm=2.0, raster_mm=5.0)
    assert len(result.placements) >= 1
    assert 0.0 < result.utilisation <= 1.0
    for placement in result.placements:
        cx = sum(p[0] for p in placement.polygon) / len(placement.polygon)
        cy = sum(p[1] for p in placement.polygon) / len(placement.polygon)
        for defect in defects:
            assert not _point_in_polygon(cx, cy, defect)


def test_grain_constraint_limits_rotation_angles() -> None:
    pieces, sheet, defects = demo_irregular_order()
    result = place_irregular(pieces, sheet, allowed_angles=(0.0, 180.0), defects=defects)
    for placement in result.placements:
        assert placement.angle in (0.0, 180.0)
