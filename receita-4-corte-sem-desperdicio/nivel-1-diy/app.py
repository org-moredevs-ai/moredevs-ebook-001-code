"""Recipe 4 — Streamlit nesting UI (rectangular Tier 1 + irregular Tier 2).

PT: Demonstração interactiva do encaixe. O leitor edita as peças (quais, quantas,
dimensões), a matéria-prima e o corte, e carrega em "Encaixar sem desperdício"
para o computador re-arrumar — vendo o aproveitamento subir face à disposição
ingénua (à mão) e as folhas descerem. O separador rectangular usa ``rectpack``
(Nível 1); o irregular usa o encaixe por rasterização com grão e zonas de
defeito (Nível 2). Corre com ``streamlit run`` (``make demo-r4``).
EN: Interactive nesting demo. The reader edits the pieces (which, how many, size),
the stock and the cut, then clicks "Nest without waste" to let the computer
re-arrange — watching utilisation rise over the naive (by-hand) layout and the
sheet count fall. The rectangular tab uses ``rectpack`` (Tier 1); the irregular
tab uses raster nesting with grain and defect zones (Tier 2).
"""

from __future__ import annotations

import math
import time

import pandas as pd
import streamlit as st
from streamlit_drawable_canvas import st_canvas
from svg_render import irregular_svg_string, svg_string

from lib_comum.nesting import (
    Piece,
    Sheet,
    demo_order,
    pack_naive,
    pack_rectangles,
    utilisation,
)
from lib_comum.nesting_irregular import (
    IrregularPiece,
    Polygon,
    demo_irregular_order,
    game_computer_solution,
    game_leather_order,
    manual_irregular_stats,
    place_irregular,
)

st.set_page_config(page_title="Corte sem desperdício", page_icon="✂️", layout="wide")
st.title("✂️ Corte sem desperdício — encaixe de peças")

rect_tab, irregular_tab, game_tab = st.tabs(
    ["Rectangular (Nível 1)", "Irregular (Nível 2)", "🎮 Tu vs o computador"]
)


# ---------------------------------------------------------------------------
# Rectangular tab
# ---------------------------------------------------------------------------


def _rect_pieces(df: pd.DataFrame) -> list[Piece]:
    """Build the list of pieces to cut from the edited table (skip excluded/invalid)."""
    pieces: list[Piece] = []
    for _, row in df.iterrows():
        if not bool(row.get("incluir", False)):
            continue
        try:
            w = float(row["largura_mm"])
            h = float(row["altura_mm"])
            qty = int(row["qtd"])
        except (TypeError, ValueError):
            continue
        name = str(row.get("peça") or "peça").strip() or "peça"
        if w > 0 and h > 0 and qty > 0:
            pieces.append(Piece(id=name, width_mm=w, height_mm=h, quantity=qty))
    return pieces


def _default_rect_df() -> pd.DataFrame:
    pieces, _ = demo_order()
    return pd.DataFrame(
        [
            {
                "incluir": True,
                "peça": p.id,
                "largura_mm": p.width_mm,
                "altura_mm": p.height_mm,
                "qtd": p.quantity,
            }
            for p in pieces
        ]
    )


