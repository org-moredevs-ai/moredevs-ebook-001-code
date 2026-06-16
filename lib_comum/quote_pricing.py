"""Quote pricing engine for Recipe 3 Tier 1.

PT: Cruzar uma lista de :class:`ExtractedLineItem` com o catálogo de
preços (do gerador :mod:`lib_comum.data_synth.rfq`) e produzir um
:class:`Quote` com totais, IVA e margem.
EN: Cross a list of :class:`ExtractedLineItem` against the price
catalogue (from :mod:`lib_comum.data_synth.rfq`) and produce a
:class:`Quote` with totals, VAT and margin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

import pandas as pd

from lib_comum.llm import ExtractedLineItem

DEFAULT_MARGIN_PCT: Final[float] = 18.0
DEFAULT_VAT_PCT: Final[float] = 23.0


@dataclass(frozen=True, slots=True)
class QuoteLineItem:
    """One priced line item in the final quote."""

    operation: str
    material: str
    thickness_mm: float
    quantity: int
    unit: str
    unit_price_eur: float
    subtotal_eur: float
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Quote:
    """A fully priced quote ready to ship to the customer."""

    rfq_id: str
    customer: str | None
    issued_at: datetime
    items: list[QuoteLineItem]
    subtotal_eur: float
    margin_pct: float
    margin_eur: float
    pre_vat_total_eur: float
    vat_pct: float
    vat_eur: float
    total_eur: float
    deadline_days: int | None
    unresolved_items: list[ExtractedLineItem] = field(default_factory=list)


def _lookup_unit_price(
    catalogue: pd.DataFrame,
    operation: str,
    material: str,
    thickness_mm: float,
) -> tuple[str, float] | None:
    """Look up unit + price for one extracted item.

    The catalogue's match priority is:

    1. Exact (operation, material, thickness_mm).
    2. (operation, material) with closest thickness.
    3. (operation) only, when material/thickness aren't relevant for the row
       (e.g. drilling, painting, assembly).
    """
    df = catalogue
    op_rows = df[df["operation"] == operation]
    if op_rows.empty:
        return None

    # Operations whose pricing doesn't depend on material/thickness.
    if op_rows["material"].isna().all():
        row = op_rows.iloc[0]
        return str(row["unit"]), float(row["unit_price_eur"])

    material_rows = op_rows[op_rows["material"] == material] if material else op_rows
    if material_rows.empty:
        material_rows = op_rows  # graceful fallback to other materials

    # Operations whose pricing has thickness tiers.
    if material_rows["thickness_mm"].notna().any() and thickness_mm > 0:
        # Pick the row with the closest thickness.
        thickness_rows = material_rows.dropna(subset=["thickness_mm"]).copy()
        thickness_rows["_delta"] = (thickness_rows["thickness_mm"] - thickness_mm).abs()
        row = thickness_rows.sort_values("_delta").iloc[0]
    else:
        row = material_rows.iloc[0]

    return str(row["unit"]), float(row["unit_price_eur"])


def price_quote(
    *,
    items: list[ExtractedLineItem],
    catalogue: pd.DataFrame,
    rfq_id: str,
    customer: str | None,
    deadline_days: int | None,
    margin_pct: float = DEFAULT_MARGIN_PCT,
    vat_pct: float = DEFAULT_VAT_PCT,
    issued_at: datetime | None = None,
) -> Quote:
    """Apply the catalogue to *items* and return a :class:`Quote`.

    PT: Aplica o catálogo aos itens. Devolve o orçamento totalizado.
    EN: Applies the catalogue to *items*. Returns the totalled quote.
    """
    priced: list[QuoteLineItem] = []
    unresolved: list[ExtractedLineItem] = []
    subtotal = 0.0
    for item in items:
        lookup = _lookup_unit_price(catalogue, item.operation, item.material, item.thickness_mm)
        if lookup is None or item.quantity <= 0:
            unresolved.append(item)
            continue
        unit, price = lookup
        line_subtotal = round(price * item.quantity, 2)
        subtotal = round(subtotal + line_subtotal, 2)
        priced.append(
            QuoteLineItem(
                operation=item.operation,
                material=item.material,
                thickness_mm=item.thickness_mm,
                quantity=item.quantity,
                unit=unit,
                unit_price_eur=price,
                subtotal_eur=line_subtotal,
                note=item.note,
            )
        )
    margin_eur = round(subtotal * margin_pct / 100.0, 2)
    pre_vat = round(subtotal + margin_eur, 2)
    vat_eur = round(pre_vat * vat_pct / 100.0, 2)
    total = round(pre_vat + vat_eur, 2)
    return Quote(
        rfq_id=rfq_id,
        customer=customer,
        issued_at=issued_at or datetime.now(UTC),
        items=priced,
        subtotal_eur=subtotal,
        margin_pct=margin_pct,
        margin_eur=margin_eur,
        pre_vat_total_eur=pre_vat,
        vat_pct=vat_pct,
        vat_eur=vat_eur,
        total_eur=total,
        deadline_days=deadline_days,
        unresolved_items=unresolved,
    )


def render_quote_text(quote: Quote) -> str:
    """Render the quote as plain text — easy to email or paste into a PDF.

    PT: Renderiza o orçamento em texto simples.
    EN: Renders the quote as plain text.
    """
    lines: list[str] = []
    lines.append(f"Orçamento {quote.rfq_id}")
    lines.append(f"Cliente: {quote.customer or '(não identificado)'}")
    lines.append(f"Data: {quote.issued_at:%Y-%m-%d %H:%M UTC}")
    if quote.deadline_days is not None:
        lines.append(f"Prazo solicitado: {quote.deadline_days} dias")
    lines.append("")
    lines.append(
        f"{'Operação':<18} {'Material':<22} {'Esp.':>6} {'Qtd':>6} {'Unit.':>8} {'Subtotal':>10}"
    )
    lines.append("-" * 76)
    for item in quote.items:
        lines.append(
            f"{item.operation:<18} {item.material:<22} "
            f"{item.thickness_mm:>6.1f} {item.quantity:>6} "
            f"{item.unit_price_eur:>8.2f} {item.subtotal_eur:>10.2f}"
        )
    lines.append("-" * 76)
    lines.append(f"{'Subtotal':>62}: €{quote.subtotal_eur:>9.2f}")
    lines.append(f"{'Margem':>62}: €{quote.margin_eur:>9.2f} ({quote.margin_pct:.0f}%)")
    lines.append(f"{'Antes de IVA':>62}: €{quote.pre_vat_total_eur:>9.2f}")
    lines.append(f"{'IVA':>62}: €{quote.vat_eur:>9.2f} ({quote.vat_pct:.0f}%)")
    lines.append(f"{'TOTAL':>62}: €{quote.total_eur:>9.2f}")
    if quote.unresolved_items:
        lines.append("")
        lines.append("Itens por classificar (revisão humana):")
        for entry in quote.unresolved_items:
            lines.append(
                f"  - {entry.operation or '(?)'} | {entry.material or '(material?)'}"
                f" | qty={entry.quantity}"
            )
    return "\n".join(lines)
