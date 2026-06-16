"""Synthetic RFQ (request-for-quote) dataset for Recipe 3.

PT: Pedidos de orçamento típicos de uma serralharia / metalomecânica em
Portugal. Texto em PT-PT com variações de tom (formal, WhatsApp, email
curto) e composição de peças. Catálogo de preços associado em
:func:`load_catalogue`. Determinístico com seed.
EN: Typical request-for-quote messages from a Portuguese sheet-metal /
metalwork shop. PT-PT text with varying tone (formal letter, WhatsApp,
short email) and composition of items. Companion price catalogue at
:func:`load_catalogue`. Deterministic with a seed.

The generator exposes two pieces of data:

- A list of :class:`RFQSample` instances with realistic message text plus
  the ground truth of what an extractor should find. Used by tests.
- A pandas DataFrame of price catalogue entries (operation, material,
  unit, price) consumed by the pricing engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

import numpy as np
import pandas as pd

from lib_comum.data_synth.base import DEFAULT_SEED, make_rng

SECTOR: Final[str] = "metalomecanica"

OperationCode = Literal[
    "corte_laser",
    "dobragem",
    "soldadura",
    "furacao",
    "rebarbagem",
    "pintura_epoxy",
    "montagem",
]

MATERIALS: Final[list[str]] = [
    "aço inox 304",
    "aço inox 316L",
    "aço carbono S235",
    "aço carbono S275",
    "alumínio 5754",
    "alumínio 6082",
]


@dataclass(frozen=True, slots=True)
class GroundTruthItem:
    """One canonical line item the extractor should recover from the text.

    PT: Item canónico que o extractor deve recuperar do texto.
    EN: One canonical line item the extractor must recover from the text.
    """

    operation: OperationCode
    material: str
    thickness_mm: float
    quantity: int
    note: str | None = None


@dataclass(frozen=True, slots=True)
class RFQSample:
    """A synthetic RFQ message with its ground-truth line items.

    PT: Mensagem sintética + lista de itens esperados.
    EN: Synthetic message + expected line items.
    """

    rfq_id: str
    channel: Literal["email", "whatsapp", "form"]
    customer: str
    deadline_days: int
    body: str
    items: list[GroundTruthItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Price catalogue
# ---------------------------------------------------------------------------


# Per-operation pricing units and base unit prices. Units are intentionally
# heterogeneous (the manuscript's catalogue is the same way): laser cutting
# is per metre of cut, bending per fold, welding per metre of bead, etc.
PRICING_UNITS: Final[dict[OperationCode, str]] = {
    "corte_laser": "m_cut",
    "dobragem": "fold",
    "soldadura": "m_weld",
    "furacao": "hole",
    "rebarbagem": "minute",
    "pintura_epoxy": "m2",
    "montagem": "hour",
}


def _catalogue_rows() -> list[dict[str, object]]:
    """Build the per-(operation, material, thickness) catalogue table.

    Prices are realistic for PT-PT 2026 small-batch metalwork: laser cutting
    in the €0.50-1.20/m range, single bends at €0.40-1.20, weld bead at
    €4-8/m, epoxy painting around €18-24/m^2.
    """
    rows: list[dict[str, object]] = []

    # Laser cutting prices climb with thickness; stainless costs more.
    laser_prices = {
        "aço inox 304": [(1.0, 0.65), (2.0, 0.80), (3.0, 1.05), (5.0, 1.45)],
        "aço inox 316L": [(1.0, 0.85), (2.0, 1.05), (3.0, 1.30), (5.0, 1.75)],
        "aço carbono S235": [(1.0, 0.50), (2.0, 0.60), (3.0, 0.78), (5.0, 1.05)],
        "aço carbono S275": [(1.0, 0.55), (2.0, 0.65), (3.0, 0.85), (5.0, 1.15)],
        "alumínio 5754": [(1.0, 0.60), (2.0, 0.72), (3.0, 0.92), (5.0, 1.25)],
        "alumínio 6082": [(1.0, 0.62), (2.0, 0.74), (3.0, 0.94), (5.0, 1.30)],
    }
    for material, tiers in laser_prices.items():
        for thickness, price in tiers:
            rows.append(
                {
                    "operation": "corte_laser",
                    "material": material,
                    "thickness_mm": thickness,
                    "unit": "m_cut",
                    "unit_price_eur": price,
                }
            )

    # Bending: per fold, climbs with thickness.
    for material in MATERIALS:
        for thickness, price in [(1.0, 0.45), (2.0, 0.60), (3.0, 0.85), (5.0, 1.20)]:
            rows.append(
                {
                    "operation": "dobragem",
                    "material": material,
                    "thickness_mm": thickness,
                    "unit": "fold",
                    "unit_price_eur": price,
                }
            )

    # Welding: per metre of bead. Stainless costs more (MIG/TIG).
    weld_base = {
        "aço inox 304": 7.20,
        "aço inox 316L": 7.80,
        "aço carbono S235": 4.50,
        "aço carbono S275": 4.80,
        "alumínio 5754": 6.50,
        "alumínio 6082": 6.50,
    }
    for material, price in weld_base.items():
        rows.append(
            {
                "operation": "soldadura",
                "material": material,
                "thickness_mm": None,
                "unit": "m_weld",
                "unit_price_eur": price,
            }
        )

    # Drilling: per hole, flat fee.
    rows.append(
        {
            "operation": "furacao",
            "material": None,
            "thickness_mm": None,
            "unit": "hole",
            "unit_price_eur": 0.35,
        }
    )

    rows.append(
        {
            "operation": "rebarbagem",
            "material": None,
            "thickness_mm": None,
            "unit": "minute",
            "unit_price_eur": 0.55,
        }
    )

    rows.append(
        {
            "operation": "pintura_epoxy",
            "material": None,
            "thickness_mm": None,
            "unit": "m2",
            "unit_price_eur": 22.00,
        }
    )

    rows.append(
        {
            "operation": "montagem",
            "material": None,
            "thickness_mm": None,
            "unit": "hour",
            "unit_price_eur": 35.00,
        }
    )

    return rows


CATALOGUE_COLUMNS: Final[list[str]] = [
    "operation",
    "material",
    "thickness_mm",
    "unit",
    "unit_price_eur",
]


def load_catalogue() -> pd.DataFrame:
    """Return the per-(operation, material, thickness) price catalogue.

    PT: Devolve o catálogo de preços. Determinístico.
    EN: Returns the price catalogue. Deterministic.
    """
    df = pd.DataFrame(_catalogue_rows(), columns=CATALOGUE_COLUMNS)
    df["unit_price_eur"] = df["unit_price_eur"].astype(float)
    return df


# ---------------------------------------------------------------------------
# RFQ messages
# ---------------------------------------------------------------------------


CUSTOMERS: Final[list[str]] = [
    "Metalúrgica Soares Lda.",
    "Construções Almeida & Filhos",
    "Eng. Construção do Norte",
    "Indústria Têxtil do Ave",
    "Auto Componentes Ribatejo",
    "Serralharia Civil Coimbra",
    "Forno Industrial Algarve",
]


# A small set of templates per channel. The generator chooses one and fills
# in the line items in language that mimics how the customer would write them.
EMAIL_FORMAL_TEMPLATE = """Exmos. Senhores,

