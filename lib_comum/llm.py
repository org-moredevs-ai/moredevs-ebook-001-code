"""Provider-agnostic LLM interface used by Recipe 3 (and onwards).

PT: Interface abstracta para extracção estruturada. O fornecedor por
omissão é o Anthropic Claude (Sonnet 4.6). Para testes ou ambientes sem
chave de API, existe um fornecedor *offline* baseado em regex que parsa
os RFQs sintéticos da Receita 3 — não cobre tudo, mas garante que o
pipeline corre end-to-end sem rede.
EN: Provider-agnostic interface for structured extraction. Default
provider is Anthropic Claude (Sonnet 4.6). For tests and offline
environments, a regex-based provider parses the synthetic Recipe 3 RFQs —
it doesn't cover everything but it keeps the pipeline runnable without
network access or API keys.

Both providers return a list of :class:`ExtractedLineItem` plus the raw
provider response (for auditing). The :func:`make_provider` factory picks
the right backend from env or arguments::

    provider = make_provider()  # uses LLM_PROVIDER env, defaults to anthropic
    extraction = provider.extract_rfq(text)
"""

from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Final, Literal

LOG = logging.getLogger("llm")


ProviderName = Literal["anthropic", "offline"]

DEFAULT_MODEL: Final[str] = "claude-sonnet-4-6"


@dataclass(frozen=True, slots=True)
class ExtractedLineItem:
    """One line item recovered from an RFQ.

    PT: Item extraído de um RFQ.
    EN: Line item extracted from an RFQ.

    The shape mirrors :class:`lib_comum.data_synth.rfq.GroundTruthItem` so
    tests can compare ground truth to extraction without re-mapping.
    """

    operation: str
    material: str
    thickness_mm: float
    quantity: int
    note: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "material": self.material,
            "thickness_mm": self.thickness_mm,
            "quantity": self.quantity,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class RfqExtraction:
    """Result of an RFQ extraction call.

    PT: Resultado da extracção.
    EN: RFQ extraction result.
    """

    items: list[ExtractedLineItem]
    customer: str | None = None
    deadline_days: int | None = None
    raw_provider_text: str | None = None
    provider: str = "offline"
    audit_metadata: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Common extraction interface."""

    name: ProviderName

    @abstractmethod
    def extract_rfq(self, body: str) -> RfqExtraction:
        """Return the structured extraction for *body*."""


# ---------------------------------------------------------------------------
# Offline provider (regex)
# ---------------------------------------------------------------------------


_OPERATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("corte_laser", re.compile(r"\bcorte\s+laser\b", re.IGNORECASE)),
    ("dobragem", re.compile(r"\b(?:dobragem|dobrar)\b", re.IGNORECASE)),
    ("soldadura", re.compile(r"\b(?:soldadura|soldar)\b", re.IGNORECASE)),
    ("furacao", re.compile(r"\bfura(?:ç[aã]o|r|cao|s)\b", re.IGNORECASE)),
    ("rebarbagem", re.compile(r"\brebarba(?:gem|r)\b", re.IGNORECASE)),
    ("pintura_epoxy", re.compile(r"\bpint(?:ura)?\s*epox[yi]\b", re.IGNORECASE)),
    ("montagem", re.compile(r"\bmontagem\b", re.IGNORECASE)),
)

_MATERIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aço inox 316L", re.compile(r"a[çc]o\s+inox\s+316L", re.IGNORECASE)),
    ("aço inox 304", re.compile(r"a[çc]o\s+inox\s+304", re.IGNORECASE)),
    ("aço carbono S275", re.compile(r"a[çc]o\s+carbono\s+S275", re.IGNORECASE)),
    ("aço carbono S235", re.compile(r"a[çc]o\s+carbono\s+S235", re.IGNORECASE)),
    ("alumínio 6082", re.compile(r"alum[ií]nio\s+6082", re.IGNORECASE)),
    ("alumínio 5754", re.compile(r"alum[ií]nio\s+5754", re.IGNORECASE)),
)

_THICKNESS_RE = re.compile(r"espessura\s*(?P<value>\d+(?:[\.,]\d+)?)\s*mm", re.IGNORECASE)
_QUANTITY_RE = re.compile(
    r"(?P<value>\d+)\s*(?P<unit>m\s*de\s+corte|m\s*de\s+cord[aã]o|m[ií2]?|dobras|furos|minutos|horas)",
    re.IGNORECASE,
)
_CUSTOMER_RE = re.compile(
    r"^Pedido\s+de\s+or[çc]amento\s*[\u2014\u2013-]\s*(?P<customer>.+)$",
    re.MULTILINE | re.IGNORECASE,
)
_CUSTOMER_SIG_RE = re.compile(r"cumprimentos,\s*(?P<customer>[^\n]+?)(?:\n|$)", re.IGNORECASE)
_DEADLINE_RE = re.compile(
    r"(?:Prazo\s*[:.]?\s*|entrega\s+em\s+|m[aá]ximo\s+de\s+)(?P<value>\d+)\s*dias", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class OfflineProvider(LLMProvider):
    """Regex-based RFQ extractor.

    PT: Extractor por regex. Cobre os templates da
    :mod:`lib_comum.data_synth.rfq`.
    EN: Regex-based extractor. Covers the templates produced by
    :mod:`lib_comum.data_synth.rfq`.
    """

    name: ProviderName = "offline"

    def extract_rfq(self, body: str) -> RfqExtraction:
        items: list[ExtractedLineItem] = []
        for line in body.splitlines():
            raw = line.strip()
            is_bullet = bool(raw) and raw[0] in "-*•"
            stripped = raw.lstrip("-*•").strip()
            if not stripped:
                continue
            item = _parse_line(stripped)
            if item is not None:
                items.append(item)
            elif is_bullet:
                # A bullet is a work-item line; if the regex can't parse it we
                # surface it for human review ("itens por classificar") instead
                # of dropping it silently — the offline path is limited, not sneaky.
                items.append(
                    ExtractedLineItem(
                        operation="",
                        material="",
                        thickness_mm=0.0,
                        quantity=0,
                        note=f"linha não reconhecida: {stripped}",
                    )
                )
        return RfqExtraction(
            items=items,
            customer=_match_customer(body),
            deadline_days=_match_deadline(body),
            raw_provider_text=None,
            provider="offline",
            audit_metadata={"line_count": len(body.splitlines())},
        )


def _parse_line(line: str) -> ExtractedLineItem | None:
    operation: str | None = None
    for op_name, pattern in _OPERATION_PATTERNS:
        if pattern.search(line):
            operation = op_name
            break
    if operation is None:
        return None

    material = ""
    for mat_name, pattern in _MATERIAL_PATTERNS:
        if pattern.search(line):
            material = mat_name
            break

    thickness = 0.0
    thickness_match = _THICKNESS_RE.search(line)
    if thickness_match is not None:
        thickness = float(thickness_match.group("value").replace(",", "."))

    quantity = 0
    for quantity_match in _QUANTITY_RE.finditer(line):
        unit = quantity_match.group("unit").lower().strip()
        # Skip the thickness mm if it slipped into the iterator.
        if unit in {"mm"} or "espessura" in line.lower()[: quantity_match.start()][-15:]:
            continue
        quantity = max(quantity, int(quantity_match.group("value")))

    return ExtractedLineItem(
        operation=operation,
        material=material,
        thickness_mm=thickness,
        quantity=quantity,
    )


def _match_customer(body: str) -> str | None:
    match = _CUSTOMER_RE.search(body)
    if match is not None:
        return match.group("customer").strip()
    match = _CUSTOMER_SIG_RE.search(body)
    if match is not None:
        return match.group("customer").strip()
    return None


def _match_deadline(body: str) -> int | None:
    match = _DEADLINE_RE.search(body)
    if match is None:
        return None
    return int(match.group("value"))


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------


_ANTHROPIC_PROMPT = """Extrai os itens de orçamento desta mensagem (PT-PT, sector metalomecânica).

