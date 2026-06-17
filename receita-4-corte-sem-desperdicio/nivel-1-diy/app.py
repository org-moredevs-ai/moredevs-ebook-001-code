"""Recipe 4 — Streamlit nesting UI (rectangular Tier 1 + irregular Tier 2).

PT: Mostra o encaixe a desenhar-se e o aproveitamento ao vivo. O separador
rectangular usa ``rectpack`` (Nível 1); o irregular usa o encaixe por
rasterização com grão e zonas de defeito (Nível 2). Corre com ``streamlit run``.
EN: Shows the nesting layout and live utilisation. The rectangular tab uses
``rectpack`` (Tier 1); the irregular tab uses raster nesting with grain and
defect zones (Tier 2). Run with ``streamlit run``.
"""

from __future__ import annotations

import streamlit as st
from svg_render import irregular_svg_string, svg_string

from lib_comum.nesting import demo_order, pack_rectangles, utilisation
from lib_comum.nesting_irregular import demo_irregular_order, place_irregular

st.set_page_config(page_title="Corte sem desperdício", page_icon="✂️", layout="wide")
st.title("✂️ Corte sem desperdício — encaixe de peças")

rect_tab, irregular_tab = st.tabs(["Rectangular (Nível 1)", "Irregular (Nível 2)"])

with rect_tab:
    st.caption("Painéis rectangulares numa chapa/placa (MDF, vidro, chapa simples).")
    kerf = st.slider("Largura de corte / kerf (mm)", 0.0, 10.0, 3.0, 0.5)
    rotate = st.checkbox("Permitir rotação 90°", value=True)
    pieces, sheet = demo_order()
    result = pack_rectangles(pieces, sheet, kerf_mm=kerf, allow_rotation=rotate)
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.metric("Aproveitamento", f"{utilisation(result) * 100:.1f}%")
        st.metric("Folhas usadas", result.sheets_used)
        st.metric("Peças encaixadas", len(result.placements))
        if result.unplaced:
            st.warning(f"Por encaixar: {len(result.unplaced)}")
    with col_b:
        st.components.v1.html(svg_string(result), height=520, scrolling=True)

with irregular_tab:
    st.caption("Peças irregulares (pele, tecido) com grão e zonas de defeito.")
    grain = st.checkbox("Respeitar grão (só rotações 0°/180°)", value=True)
    spacing = st.slider("Espaçamento entre peças (mm)", 0.0, 8.0, 2.0, 0.5)
    angles = (0.0, 180.0) if grain else (0.0, 90.0, 180.0, 270.0)
    ir_pieces, ir_sheet, defects = demo_irregular_order()
    ir_result = place_irregular(
        ir_pieces, ir_sheet, allowed_angles=angles, defects=defects, spacing_mm=spacing
    )
    col_c, col_d = st.columns([1, 2])
    with col_c:
        st.metric("Aproveitamento", f"{ir_result.utilisation * 100:.1f}%")
        st.metric("Peças encaixadas", len(ir_result.placements))
        if ir_result.unplaced:
            st.warning(f"Por encaixar: {len(ir_result.unplaced)}")
        st.caption("A zona a vermelho é um defeito a evitar.")
    with col_d:
        st.components.v1.html(
            irregular_svg_string(ir_result, defects=defects), height=520, scrolling=True
        )
