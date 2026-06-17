"""Recipe 4 Tier 1 — SVG visualisation of a nesting layout.

PT: Desenha o resultado do encaixe num SVG que o operador pode ver e validar
antes de levar para a máquina de corte. Empilha as várias folhas usadas e
inverte o eixo Y (o *nesting* tem origem em baixo-à-esquerda; o SVG em cima).
EN: Draws the nesting result as an SVG the operator can review before sending it
to the cutting machine. Stacks the used sheets and flips the Y axis (nesting
has a bottom-left origin; SVG a top-left one).
"""

from __future__ import annotations

import svgwrite

from lib_comum.nesting import NestingResult
from lib_comum.nesting_irregular import IrregularResult, Polygon

_PALETTE = ("#cfe8ff", "#ffe0b2", "#c8e6c9", "#f8bbd0", "#d1c4e9", "#b2dfdb")


def _colour(piece_id: str, seen: dict[str, str]) -> str:
    if piece_id not in seen:
        seen[piece_id] = _PALETTE[len(seen) % len(_PALETTE)]
    return seen[piece_id]


def _build(
    result: NestingResult, *, scale: float = 0.1, margin_mm: float = 40.0
) -> svgwrite.Drawing:
    sheet = result.sheet
    n_sheets = max(1, result.sheets_used)
    total_w = sheet.width_mm
    total_h = n_sheets * sheet.height_mm + (n_sheets - 1) * margin_mm
    dwg = svgwrite.Drawing(
        size=(f"{total_w * scale}px", f"{total_h * scale}px"),
        viewBox=f"0 0 {total_w} {total_h}",
    )
    for s in range(n_sheets):
        block_top = s * (sheet.height_mm + margin_mm)
        dwg.add(
            dwg.rect(
                (0, block_top),
                (sheet.width_mm, sheet.height_mm),
                fill="white",
                stroke="black",
                stroke_width=4,
            )
        )
    seen: dict[str, str] = {}
    for placement in result.placements:
        block_top = placement.sheet_index * (sheet.height_mm + margin_mm)
        # Flip Y: nesting origin is bottom-left, SVG origin is top-left.
        svg_y = block_top + (sheet.height_mm - placement.y - placement.height)
        dwg.add(
            dwg.rect(
                (placement.x, svg_y),
                (placement.width, placement.height),
                fill=_colour(placement.piece_id, seen),
                stroke="#1e40af",
                stroke_width=2,
            )
        )
    return dwg


def render_svg(result: NestingResult, path: str, *, scale: float = 0.1) -> None:
    """Write the layout SVG to *path*.

    PT: Escreve o SVG do encaixe no caminho indicado.
    EN: Writes the nesting SVG to the given path.
    """
    _build(result, scale=scale).saveas(path)


def svg_string(result: NestingResult, *, scale: float = 0.1) -> str:
    """Return the layout SVG as a string (for inline display in Streamlit).

    PT: Devolve o SVG como string.
    EN: Returns the SVG as a string.
    """
    return str(_build(result, scale=scale).tostring())


def irregular_svg_string(
    result: IrregularResult,
    *,
    defects: tuple[Polygon, ...] = (),
    scale: float = 0.4,
) -> str:
    """Return an SVG string for an irregular nesting result (with defects).

    PT: Devolve o SVG do encaixe irregular, com as zonas de defeito a vermelho.
    EN: Returns the SVG for an irregular nesting result, defects in red.
    """
    sheet = result.sheet
    dwg = svgwrite.Drawing(
        size=(f"{sheet.width_mm * scale}px", f"{sheet.height_mm * scale}px"),
        viewBox=f"0 0 {sheet.width_mm} {sheet.height_mm}",
    )
    dwg.add(
        dwg.rect(
            (0, 0), (sheet.width_mm, sheet.height_mm), fill="white", stroke="black", stroke_width=4
        )
    )
    for defect in defects:
        pts = [(x, sheet.height_mm - y) for x, y in defect]
        dwg.add(dwg.polygon(pts, fill="#ffcdd2", stroke="#c62828", stroke_width=2))
    seen: dict[str, str] = {}
    for placement in result.placements:
        pts = [(x, sheet.height_mm - y) for x, y in placement.polygon]
        dwg.add(
            dwg.polygon(
                pts,
                fill=_colour(placement.piece_id, seen),
                stroke="#1e40af",
                stroke_width=2,
            )
        )
    return str(dwg.tostring())
