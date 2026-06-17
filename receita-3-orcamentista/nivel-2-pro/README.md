# Receita 3 — Nível 2 (Pro)

> Companion code para o Capítulo 3 do ebook *Fábrica Inteligente: Receitas de IA*.

O Nível 2 acrescenta ao orçamentista do Nível 1 três capacidades: leitura de
desenhos por **visão**, **memória vectorial** de orçamentos passados, e uma
**interface de revisão humana** com aprovação em dois cliques.

EN: Tier 2 adds three capabilities to the Tier 1 quote writer: **vision** for
reading drawings, a **vector memory** of past quotes, and a **human review** UI
with two-click approval.

## Componentes

| Ficheiro | Função |
|---|---|
| `lib_comum/quote_memory.py` | Índice vectorial de orçamentos aprovados (cosseno sobre *embeddings* de *hashing*; interface compatível com chromadb). |
| `lib_comum/quote_review.py` | Pipeline de revisão: extracção → preço → semelhantes → *flag* de coerência. |
| `quote_review/pipeline.py` | Demo de linha de comandos (corre *offline*). |
| `quote_review/app.py` | Interface Streamlit de revisão humana (Aprovar / Rejeitar). |
| `vision/pdf_extract.py` | Lê o texto de um PDF (`pypdf`) e extrai o pedido; *vision-ready* para desenhos. |

## Correr

```bash
# Demo CLI (offline, sem chave de API):
make demo-r3-n2

# Interface de revisão (Streamlit):
make demo-r3-n2-ui

# Com Claude (visão e extracção de maior qualidade):
export ANTHROPIC_API_KEY=sk-...
LLM_PROVIDER=anthropic make demo-r3-n2
```

## Notas

- O *backend* de memória incluído é leve e puro Python — corre em qualquer
  máquina, sem descarregar modelos. A interface (`add_quote` / `find_similar`)
  é a de um vector DB, pelo que se troca por **chromadb** em produção sem mexer
  no resto do código.
- O *flag* de preço compara o total calculado com a mediana dos pedidos
  passados mais parecidos: apanha erros de extracção (quantidades trocadas) e
  mantém coerência comercial.
- A aritmética do orçamento é sempre código testado (`lib_comum/quote_pricing.py`),
  nunca a IA — a IA só **lê**, não faz contas.