Vimos por este meio solicitar o vosso melhor orçamento para o fornecimento
abaixo descrito, com entrega num prazo máximo de {deadline_days} dias úteis.

{items_block}

Aguardamos o envio do orçamento detalhado por email.

Com os melhores cumprimentos,
{customer}"""


WHATSAPP_TEMPLATE = (
    "Olá, preciso de um orçamento urgente para:\n{items_block}\n\n"
    "Para entrega em {deadline_days} dias. Obrigado!"
)


FORM_TEMPLATE = """Pedido de orçamento — {customer}
Prazo: {deadline_days} dias

Itens:
{items_block}"""


def _item_phrase(item: GroundTruthItem, channel: str, rng: np.random.Generator) -> str:
    """Render one item in the language a customer would use on *channel*."""
    formal = channel in {"email", "form"}
    if item.operation == "corte_laser":
        verb = "Corte laser" if formal else "corte laser"
        return (
            f"{verb} em {item.material}, espessura {item.thickness_mm:.0f} mm, "
            f"{item.quantity} m de corte"
        )
    if item.operation == "dobragem":
        verb = "Dobragem" if formal else "dobrar"
        return (
            f"{verb} de chapa de {item.material}, espessura {item.thickness_mm:.0f} mm, "
            f"{item.quantity} dobras"
        )
    if item.operation == "soldadura":
        verb = "Soldadura" if formal else "soldar"
        return f"{verb} TIG em {item.material}, {item.quantity} m de cordão"
    if item.operation == "furacao":
        verb = "Furação" if formal else "furos"
        return f"{verb}: {item.quantity} furos"
    if item.operation == "rebarbagem":
        verb = "Rebarbagem" if formal else "rebarbar"
        return f"{verb}: ~{item.quantity} minutos"
    if item.operation == "pintura_epoxy":
        verb = "Pintura epoxy" if formal else "pintar epoxy"
        # rng adds a small visual modifier sometimes for realism
        colour = rng.choice(["RAL 5010", "RAL 7016", "RAL 9005", "RAL 9010"])
        return f"{verb} {colour} em {item.quantity} m²"
    if item.operation == "montagem":
        verb = "Montagem em obra" if formal else "montagem em obra"
        return f"{verb}: {item.quantity} horas"
    return ""


def _format_body(template: str, sample: RFQSample, rng: np.random.Generator) -> str:
    bullets = [f"  - {_item_phrase(item, sample.channel, rng)}" for item in sample.items]
    return template.format(
        deadline_days=sample.deadline_days,
        customer=sample.customer,
        items_block="\n".join(bullets),
    )


def _sample_items(rng: np.random.Generator) -> list[GroundTruthItem]:
    """Pick a realistic combination of line items for one RFQ."""
    n_items = int(rng.integers(2, 5))
    items: list[GroundTruthItem] = []
    operations = list(PRICING_UNITS.keys())
    chosen = rng.choice(operations, size=n_items, replace=False)
    for op in chosen:
        if op in {"corte_laser", "dobragem"}:
            material = str(rng.choice(MATERIALS))
            thickness = float(rng.choice([1.0, 2.0, 3.0, 5.0]))
            quantity = int(rng.integers(5, 60))
        elif op == "soldadura":
            material = str(rng.choice(MATERIALS))
            thickness = 0.0
            quantity = int(rng.integers(2, 15))
        elif op == "furacao":
            material = ""
            thickness = 0.0
            quantity = int(rng.integers(10, 120))
        elif op == "rebarbagem":
            material = ""
            thickness = 0.0
            quantity = int(rng.integers(30, 180))
        elif op == "pintura_epoxy":
            material = ""
            thickness = 0.0
            quantity = int(rng.integers(3, 18))
        elif op == "montagem":
            material = ""
            thickness = 0.0
            quantity = int(rng.integers(2, 16))
        else:  # pragma: no cover — exhaustive above
            continue
        items.append(
            GroundTruthItem(
                operation=op,
                material=material,
                thickness_mm=thickness,
                quantity=quantity,
            )
        )
    return items


def generate_samples(n: int = 12, seed: int = DEFAULT_SEED) -> list[RFQSample]:
    """Generate *n* synthetic RFQ samples with ground truth.

    PT: Gera *n* RFQs sintéticos com ground truth.
    EN: Generates *n* synthetic RFQ samples with ground truth.
    """
    rng = make_rng(seed)
    channels: list[Literal["email", "whatsapp", "form"]] = [
        "email",
        "whatsapp",
        "form",
    ]
    templates = {
        "email": EMAIL_FORMAL_TEMPLATE,
        "whatsapp": WHATSAPP_TEMPLATE,
        "form": FORM_TEMPLATE,
    }
    out: list[RFQSample] = []
    for i in range(n):
        channel = channels[int(rng.integers(0, len(channels)))]
        customer = str(rng.choice(CUSTOMERS))
        deadline = int(rng.integers(7, 30))
        items = _sample_items(rng)
        sample = RFQSample(
            rfq_id=f"RFQ-{seed % 10000:04d}-{i:03d}",
            channel=channel,
            customer=customer,
            deadline_days=deadline,
            body="",
            items=items,
        )
        body = _format_body(templates[channel], sample, rng)
        out.append(
            RFQSample(
                rfq_id=sample.rfq_id,
                channel=sample.channel,
                customer=sample.customer,
                deadline_days=sample.deadline_days,
                body=body,
                items=sample.items,
            )
        )
    return out


def write_catalogue(out_dir: Path) -> Path:
    """Write the catalogue as a CSV under *out_dir* and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_catalogue()
    path = out_dir / "catalogue.csv"
    df.to_csv(path, index=False)
    return path


def write_samples(out_dir: Path, n: int = 12, seed: int = DEFAULT_SEED) -> list[Path]:
    """Write each generated sample to ``out_dir/{rfq_id}.txt``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for sample in generate_samples(n=n, seed=seed):
        path = out_dir / f"{sample.rfq_id}.txt"
        path.write_text(sample.body, encoding="utf-8")
        paths.append(path)
    return paths


if __name__ == "__main__":  # pragma: no cover
    out = Path("receita-3-orcamentista/data-exemplo/metalomecanica")
    print(f"Catalogue: {write_catalogue(out)}")
    paths = write_samples(out)
    print(f"Samples: {len(paths)} written")
