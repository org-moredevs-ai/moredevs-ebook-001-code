"""Recipe 4 — nesting tests (rectangular + irregular), deterministic, no I/O.

PT: Testa o encaixe rectangular (rectpack) e o irregular (rasterização com grão
e zonas de defeito) de forma determinística.
EN: Tests rectangular (rectpack) and irregular (raster with grain and defect
zones) nesting deterministically.
"""

from __future__ import annotations

import itertools

from lib_comum.nesting import (
    Placement,
    Sheet,
    demo_order,
    manual_placement_stats,
    pack_naive,
    pack_rectangles,
    utilisation,
)
from lib_comum.nesting_irregular import (
    IrregularSheet,
    _point_in_polygon,
    _polygons_overlap,
    demo_irregular_order,
    game_computer_solution,
    game_leather_order,
    manual_irregular_stats,
    place_irregular,
    polygon_area,
)


def _square(x: float, y: float, side: float) -> list[tuple[float, float]]:
    return [(x, y), (x + side, y), (x + side, y + side), (x, y + side)]


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


def test_pack_naive_is_valid_and_no_overlap() -> None:
    pieces, sheet = demo_order()
    result = pack_naive(pieces, sheet, kerf_mm=3.0)
    assert result.sheets_used >= 1
    assert 0.0 < utilisation(result) <= 1.0
    by_sheet: dict[int, list[Placement]] = {}
    for placement in result.placements:
        by_sheet.setdefault(placement.sheet_index, []).append(placement)
    for placements in by_sheet.values():
        for a, b in itertools.combinations(placements, 2):
            assert not _overlap(a, b)


def test_heuristic_beats_naive_on_the_demo_order() -> None:
    """The teaching claim: rectpack lifts utilisation over the by-hand baseline."""
    pieces, sheet = demo_order()
    naive = pack_naive(pieces, sheet, kerf_mm=3.0)
    smart = pack_rectangles(pieces, sheet, kerf_mm=3.0)
    assert utilisation(smart) >= utilisation(naive)
    assert smart.sheets_used <= naive.sheets_used


def test_manual_stats_scores_valid_non_overlapping_pieces() -> None:
    sheet = Sheet(width_mm=1000.0, height_mm=1000.0, count=1)
    # two 400x400 side by side (no overlap, inside) -> both valid
    rects = [(0.0, 0.0, 400.0, 400.0), (500.0, 0.0, 400.0, 400.0)]
    stats = manual_placement_stats(rects, sheet)
    assert stats.valid_indices == [0, 1]
    assert stats.invalid_indices == []
    assert abs(stats.utilisation - (2 * 400 * 400) / (1000 * 1000)) < 1e-9


def test_manual_stats_flags_overlap_and_off_sheet() -> None:
    sheet = Sheet(width_mm=1000.0, height_mm=1000.0, count=1)
    rects = [
        (0.0, 0.0, 400.0, 400.0),  # 0: overlaps 1
        (200.0, 200.0, 400.0, 400.0),  # 1: overlaps 0
        (900.0, 900.0, 400.0, 400.0),  # 2: off the sheet
    ]
    stats = manual_placement_stats(rects, sheet)
    assert set(stats.invalid_indices) == {0, 1, 2}
    assert stats.valid_indices == []
    assert stats.utilisation == 0.0


def test_polygon_area_of_rectangle() -> None:
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)]
    assert abs(polygon_area(square) - 50.0) < 1e-6


def test_polygons_overlap_detects_intersection() -> None:
    assert _polygons_overlap(_square(0, 0, 100), _square(50, 50, 100))
    assert not _polygons_overlap(_square(0, 0, 100), _square(200, 0, 100))


def test_manual_irregular_stats_scores_valid_pieces() -> None:
    sheet = IrregularSheet(width_mm=1000.0, height_mm=1000.0)
    polys = [_square(0, 0, 200), _square(400, 0, 200)]
    stats = manual_irregular_stats(polys, sheet)
    assert stats.valid_indices == [0, 1]
    assert stats.invalid_indices == []
    assert abs(stats.utilisation - (2 * 200 * 200) / (1000 * 1000)) < 1e-6


def test_manual_irregular_stats_flags_overlap_defect_and_off_sheet() -> None:
    sheet = IrregularSheet(width_mm=1000.0, height_mm=1000.0)
    defect = _square(600, 600, 100)
    polys = [
        _square(0, 0, 200),  # 0: overlaps 1
        _square(100, 100, 200),  # 1: overlaps 0
        _square(620, 620, 60),  # 2: overlaps the defect
        _square(950, 950, 200),  # 3: off the sheet
        _square(400, 0, 150),  # 4: clean -> valid
    ]
    stats = manual_irregular_stats(polys, sheet, defects=(defect,))
    assert stats.valid_indices == [4]
    assert set(stats.invalid_indices) == {0, 1, 2, 3}


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


def test_game_leather_order_is_genuine_overflow() -> None:
    """The game is over-full: even the near-optimal packing leaves a part out.

    If every part fit, a rule-following human would tie the computer. Here not
    even the strong opponent fits all 10, so *how many* you fit is what counts.
    """
    pieces, _sheet, _defect = game_leather_order()
    best = game_computer_solution()
    assert len(best.unplaced) > 0  # not even the best layout fits all -> overflow
    assert len(best.placements) < len(pieces)


def test_game_computer_beats_greedy_and_scores_valid() -> None:
    """The opponent must pack clearly more than greedy bottom-left, and be valid.

    A thoughtful human beats the greedy heuristic, so the game's computer replays
    a random-restart solution that packs more — hard to match by hand.
    """
    pieces, sheet, defect = game_leather_order()
    greedy = place_irregular(pieces, sheet, allowed_angles=(0.0, 180.0), defects=(defect,))
    smart = game_computer_solution()
    assert len(smart.placements) > len(greedy.placements)  # random-restart > greedy
    assert smart.utilisation > greedy.utilisation
    # The computer's layout must score as fully valid under the game's referee.
    stats = manual_irregular_stats(
        [pl.polygon for pl in smart.placements], sheet, defects=(defect,)
    )
    assert stats.invalid_indices == []
    assert abs(stats.utilisation - smart.utilisation) < 1e-6


def test_grain_constraint_limits_rotation_angles() -> None:
    pieces, sheet, defects = demo_irregular_order()
    result = place_irregular(pieces, sheet, allowed_angles=(0.0, 180.0), defects=defects)
    for placement in result.placements:
        assert placement.angle in (0.0, 180.0)
