"""Recipe 3 Tier 2 — vector memory of approved quotes.

PT: Índice vectorial de orçamentos aprovados. Cada orçamento é guardado com um
*embedding* do texto do pedido, para que um pedido novo possa recuperar os mais
parecidos do passado — mantendo coerência de preços e apanhando erros de
extracção que produzem totais fora do intervalo razoável.

O *backend* incluído é leve e puro Python (cosseno sobre *embeddings* de
*bag-of-words* com *hashing*), determinístico e sem descarregar modelos — corre
em qualquer máquina. A mesma interface (``add_quote`` / ``find_similar``) é a de
um vector DB, pelo que se troca por chromadb em produção sem mudar o resto.

EN: Vector index of approved quotes. Each quote is stored with an embedding of
its RFQ text so a new RFQ can retrieve the most similar past quotes — keeping
pricing consistent and catching extraction errors that yield out-of-range
totals. The bundled backend is a lightweight, pure-Python cosine over hashed
bag-of-words embeddings: deterministic, no model downloads, runs anywhere. The
``add_quote`` / ``find_similar`` interface mirrors a vector DB, so it swaps for
chromadb in production without touching the rest.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import numpy as np

from lib_comum.quote_pricing import Quote

EMBED_DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def embed(text: str, dim: int = EMBED_DIM) -> np.ndarray:
    """Return an L2-normalised hashed bag-of-words embedding of *text*.

    PT: Embedding determinístico, sem dependências externas nem downloads.
    EN: Deterministic embedding, no external dependencies or downloads.
    """
    vec = np.zeros(dim, dtype=np.float64)
    for token in _TOKEN_RE.findall(text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        vec[int.from_bytes(digest, "big") % dim] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm > 0.0:
        vec /= norm
    return vec


@dataclass(frozen=True, slots=True)
class SimilarQuote:
    """A past quote retrieved by similarity to a new RFQ."""

    rfq_id: str
    body: str
    total_eur: float
    similarity: float


@dataclass(slots=True)
class _Entry:
    rfq_id: str
    body: str
    total_eur: float
    embedding: np.ndarray


@dataclass(slots=True)
class QuoteMemory:
    """In-process vector index of approved quotes (chromadb-compatible).

    PT: Índice vectorial de orçamentos aprovados.
    EN: Vector index of approved quotes.
    """

    dim: int = EMBED_DIM
    _entries: list[_Entry] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self._entries)

    def add_quote(self, rfq_id: str, body: str, quote: Quote) -> None:
        """Store one approved quote keyed by its RFQ text.

        PT: Guarda um orçamento aprovado, indexado pelo texto do pedido.
        EN: Stores one approved quote, indexed by its RFQ text.
        """
        self._entries.append(
            _Entry(
                rfq_id=rfq_id,
                body=body,
                total_eur=quote.total_eur,
                embedding=embed(body, self.dim),
            )
        )

    def find_similar(self, body: str, k: int = 3) -> list[SimilarQuote]:
        """Return the *k* most similar past quotes to *body* (cosine, desc).

        PT: Devolve os *k* orçamentos passados mais parecidos com *body*.
        EN: Returns the *k* most similar past quotes to *body*.
        """
        if not self._entries:
            return []
        query = embed(body, self.dim)
        scored = [(float(query @ entry.embedding), entry) for entry in self._entries]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            SimilarQuote(
                rfq_id=entry.rfq_id,
                body=entry.body,
                total_eur=entry.total_eur,
                similarity=similarity,
            )
            for similarity, entry in scored[:k]
        ]
