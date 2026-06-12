# Receita 1 — Nível 2 (Pro)

> Modbus TCP + TimescaleDB + OEE em tempo real + dashboards multi-utilizador.

🇵🇹 PT (este ficheiro) · [🇬🇧 EN](README.en.md)

## O que muda em relação ao Nível 1

| Aspecto | Nível 1 (DIY) | Nível 2 (Pro) |
|---|---|---|
| Telemetria | SCT-013 → ESP32 → MQTT (proxy de corrente) | PLC → Modbus TCP (estado, contadores, temperaturas) |
| OEE | Não calculado | Disponibilidade em tempo real (continuous aggregates) |
| Histórico | Compactado a 7 dias | Idem + roll-ups por minuto/hora |
| Utilizadores | Dashboard local | Dashboard com múltiplos painéis e papéis |

A Receita 1 cobre apenas a **componente de disponibilidade** do OEE (running ÷ tempo). A Receita 2 acrescenta qualidade (anomalias) e a Receita 5 acrescenta performance (planeado vs real).

## Componentes

| Pasta | Função |
|---|---|
| [`modbus_collector/`](modbus_collector/) | Cliente Modbus TCP assíncrono. Polling de N máquinas em paralelo, escreve `state`/`shift_count`/`temperature_c`/`ambient_temp_c` em TimescaleDB. |
| [`grafana-dashboards/`](grafana-dashboards/) | Dashboard "Receita 1 N2 — OEE & Pro". |

Acrescentado a `lib_comum`:

- [`lib_comum/plc_sim/modbus_emulator.py`](../../lib_comum/plc_sim/modbus_emulator.py) — emulador Modbus TCP que substitui PLCs físicos em demos e testes.
- [`lib_comum/plc_sim/state_clock.py`](../../lib_comum/plc_sim/state_clock.py) — relógio comprimido (`SimClock`) partilhado por emuladores.
- [`lib_comum/sql/init/03_oee.sql`](../../lib_comum/sql/init/03_oee.sql) — continuous aggregates: `machine_availability_1m`, `machine_availability_1h`, view `machine_availability_last_24h`.

## Demo em <2 minutos (sem hardware)

```bash
make up                  # stack base
make seed-data           # gera o dataset alimentar (uma vez)
make demo-r1-n2          # emulador Modbus (5 PLCs) + colector, ~90 segundos
# → abre http://localhost:3000
# → dashboard "Receita 1 N2 — OEE & Pro"
```

O `demo-r1-n2` arranca:
1. Um emulador Modbus em `localhost:1502`, com 5 PLCs identificados por `device_id` 1..5.
2. O `modbus_collector` em paralelo, a fazer polling de cada máquina a cada segundo.

Após terminar, refresca os continuous aggregates uma última vez para o dashboard ficar populado.

## Stack final do Nível 2

| Componente | Versão | Função |
|---|---|---|
| Postgres + TimescaleDB | 16 + 2.x | Persistência relacional + séries temporais + continuous aggregates |
| Mosquitto | 2.0 | Broker MQTT (reutilizado do N1 para sensores que não tenham PLC) |
| Grafana | 11 | Dashboards |
| pymodbus | 3.7+ | Cliente Modbus TCP assíncrono |
| asyncua | 1.x | (Em construção — colector OPC-UA) |
| Apprise | 1.9+ | (Em construção — alertas multi-canal) |

## Mapeamento de holding registers (por máquina)

| Address | Conteúdo |
|---|---|
| HR 1 | Estado: 0 stopped, 1 running, 2 idle, 3 fault, 4 setup, 5 cleaning |
| HR 11 | `shift_count` — produção acumulada no turno (16-bit) |
| HR 21 | `temperature_c × 10` — temperatura interna (245 = 24,5 °C) |
| HR 22 | `ambient_temp_c × 10` — temperatura ambiente da linha |

O `modbus_collector` lê os 30 primeiros HRs de cada `device_id` e desempacota nestes 4 métricas. O emulador `modbus_emulator` serve estes valores a partir do dataset sintético.

## OEE — disponibilidade em tempo real

```sql
SELECT machine, ROUND(availability_24h::numeric, 2) AS availability
FROM machine_availability_last_24h
ORDER BY availability_24h ASC;
```

Saída típica após a demo:

```
      machine      | availability
-------------------+--------------
 linha-1.maquina-1 |         0.78
 linha-1.maquina-2 |         0.96
 linha-1.maquina-3 |         0.94
 linha-1.maquina-4 |         0.95
 linha-2.maquina-1 |         0.88
```

A política de refresh actualiza `machine_availability_1m` a cada 30 segundos e `machine_availability_1h` a cada 5 minutos. Em demos curtas (<2 min) chama-se `CALL refresh_continuous_aggregate(...)` manualmente — o `make demo-r1-n2` já faz isso no fim.

## Quando o N2 não chega

O Capítulo 1 descreve os limites:
- Mais do que uma fábrica → entra-se em N3 (multi-site, BI corporativo).
- Integração bidireccional ERP → também N3.
- Análise preditiva (RUL, anomalias) → Capítulo 2 (Receita 2).

Voltar à [Receita 1](../README.md).
