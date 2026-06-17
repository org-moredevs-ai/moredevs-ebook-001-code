"""Recipe 3 Tier 2 — read an RFQ from a PDF (text layer; vision-ready).

PT: Extrai o texto embutido de um PDF (com ``pypdf``) e passa-o ao *provider* de
extracção. Para PDFs que são imagens (desenhos digitalizados), usa-se um
*provider* com visão que aceita as páginas como imagens — o caminho de texto
abaixo cobre os PDFs com camada de texto e o modo *offline*.
EN: Extracts a PDF's embedded text (via ``pypdf``) and feeds it to the
extraction provider. For image-only PDFs (scanned drawings) use a vision-capable
provider that accepts page images — the text path below covers text-layer PDFs
and the offline mode.

Run with::

    uv run python receita-3-orcamentista/nivel-2-pro/vision/pdf_extract.py path/to/rfq.pdf
"""

from __future__ import annotations

import sys
from pathlib import Path

from lib_comum.llm import LLMProvider, RfqExtraction, make_provider


def extract_text_from_pdf(path: str | Path) -> str:
    """Return the concatenated text layer of *path*.

    PT: Devolve a camada de texto do PDF. Requer o extra ``receita-3``.
    EN: Returns the PDF's text layer. Requires the ``receita-3`` extra.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "pypdf is required: install the receita-3 extra (uv sync --extra receita-3)."
        ) from exc
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def extract_rfq_from_pdf(path: str | Path, provider: LLMProvider) -> RfqExtraction:
    """Extract a structured RFQ from *path* via *provider*.

    PT: Extrai o pedido estruturado de um PDF.
    EN: Extracts a structured RFQ from a PDF.
    """
    text = extract_text_from_pdf(path)
    return provider.extract_rfq(text)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: pdf_extract.py path/to/rfq.pdf")
        return 2
    provider = make_provider()
    extraction = extract_rfq_from_pdf(args[0], provider)
    print(f"provider={extraction.provider} items={len(extraction.items)}")
    for item in extraction.items:
        print(
            f"  - {item.operation} | {item.material} | {item.thickness_mm}mm | qty={item.quantity}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