with rect_tab:
    st.caption("Painéis rectangulares numa chapa/placa (MDF, vidro, chapa simples).")

    st.markdown("##### 1. As peças a cortar — inclua, exclua, mude dimensões e quantidades")
    edited = st.data_editor(
        _default_rect_df(),
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="rect_pieces",
        column_config={
            "incluir": st.column_config.CheckboxColumn("incluir", default=True),
            "peça": st.column_config.TextColumn("peça"),
            "largura_mm": st.column_config.NumberColumn("largura (mm)", min_value=1, step=10),
            "altura_mm": st.column_config.NumberColumn("altura (mm)", min_value=1, step=10),
            "qtd": st.column_config.NumberColumn("qtd", min_value=1, step=1),
        },
    )

    st.markdown("##### 2. A matéria-prima e o corte")
    c1, c2, c3 = st.columns(3)
    sheet_w = c1.number_input("Folha — largura (mm)", 100.0, 6000.0, 2800.0, 10.0)
    sheet_h = c2.number_input("Folha — altura (mm)", 100.0, 6000.0, 2070.0, 10.0)
    sheet_n = c3.number_input("Folhas disponíveis", 1, 50, 10, 1)
    c4, c5, c6 = st.columns(3)
    kerf = c4.slider("Largura de corte / kerf (mm)", 0.0, 10.0, 3.0, 0.5)
    rotate = c5.checkbox("Permitir rotação 90°", value=True)
    annual = c6.number_input("Custo anual de material (€)", 0, 2_000_000, 200_000, 10_000)
    sheet = Sheet(width_mm=sheet_w, height_mm=sheet_h, count=int(sheet_n))

    if st.button("✂️ Encaixar sem desperdício", type="primary", use_container_width=True):
        st.session_state["r4_packed"] = True

    st.divider()
    pieces = _rect_pieces(edited)
    if not pieces:
        st.info("Marque **incluir** em pelo menos uma peça para encaixar.")
    elif not st.session_state.get("r4_packed"):
        naive = pack_naive(pieces, sheet, kerf_mm=kerf)
        left, right = st.columns([1, 2])
        with left:
            st.markdown("#### 🖐️ Como ficaria à mão")
            st.metric("Aproveitamento", f"{utilisation(naive) * 100:.1f}%")
            st.metric("Folhas usadas", naive.sheets_used)
            st.caption("Carregue em **✂️ Encaixar sem desperdício** para o computador re-arrumar.")
        with right:
            st.components.v1.html(svg_string(naive), height=460, scrolling=True)
    else:
        naive = pack_naive(pieces, sheet, kerf_mm=kerf)
        smart = pack_rectangles(pieces, sheet, kerf_mm=kerf, allow_rotation=rotate)
        u_naive, u_smart = utilisation(naive), utilisation(smart)
        pp = (u_smart - u_naive) * 100
        saved = pp * annual * 0.01

        left, right = st.columns([1, 2])
        with left:
            m1, m2 = st.columns(2)
            with m1:
                st.markdown("**🖐️ Ingénua**")
                st.metric("Aproveitamento", f"{u_naive * 100:.1f}%")
                st.metric("Folhas", naive.sheets_used)
            with m2:
                st.markdown("**✂️ Sem desperdício**")
                st.metric("Aproveitamento", f"{u_smart * 100:.1f}%", delta=f"{pp:+.1f} pontos")
                st.metric(
                    "Folhas",
                    smart.sheets_used,
                    delta=f"{smart.sheets_used - naive.sheets_used:+d}",
                    delta_color="inverse",
                )
            if smart.unplaced:
                st.warning(f"Por encaixar: {len(smart.unplaced)} — some folhas ou reduza peças.")
            if pp > 0:
                st.success(
                    f"Cada ponto percentual vale €{annual * 0.01:,.0f}/ano. "
                    f"Ganhou {pp:.1f} pontos → **€{saved:,.0f}/ano** face à disposição ingénua."
                )
        with right:
            view = st.radio(
                "Ver disposição", ["Optimizada", "Ingénua"], horizontal=True, key="rect_view"
            )
            shown = smart if view == "Optimizada" else naive
            st.components.v1.html(svg_string(shown), height=460, scrolling=True)


# ---------------------------------------------------------------------------
# Irregular tab
# ---------------------------------------------------------------------------


def _default_irregular_df() -> pd.DataFrame:
    base, _, _ = demo_irregular_order()
    return pd.DataFrame([{"incluir": True, "peça": p.id, "qtd": p.quantity} for p in base])


