# Fábrica Inteligente — Receitas de IA · Código companheiro

> Repositório público de código que acompanha o ebook *"Fábrica Inteligente: Receitas de IA"* (MoreDevs.ai).
> Estado: **em desenvolvimento.** Lançamento previsto para o final de 2026.
>
> 🇵🇹 PT (este ficheiro) · [🇬🇧 EN](README.en.md)

---

## O que é este repositório

Cinco receitas de IA aplicada a PMEs industriais, com código que corre — não código pedagógico. Cada receita tem três níveis:

- **Nível 1 — DIY** (€): ESP32 / Raspberry Pi, scripts Python, dashboards locais.
- **Nível 2 — Pro** (€€): stack completo com TimescaleDB, Postgres, Grafana, alertas, Docker.
- **Nível 3 — Premium** (€€€): arquitectura de referência, integrações ERP/MES/PLC. Sem código completo — é onde a MoreDevs.ai entra.

| # | Receita | Pasta |
|---|---|---|
| 1 | O Olho que Vê a Fábrica | [`receita-1-olho-da-fabrica/`](receita-1-olho-da-fabrica/) |
| 2 | A Máquina que Avisa Antes de Partir | [`receita-2-maquina-avisa/`](receita-2-maquina-avisa/) |
| 3 | O Orçamentista que Não Dorme | [`receita-3-orcamentista/`](receita-3-orcamentista/) |
| 4 | O Corte que Não Desperdiça | [`receita-4-corte-sem-desperdicio/`](receita-4-corte-sem-desperdicio/) |
| 5 | A Promessa de Prazo que se Cumpre | [`receita-5-promessa-prazo/`](receita-5-promessa-prazo/) |

## Arrancar em <30 minutos

```bash
git clone https://github.com/org-moredevs-ai/moredevs-ebook-001-code
cd moredevs-ebook-001-code

# 1. Setup do ambiente Python
make setup

# 2. Arrancar stack base (TimescaleDB + Mosquitto + Grafana)
make up

# 3. Gerar dados de exemplo para todas as receitas
make seed-data

# 4. Demo da Receita 1
make demo-r1
```

Abrir `http://localhost:3000` (Grafana, admin/admin local) para ver dados a fluir.

## Pré-requisitos

- **Python 3.13** (3.12 também testado).
- **uv** ≥ 0.5 — gestor de dependências ([instalar](https://docs.astral.sh/uv/getting-started/installation/)).
- **Docker** + **Docker Compose v2** — para Nível 2.
- **PlatformIO** — apenas para flashing ESP32 (Nível 1 de R1/R2).

Recomendado: **VS Code com a extensão Dev Containers**. `Reopen in Container` resolve tudo automaticamente em <5 min.

## Stack técnica

| Camada | Escolha |
|---|---|
| Linguagem | Python 3.13 |
| Gestor deps | `uv` |
| Time-series DB | **TimescaleDB** (extensão Postgres 16) |
| Relational DB | Postgres 16 (parte do TimescaleDB) |
| Broker MQTT | Eclipse Mosquitto |
| Dashboards | Grafana 11 |
| Optimização (R4, R5) | OR-Tools |
| LLM (R3) | Anthropic Claude (Sonnet 4.6 default) |
| UI N2 (R3, R4, R5) | Streamlit + FastAPI |
| Containerização | Docker + Compose v2 |

## Estrutura

```
.
├── lib-comum/          # Helpers MQTT, TimescaleDB, gerador de dados sintéticos
├── receita-1..5/       # Uma pasta por receita
│   ├── nivel-1-diy/
│   ├── nivel-2-pro/
│   ├── nivel-3-premium/  # README arquitectural, sem código
│   ├── data-exemplo/   # 3 sectores por receita
│   └── docs/
├── pack-extra/         # Pack opcional (Order Bump)
├── tests/              # Testes de integração end-to-end
├── tools/              # Utilitários (seed, snapshot, verify-sync)
├── docs/               # Documentação técnica + diagramas Mermaid
└── docker-compose.yml  # Stack base partilhado
```

## Licença

Código sob [MIT](LICENSE). Os textos do ebook (manuscrito, marketing) vivem num repositório privado separado e estão sob copyright MoreDevs.ai.

## Estado

**Em desenvolvimento.** Companion code para o ebook *Fábrica Inteligente: Receitas de IA*. Acompanha:

- Lançamento ebook: previsto para Q4 2026.
- Marketplaces: Amazon KDP, Apple Books, Google Play, Kobo, LeanPub.
- Adquire em [moredevs.ai/ebook-001](https://moredevs.ai/ebook-001) (em breve).

## Contribuir

Issues e PRs bem-vindos, mas o âmbito do repositório é fixado pelo ebook. Para discussões maiores, abre uma issue antes de submeter PR.

## Sobre

Produzido por [MoreDevs.ai](https://moredevs.ai). Consultoria de IA aplicada a PMEs industriais europeias.
