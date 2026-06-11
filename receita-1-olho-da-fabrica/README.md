# Receita 1 — O Olho que Vê a Fábrica

> Saber, em tempo real, se cada máquina está a funcionar, parada ou a produzir mal — sem comprar máquinas novas.

🇵🇹 PT (este ficheiro) · [🇬🇧 EN](README.en.md)

## Estrutura

| Pasta | Conteúdo |
|---|---|
| [`nivel-1-diy/`](nivel-1-diy/) | ESP32 + SCT-013 + MQTT → InfluxDB → Grafana. ~€80 por máquina. |
| [`nivel-2-pro/`](nivel-2-pro/) | + Modbus/MTConnect/OPC-UA + Postgres + alertas. |
| [`nivel-3-premium/`](nivel-3-premium/) | Arquitectura de referência. Edge AI + ERP. Sem código completo. |
| [`data-exemplo/`](data-exemplo/) | Dados sintéticos para alimentar, metalomecânica, têxtil. |
| [`docs/`](docs/) | Documentação técnica adicional. |

## Estado

**Em desenvolvimento** — capítulo 1 piloto. Aguarda Fase 1 do plano de produção.

Voltar ao [README do repositório](../README.md).