with irregular_tab:
    st.caption("Peças irregulares (pele, tecido) com grão e zonas de defeito.")
    base_pieces, ir_sheet, _ = demo_irregular_order()
    poly_by_id: dict[str, Polygon] = {p.id: p.polygon for p in base_pieces}

    st.markdown("##### 1. As peças (formas fixas) — inclua/exclua e escolha as quantidades")
    edited_ir = st.data_editor(
        _default_irregular_df(),
        hide_index=True,
        use_container_width=True,
        key="ir_pieces",
        column_config={
            "incluir": st.column_config.CheckboxColumn("incluir", default=True),
            "peça": st.column_config.TextColumn("peça", disabled=True),
            "qtd": st.column_config.NumberColumn("qtd", min_value=1, step=1),
        },
    )

    st.markdown("##### 2. Grão, espaçamento e zona de defeito")
    g1, g2 = st.columns(2)
    grain = g1.checkbox("Respeitar grão (só rotações 0°/180°)", value=True)
    spacing = g2.slider("Espaçamento entre peças (mm)", 0.0, 8.0, 2.0, 0.5)
    angles = (0.0, 180.0) if grain else (0.0, 90.0, 180.0, 270.0)

    use_defect = st.checkbox("Evitar uma zona de defeito", value=True)
    defects: tuple[Polygon, ...] = ()
    if use_defect:
        d1, d2, d3, d4 = st.columns(4)
        dx = d1.slider("Defeito — X (mm)", 0, int(ir_sheet.width_mm), 700, 10)
        dy = d2.slider("Defeito — Y (mm)", 0, int(ir_sheet.height_mm), 100, 10)
        dw = d3.slider("Defeito — largura (mm)", 20, 500, 120, 10)
        dh = d4.slider("Defeito — altura (mm)", 20, 500, 120, 10)
        defects = (
            [
                (float(dx), float(dy)),
                (float(dx + dw), float(dy)),
                (float(dx + dw), float(dy + dh)),
                (float(dx), float(dy + dh)),
            ],
        )

    if st.button("✂️ Encaixar (irregular)", type="primary", use_container_width=True):
        st.session_state["r4_ir_packed"] = True

    st.divider()
    ir_pieces = [
        IrregularPiece(
            id=str(row["peça"]), polygon=poly_by_id[str(row["peça"])], quantity=int(row["qtd"])
        )
        for _, row in edited_ir.iterrows()
        if bool(row.get("incluir", False))
        and str(row["peça"]) in poly_by_id
        and int(row["qtd"]) > 0
    ]
    if not ir_pieces:
        st.info("Marque **incluir** em pelo menos uma peça para encaixar.")
    elif not st.session_state.get("r4_ir_packed"):
        st.caption(
            "Carregue em **✂️ Encaixar (irregular)** para colocar as formas verdadeiras, "
            "respeitando o grão e evitando o defeito."
        )
    else:
        result = place_irregular(
            ir_pieces, ir_sheet, allowed_angles=angles, defects=defects, spacing_mm=spacing
        )
        left, right = st.columns([1, 2])
        with left:
            st.metric("Aproveitamento da pele", f"{result.utilisation * 100:.1f}%")
            st.metric("Peças encaixadas", len(result.placements))
            if result.unplaced:
                st.caption(f"↳ {len(result.unplaced)} por encaixar — a pele está cheia.")
            st.caption(
                "A zona a vermelho é um defeito a evitar. "
                "Ligue/desligue **respeitar grão** e compare o aproveitamento — "
                "o grão custa material, mas é obrigatório no tecido e na pele."
            )
            st.info(
                "O encaixe *bottom-left* (Nível 2) satura por volta dos **60-65%** em "
                "formas curvas — é ganancioso: cada peça vai para o canto mais baixo e "
                "nunca mais se mexe, deixando folgas entre as curvas. Os **~85-90%** que "
                "uma fábrica atinge são o **Nível 3**: metaheurísticas (No-Fit Polygon + "
                "*simulated annealing*) que re-arranjam e interligam as peças."
            )
        with right:
            st.components.v1.html(
                irregular_svg_string(result, defects=defects), height=460, scrolling=True
            )


# ---------------------------------------------------------------------------
# Game tab — place the curved leather parts yourself, then let the computer win
# ---------------------------------------------------------------------------

_GAME_PIECES, _GAME_HIDE, _GAME_DEFECT = game_leather_order()  # 1 mm == 1 px here
_GAME_COLOURS: dict[str, tuple[str, str]] = {
    "gáspea": ("rgba(207,232,255,0.85)", "#1e40af"),
    "traseiro": ("rgba(255,224,178,0.85)", "#b45309"),
    "biqueira": ("rgba(200,230,201,0.85)", "#2e7d32"),
}
# Initial (left, top) in px == mm — piled and overlapping so the reader must sort them.
_GAME_START: list[tuple[int, int]] = [
    (8, 8),
    (28, 28),
    (48, 48),
    (68, 68),
    (250, 8),
    (270, 38),
    (290, 68),
    (20, 390),
    (48, 405),
    (76, 420),
]


