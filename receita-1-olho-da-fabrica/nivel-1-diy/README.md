# Receita 1 — Nível 1 (DIY)

> ESP32 + SCT-013 → MQTT → TimescaleDB → Grafana. **~€600 para 10 máquinas.**

🇵🇹 PT (este ficheiro) · [🇬🇧 EN](README.en.md)

## O que isto faz

Mede a corrente eléctrica de cada motor (proxy fiável de "está a trabalhar / parado") e mostra-a num dashboard web acessível na rede local da fábrica. Capítulo 1 do livro descreve a teoria; este pacote é o código que corre.

## Componentes

| Pasta | Função |
|---|---|
| [`firmware-esp32/`](firmware-esp32/) | Firmware ESP32 (PlatformIO). Lê o SCT-013 e publica em MQTT a cada segundo. |
| [`ingest/`](ingest/) | Subscritor MQTT → INSERT em TimescaleDB. |
| [`simulator/`](simulator/) | Substitui as ESP32 físicas em demos e testes. Replays dados sintéticos via MQTT. |
| [`grafana-dashboards/`](grafana-dashboards/) | Dashboard JSON auto-provisionado para Grafana. |

## Lista de compras (10 máquinas)

| Item | Qtd | Preço unit. | Total |
|---|---|---|---|
| ESP32 DevKitC-32E (PTRobotics) | 10 | €12 | €120 |
| Sensor SCT-013 30 A com saída em tensão (PTRobotics) | 10 | €13 | €130 |
| Caixa IP54 80 × 60 × 40 mm | 10 | €10 | €100 |
| Fonte 5 V 1 A USB-C | 10 | €6 | €60 |
| Cabo USB-C 1 m | 10 | €3 | €30 |
| Bornes, fios, calhas DIN | — | — | €40 |
| Raspberry Pi 5 8 GB Kit | 1 | €110 | €110 |
| MicroSD 64 GB A2 V30 | 1 | €18 | €18 |
| **Total** | | | **~€608** |

> Fornecedores PT: PTRobotics (portes grátis acima de €75) e Mauser. Validade dos preços: Junho 2026, ±10%.

## Arquitectura

```
   [Motor]  ─cabo─►  [SCT-013]  ─V_out─►  [ESP32]  ─WiFi/MQTT─►  [Mosquitto]
                                                                       │
                                                                       ▼
                                                   [Ingest Python]  ─►  [TimescaleDB]
                                                                       │
                                                                       ▼
                                                                  [Grafana]  ──►  Browser
```

## Demo em <2 minutos (sem hardware)

A partir do directório raiz do repo:

```bash
make up                  # Postgres+TimescaleDB + Mosquitto + Grafana
make seed-data           # gera o dataset alimentar (uma vez)
make demo-r1             # simulator + ingest em paralelo, 90 segundos
# abre http://localhost:3000 (admin/admin)
# → dashboard "Receita 1 N1 — Olho da fábrica"
```

O `demo-r1` reproduz, em 90 segundos, a actividade de 5 máquinas de uma linha de produção alimentar — com paragens, regime normal e operações de limpeza. O dashboard mostra a corrente em tempo real e o estado actual.

## Demo com hardware real

1. Flashar o firmware nos ESP32 (ver [`firmware-esp32/README.md`](firmware-esp32/README.md)).
2. Instalar os SCT-013 nos cabos de alimentação dos motores.
3. Ligar tudo à mesma rede WiFi do Raspberry Pi (ou laptop) onde corre `make up`.
4. Arrancar o ingest: `uv run python receita-1-olho-da-fabrica/nivel-1-diy/ingest/mqtt_to_db.py`.

Os ESP32 publicam em `fabrica/<line>/<machine>/current` e o ingest subscreve `fabrica/+/+/current`.

## Esquema da base de dados

A hypertable `telemetry` é criada automaticamente no boot da TimescaleDB:

```sql
CREATE TABLE telemetry (
  ts        TIMESTAMPTZ      NOT NULL,
  machine   TEXT             NOT NULL,
  metric    TEXT             NOT NULL,
  value     DOUBLE PRECISION NOT NULL
);
SELECT create_hypertable('telemetry', 'ts', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX telemetry_machine_metric_ts_idx ON telemetry (machine, metric, ts DESC);
ALTER TABLE telemetry SET (timescaledb.compress, timescaledb.compress_segmentby = 'machine, metric');
SELECT add_compression_policy('telemetry', INTERVAL '7 days');
```

Chunks com mais de 7 dias são automaticamente comprimidos.

## Custo total tipo

- **Hardware:** €608.
- **Engenharia:** 4,5 dias-pessoa.
- **Mão-de-obra com electricista (1 dia):** ~€240.

**Total tipo:** ~€2.700. Se a empresa tem alguém da casa para fazer, cai para metade.

## Quando isto não chega

Ler corrente como proxy é uma boa primeira aproximação, mas tem limites:

- Não distingue causa de paragem (avaria? operador? matéria-prima?).
- Não mede qualidade nem rendimento por unidade.
- Não tem alertas multi-canal.
- Não integra com PLCs reais nem com o ERP.

Para isso, ver [Nível 2](../nivel-2-pro/).

Voltar à [Receita 1](../README.md).
