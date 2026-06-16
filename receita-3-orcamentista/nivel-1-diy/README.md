# Receita 3 — Nível 1 (DIY)

> RFQ por email → LLM extrai itens → catálogo → orçamento pronto a enviar, em minutos. **~€0,05 por orçamento.**

🇵🇹 PT (este ficheiro) · [🇬🇧 EN](README.en.md)

## O que isto faz

Cliente envia um pedido por email, WhatsApp ou formulário. O sistema lê o texto, identifica as operações (corte laser, dobragem, soldadura, furação, pintura, montagem), o material (aço inox 304/316L, carbono S235/S275, alumínio 5754/6082), a espessura e a quantidade. Cruza com o catálogo de preços, aplica margem e IVA, e devolve o orçamento numa janela do browser — pronto para o director rever em 2 cliques e enviar.

O caso de campo do Capítulo 3: serralharia no Vale do Sousa que responde em minutos a pedidos que costumavam demorar 1–2 dias. Resposta no dia subiu de 35% para 92%.

## Componentes

| Pasta / módulo | Função |
|---|---|
| [`quote_writer/app.py`](quote_writer/app.py) | UI Streamlit para revisão e exportação. |
| [`quote_writer/pipeline.py`](quote_writer/pipeline.py) | Orquestrador CLI (sem UI). |

Suporte em `lib_comum`:

- [`lib_comum/data_synth/rfq.py`](../../lib_comum/data_synth/rfq.py) — gerador sintético de RFQs em PT-PT (email formal, WhatsApp, formulário) + catálogo de preços (58 linhas).
- [`lib_comum/llm.py`](../../lib_comum/llm.py) — interface abstracta com dois fornecedores: **Anthropic Claude** (Sonnet 4.6 por defeito) e **offline** (regex para testes e ambientes sem rede).
- [`lib_comum/quote_pricing.py`](../../lib_comum/quote_pricing.py) — motor de pricing (lookup hierárquico no catálogo, totais com margem e IVA, items por classificar).

## Demo em <1 minuto

```bash
make demo-r3          # abre Streamlit em http://localhost:8501
# ou
make demo-r3-cli      # corre o pipeline em terminal com offline provider
```

Para usar o Anthropic Claude:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
make demo-r3          # Streamlit usa Anthropic por defeito quando há API key
```

Sem API key, o pipeline cai automaticamente para o fornecedor `offline` (regex). Útil para testes, CI e ambientes air-gapped — não é tão preciso (~80–90% de match nos RFQs sintéticos) mas dá uma base sem dependências externas.

## Catálogo

O catálogo está em código (gerado por `rfq.load_catalogue()`) com 58 entradas cobrindo as 7 operações × 6 materiais × 4 espessuras + linhas flat-fee (furação, rebarbagem, pintura, montagem). Preços realistas para PT-PT 2026.

Para produção real:
- Exportar `rfq.load_catalogue()` para CSV.
- Editar a CSV com os preços do vosso fornecedor.
- Passar via `--catalogue path/to/seu.csv` no pipeline ou montar no Streamlit.

## Custo por orçamento

| Item | Por orçamento |
|---|---|
| Anthropic Claude Sonnet 4.6 — ~1–2k tokens in, ~500 out | ~€0,04 |
| TimescaleDB / Postgres write | quase grátis |
| Streamlit hosting (self-hosted) | quase grátis |
| **Total marginal** | **~€0,05** |

A 50 orçamentos/dia: **~€2,50/dia** em LLM. Comparado com 30 min de engenheiro por orçamento (€20–30 cada), o ROI é imediato.

## Limites do Nível 1

- **Sem PDF/imagem.** RFQs com desenho técnico anexado precisam de Vision (Nível 2).
- **Sem histórico.** Não compara com orçamentos anteriores do mesmo cliente. Nível 2 traz vector DB (Chroma) com semelhança semântica.
- **Sem aprovação automática.** O orçamento volta a humano antes de enviar. Aprovação automática para casos simples — Nível 3.
- **Catálogo estático.** Mudanças de preços via redeploy. Para gestão dinâmica — Nível 2 (Postgres).

Voltar à [Receita 3](../README.md).