Devolve APENAS JSON válido com este formato:

{
  "customer": "...",
  "deadline_days": 14,
  "items": [
    {"operation": "corte_laser", "material": "aço inox 304", "thickness_mm": 2, "quantity": 30, "note": null}
  ]
}

Códigos de operação válidos: corte_laser, dobragem, soldadura, furacao, rebarbagem, pintura_epoxy, montagem.
Materiais válidos: aço inox 304, aço inox 316L, aço carbono S235, aço carbono S275, alumínio 5754, alumínio 6082.
Se não conseguires determinar um valor, deixa como string vazia (para strings) ou 0 (para números).

Mensagem:
---
{body}
---"""


@dataclass(frozen=True, slots=True)
class AnthropicProvider(LLMProvider):
    """Real Anthropic-backed extractor.

    PT: Extractor via Anthropic Claude.
    EN: Anthropic-backed extractor.
    """

    api_key: str
    model: str = DEFAULT_MODEL
    name: ProviderName = "anthropic"

    def extract_rfq(self, body: str) -> RfqExtraction:
        # Local import keeps the offline test path free of the dependency.
        from anthropic import Anthropic

        client = Anthropic(api_key=self.api_key)
        prompt = _ANTHROPIC_PROMPT.replace("{body}", body)
        response = client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text_chunks: list[str] = []
        for block in response.content:
            # The SDK's content union includes many block types (tool use, etc).
            # We only care about plain text blocks.
            text = getattr(block, "text", None)
            if isinstance(text, str):
                text_chunks.append(text)
        body_text = "".join(text_chunks).strip()
        parsed = _safe_json(body_text)
        items: list[ExtractedLineItem] = []
        raw_items = parsed.get("items", [])
        if isinstance(raw_items, list):
            for entry in raw_items:
                if not isinstance(entry, dict):
                    continue
                items.append(
                    ExtractedLineItem(
                        operation=str(entry.get("operation", "")),
                        material=str(entry.get("material", "")),
                        thickness_mm=float(entry.get("thickness_mm", 0.0) or 0.0),
                        quantity=int(entry.get("quantity", 0) or 0),
                        note=(str(entry["note"]) if entry.get("note") else None),
                    )
                )
        deadline_raw = parsed.get("deadline_days")
        deadline_days = int(deadline_raw) if isinstance(deadline_raw, int | float) else None
        customer_raw = parsed.get("customer")
        customer = str(customer_raw) if isinstance(customer_raw, str) else None
        return RfqExtraction(
            items=items,
            customer=customer,
            deadline_days=deadline_days,
            raw_provider_text=body_text,
            provider="anthropic",
            audit_metadata={
                "model": self.model,
                "input_tokens": getattr(response.usage, "input_tokens", None),
                "output_tokens": getattr(response.usage, "output_tokens", None),
            },
        )


def _rfq_from_json(
    parsed: dict[str, object],
    *,
    raw_text: str,
    provider: str,
    audit: dict[str, object],
) -> RfqExtraction:
    """Map a parsed JSON object to an :class:`RfqExtraction` (shared by cloud providers)."""
    items: list[ExtractedLineItem] = []
    raw_items = parsed.get("items", [])
    if isinstance(raw_items, list):
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            items.append(
                ExtractedLineItem(
                    operation=str(entry.get("operation", "")),
                    material=str(entry.get("material", "")),
                    thickness_mm=float(entry.get("thickness_mm", 0.0) or 0.0),
                    quantity=int(entry.get("quantity", 0) or 0),
                    note=(str(entry["note"]) if entry.get("note") else None),
                )
            )
    deadline_raw = parsed.get("deadline_days")
    deadline_days = int(deadline_raw) if isinstance(deadline_raw, int | float) else None
    customer_raw = parsed.get("customer")
    customer = str(customer_raw) if isinstance(customer_raw, str) else None
    return RfqExtraction(
        items=items,
        customer=customer,
        deadline_days=deadline_days,
        raw_provider_text=raw_text,
        provider=provider,
        audit_metadata=audit,
    )


@dataclass(frozen=True, slots=True)
class OpenRouterProvider(LLMProvider):
    """Paid cloud extractor — runs Claude through OpenRouter's OpenAI-compatible API.

    PT: Caminho pago (o "modelo especializado na nuvem" do livro). Corre o Claude
    via OpenRouter, para quem tem uma ``OPENROUTER_API_KEY`` em vez da chave directa
    da Anthropic. A extracção é a mesma; muda só a rota.
    EN: Paid path — runs Claude via OpenRouter for users holding an
    ``OPENROUTER_API_KEY`` instead of a direct Anthropic key.
    """

    api_key: str
    model: str = "anthropic/claude-sonnet-4.6"
    name: ProviderName = "anthropic"

    def extract_rfq(self, body: str) -> RfqExtraction:
        import urllib.request

        prompt = _ANTHROPIC_PROMPT.replace("{body}", body)
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048,
                "temperature": 0,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://moredevs.ai",
                "X-Title": "MoreDevs Ebook Receita 3",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        message = data["choices"][0]["message"]
        body_text = str(message.get("content") or "").strip()
        usage = data.get("usage", {}) or {}
        return _rfq_from_json(
            _safe_json(body_text),
            raw_text=body_text,
            provider="anthropic",
            audit={
                "model": self.model,
                "via": "openrouter",
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            },
        )


def _safe_json(text: str) -> dict[str, object]:
    """Extract the first JSON object from *text*, tolerating prose around it."""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    raw = text[start : end + 1]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        LOG.warning("Anthropic response was not valid JSON; returning empty extraction")
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_provider(
    name: ProviderName | None = None,
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    """Build a provider from explicit args or the env.

    PT: Constrói um fornecedor. Prioridade: argumento explícito, depois
    ``LLM_PROVIDER`` (env), depois fallback para ``offline``.
    EN: Builds a provider. Priority: explicit args, then ``LLM_PROVIDER``
    env, then fallback to ``offline``.
    """
    chosen = name or os.environ.get("LLM_PROVIDER", "anthropic")
    if chosen == "anthropic":
        # PT: caminho pago (Claude). Preferimos o OpenRouter se a sua chave estiver
        # definida (chama o Claude via API compatível); senão a chave directa da
        # Anthropic; senão recorre ao offline. EN: paid Claude path — OpenRouter first,
        # then direct Anthropic, then offline fallback.
        or_key = os.environ.get("OPENROUTER_API_KEY")
        if or_key:
            return OpenRouterProvider(
                api_key=or_key,
                model=model or os.environ.get("LLM_MODEL", "anthropic/claude-sonnet-4.6"),
            )
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            LOG.warning(
                "Nem OPENROUTER_API_KEY nem ANTHROPIC_API_KEY definidas; "
                "a usar o provider offline (regex)."
            )
            return OfflineProvider()
        return AnthropicProvider(
            api_key=key,
            model=model or os.environ.get("LLM_MODEL", DEFAULT_MODEL),
        )
    if chosen == "offline":
        return OfflineProvider()
    raise ValueError(f"Unknown LLM provider: {chosen}")