def _fmt_secs(seconds: float) -> str:
    """Human-readable duration: '0.3s', '42s', or '3m 12s'."""
    if seconds < 1.0:
        return f"{seconds:.1f}s"
    if seconds < 60.0:
        return f"{seconds:.0f}s"
    return f"{int(seconds // 60)}m {round(seconds % 60):02d}s"


def _game_initial_drawing() -> dict:
    objects: list[dict] = []
    for piece, (left, top) in zip(_GAME_PIECES, _GAME_START, strict=True):
        fill, stroke = _GAME_COLOURS[piece.id]
        objects.append(
            {
                "type": "polygon",
                "points": [{"x": x, "y": y} for x, y in piece.polygon],
                "left": left,
                "top": top,
                "fill": fill,
                "stroke": stroke,
                "strokeWidth": 2,
                "lockScalingX": True,  # size is fixed — only move and rotate
                "lockScalingY": True,
                "lockRotation": False,  # the reader may rotate the part
                "hasControls": True,
                "hasBorders": True,
            }
        )
    # The scar to avoid: fixed — cannot be selected, moved or transformed.
    objects.append(
        {
            "type": "polygon",
            "points": [{"x": x, "y": y} for x, y in _GAME_DEFECT],
            "left": _GAME_DEFECT[0][0],
            "top": _GAME_DEFECT[0][1],
            "fill": "rgba(255,205,210,0.75)",
            "stroke": "#c62828",
            "strokeWidth": 2,
            "selectable": False,
            "evented": False,
            "lockMovementX": True,
            "lockMovementY": True,
            "hasControls": False,
        }
    )
    return {"version": "4.4.0", "objects": objects}


