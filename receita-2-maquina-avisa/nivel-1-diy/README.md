# Receita 2 — Nível 1 (DIY)

> ESP32 + ADXL345 → MQTT (snapshots brutos) → FFT em Python → alerta. **~€50 por máquina.**

🇵🇹 PT (este ficheiro) · [🇬🇧 EN](README.en.md)

## O que isto faz

Cada máquina importante recebe um acelerómetro ADXL345 ligado a um ESP32. A cada poucos segundos, o ESP32 captura 1 segundo de amostras a 1 kHz nos três eixos e envia o pacote bruto por MQTT. Um pequeno serviço Python corre a FFT, extrai a amplitude na banda BPFO (chumaceira), congela um baseline saudável e dispara alerta quando a banda cresce mais de 30–40% acima desse baseline.

O caso de campo do Capítulo 2: a prensa de 250 t entra em falha de chumaceira 11 dias antes da paragem catastrófica. O dataset sintético `moldes` injecta exactamente esse sinal e o pipeline aqui detecta-o sem qualquer falso positivo nas outras 5 máquinas.

## Componentes

| Pasta | Função |
|---|---|
| [`firmware-esp32/`](firmware-esp32/) | Firmware ESP32 + ADXL345 (PlatformIO). |
| [`simulator/`](simulator/) | Substitui as ESP32 físicas em demos e testes. Publica snapshots sintetizados a partir do dataset `moldes`. |
| [`fft_alert/`](fft_alert/) | Subscritor MQTT, FFT em Python, alertas com baseline congelado. |
| [`grafana-dashboards/`](grafana-dashboards/) | Dashboard "Receita 2 N1 — Vibração & FFT". |

Suporte em `lib_comum`:

- [`lib_comum/plc_sim/vibration_signal.py`](../../lib_comum/plc_sim/vibration_signal.py) — gerador de waveform sintético partilhado pelo simulator e pelos testes.
- [`lib_comum/sql/init/04_vibration.sql`](../../lib_comum/sql/init/04_vibration.sql) — tabelas `vibration_bands` e `vibration_alerts`.
- [`lib_comum/db.py`](../../lib_comum/db.py) — helpers de inserção em batch.

## Lista de compras (por máquina)

| Item | Preço unit. |
|---|---|
| ESP32 DevKitC-32E | €12 |
| ADXL345 breakout | €4 |
| Caixa IP54 + suporte magnético / cola industrial | €15 |
| Fonte 5 V 1 A USB-C + cabo | €10 |
| Bornes, fios | €5 |
| **Subtotal por máquina** | **~€46** |

A 10 motores monitorizados: ~€460 em hardware. Servidor partilhado com a Receita 1 (sem custo adicional).

## Demo em <2 minutos (sem hardware)

A partir do directório raiz do repo:

```bash
make up                  # Postgres + TimescaleDB + Mosquitto + Grafana
make seed-data           # alimentar + moldes datasets
make demo-r2             # simulator + FFT receiver em paralelo, 60 segundos
# → abre http://localhost:3000 (admin/admin)
# → dashboard "Receita 2 N1 — Vibração & FFT"
```

O `demo-r2` reproduz 3 dias simulados do dataset `moldes`, começando 1 dia antes da janela de wear da prensa-1. Em ~60 segundos de tempo real, o receptor vê o baseline congelar nas máquinas saudáveis e a banda BPFO da prensa subir 2–4× acima do baseline. Os alertas concentram-se exclusivamente na prensa-1, nos três eixos.

## Arquitectura

```
[Motor]  ─cola/íman─►  [ADXL345]  ─I²C─►  [ESP32]  ─WiFi/MQTT─►  [Mosquitto]
                                                                       │
                                                                       ▼
                                                    [FFT receiver Python]
                                                                       │
                                                            ┌──────────┴──────────┐
                                                            ▼                     ▼
                                                  [TimescaleDB]            Apprise alert
                                                  vibration_bands           Telegram / email
                                                  vibration_alerts          (Nível 2)
                                                            │
                                                            ▼
                                                       [Grafana]
```

## Tópico e payload MQTT

Tópico:

```
fabrica/<line>/<machine>/vibration
```

Payload JSON (1 segundo a 1 kHz):

```json
{
  "machine": "prensa-250t.maquina-1",
  "sample_rate_hz": 1000,
  "uptime_ms": 13420,
  "x": [0.018, 0.022, -0.011, ...],
  "y": [-0.005, 0.014, ...],
  "z": [0.001, 0.008, ...]
}
```

## O que o receptor faz

1. Subscreve `fabrica/+/+/vibration`.
2. Para cada snapshot, corre `numpy.fft.rfft` por eixo e calcula a amplitude RMS dentro de duas bandas:
   - **`rotation_1x`** — 22–28 Hz (1× rotação para a prensa).
   - **`bpfo`** — 79–87 Hz (banda da chumaceira para a prensa, valor típico).
3. Persiste cada amplitude em `vibration_bands`.
4. Acumula um baseline durante `--warmup-samples` snapshots; depois **congela** o valor.
5. Quando uma amostra ultrapassa `baseline × (1 + threshold_pct/100)`, dispara alerta:
   - severidade `info` para ≥1,5× baseline, `warning` para ≥2×, `critical` para ≥3×.
   - cooldown configurável para evitar flapping.
   - amplitude mínima absoluta (`--min-amplitude-g`) protege contra falsos positivos em máquinas silenciosas.

## Limites do Nível 1

- Apenas duas bandas pré-definidas. Para classificar a fault (BPFO vs BPFI vs FTF vs BSF) é preciso conhecer a geometria da chumaceira.
- Baseline congelado assume que a máquina arranca saudável. Em produção, recalibra-se após cada manutenção.
- Sem aprendizagem (Isolation Forest, autoencoder). É a Receita 2 Nível 2.
- Alerta via log apenas. Para Telegram/email, ligar Apprise — base já está no `lib_comum`.

Voltar à [Receita 2](../README.md).