with game_tab:
    st.caption(
        "Encaixe o **máximo de peças de calçado** que conseguir nesta pele, **sem se "
        "sobreporem e sem tocar na cicatriz** (a vermelho). Arraste-as e **rode-as** pela "
        "pega de cima (o tamanho não muda). **São mais peças do que cabem** — o segredo "
        "é encaixá-las bem. O computador testa milhares de disposições e mete mais do "
        "que uma pessoa consegue à mão — **quantas mete você?** A solução dele só aparece "
        "**depois** do botão (e a sua pontuação trava nesse momento)."
    )
    canvas_w = round(_GAME_HIDE.width_mm)
    canvas_h = round(_GAME_HIDE.height_mm)
    # drawable-canvas 0.9.3 does not size its iframe on recent Streamlit (the frame
    # collapses to 0 px); pin the height so the hide stays visible.
    st.markdown(
        f'<style>iframe[title="streamlit_drawable_canvas.st_canvas"]'
        f"{{height:{canvas_h + 30}px !important;}}</style>",
        unsafe_allow_html=True,
    )
    round_n = st.session_state.get("r4_round", 0)
    board_col, score_col = st.columns([2, 1])
    with board_col:
        canvas = st_canvas(
            fill_color="rgba(207,232,255,0.85)",
            stroke_width=2,
            background_color="#ffffff",
            width=canvas_w,
            height=canvas_h,
            drawing_mode="transform",
            initial_drawing=_game_initial_drawing(),
            update_streamlit=True,
            key=f"game_canvas_{round_n}",
        )

    # Rebuild each piece's polygon at its TRUE shape from the canvas *position and
    # rotation only* (never its scaling), so resizing cannot shrink a part to cheat:
    #   absolute = (left, top) + R(angle) . point   (verified against the canvas).
    # The last canvas object is the fixed scar, which the zip over _GAME_PIECES drops.
    objects = canvas.json_data.get("objects") if canvas.json_data else None
    if not objects:
        objects = _game_initial_drawing()["objects"]
    placed: list[Polygon] = []
    for piece, o in zip(_GAME_PIECES, objects, strict=False):
        left, top = float(o.get("left", 0)), float(o.get("top", 0))
        rad = math.radians(float(o.get("angle", 0)))
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        placed.append(
            [
                (left + px * cos_a - py * sin_a, top + px * sin_a + py * cos_a)
                for px, py in piece.polygon
            ]
        )
    live = manual_irregular_stats(placed, _GAME_HIDE, defects=(_GAME_DEFECT,))

    # Start the stopwatch on the first canvas interaction of this round (json_data
    # only appears once the reader has actually moved a part).
    if canvas.json_data is not None:
        st.session_state.setdefault(f"r4_start_{round_n}", time.time())

    # Freeze the score AND the elapsed time at submit, so seeing the computer's answer
    # can't be copied. "Tentar de novo" scatters the parts again (new canvas).
    submitted = "r4_submit" in st.session_state
    sub = st.session_state.get("r4_submit")
    you_util = sub["you_util"] if submitted else live.utilisation
    you_valid = sub["you_valid"] if submitted else len(live.valid_indices)
    total = len(_GAME_PIECES)

    with score_col:
        st.metric("O teu aproveitamento", f"{you_util * 100:.1f}%")
        st.metric("Peças bem cortadas", f"{you_valid} / {total}")
        if not submitted and live.invalid_indices:
            st.caption(
                f"↳ {len(live.invalid_indices)} sobrepõem-se, saem da pele ou tocam na "
                "cicatriz — não contam."
            )
        annual = st.number_input("Custo anual de pele (€)", 0, 2_000_000, 200_000, 10_000)
        if not submitted:
            if st.button(
                "🤖 Deixa o computador encaixar", type="primary", use_container_width=True
            ):
                start = st.session_state.get(f"r4_start_{round_n}", time.time())
                t0 = time.perf_counter()
                comp_result = game_computer_solution()
                st.session_state["r4_submit"] = {
                    "you_util": live.utilisation,
                    "you_valid": len(live.valid_indices),
                    "elapsed": max(0.0, time.time() - start),
                    "comp": comp_result,
                    "comp_time": time.perf_counter() - t0,
                }
                st.rerun()
        elif st.button("🔄 Tentar de novo", use_container_width=True):
            st.session_state["r4_round"] = round_n + 1
            del st.session_state["r4_submit"]
            st.rerun()

    if submitted and sub is not None:
        st.divider()
        comp = sub["comp"]
        comp_util = comp.utilisation
        gap_pp = max(0.0, (comp_util - you_util) * 100.0)
        you_secs, comp_secs = sub["elapsed"], sub["comp_time"]
        speedup = you_secs / comp_secs if comp_secs > 0 else 0.0
        left_c, right_c = st.columns([1, 2])
        with left_c:
            st.markdown("#### 🤖 O computador")
            st.metric(
                "Aproveitamento",
                f"{comp_util * 100:.1f}%",
                delta=f"{(comp_util - you_util) * 100:+.1f} pontos vs ti",
            )
            st.metric("Peças na pele", f"{len(comp.placements)} / {total}")
            if you_util >= comp_util:
                st.success(
                    f"Igualaste ou bateste o computador — {you_util * 100:.1f}%! "
                    "Poucos conseguem à mão. 🏆"
                )
            else:
                waste = gap_pp * annual * 0.01
                st.warning(
                    f"O computador meteu **{len(comp.placements)} peças** ({comp_util * 100:.1f}%); "
                    f"tu **{you_valid}** ({you_util * 100:.1f}%). São **{gap_pp:.1f} pontos** de "
                    f"aproveitamento — a €{annual * 0.01:,.0f}/ponto, **€{waste:,.0f}/ano** de pele "
                    "a mais no lixo."
                )
            st.info(
                f"⏱️ Demoraste **{_fmt_secs(you_secs)}** a arrumar à mão; o computador "
                f"**{_fmt_secs(comp_secs)}**"
                + (f" — cerca de **{speedup:,.0f}x mais rápido**." if speedup >= 2 else ".")
            )
        with right_c:
            st.caption("O encaixe do computador (mais peças na mesma pele):")
            st.components.v1.html(
                irregular_svg_string(comp, defects=(_GAME_DEFECT,)),
                height=canvas_h + 20,
                scrolling=True,
            )
