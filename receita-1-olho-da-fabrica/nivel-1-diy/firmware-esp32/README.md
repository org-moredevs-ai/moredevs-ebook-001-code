# Firmware ESP32 — Receita 1 N1

> ESP32 + SCT-013, lê a corrente do motor e publica em MQTT a cada segundo.

🇵🇹 PT (este ficheiro) · [🇬🇧 EN](README.en.md)

## Hardware

| Componente | Modelo de referência |
|---|---|
| Microcontrolador | ESP32 DevKitC-32E |
| Sensor de corrente | SCT-013 (versão com saída em tensão, 30 A) |
| Resistência burden | 33 Ω (já incluída no SCT-013 com saída de tensão) |
| Alimentação | USB-C 5 V, 1 A |
| Caixa | IP54, 80 × 60 × 40 mm |

## Esquema rápido

```
                  +-------------+        +---------+
[Motor] ====> |  SCT-013    | -----> |  ESP32  | --- WiFi ---> MQTT broker
              |  (clamp)    |  V_out |  GPIO34 |                (Mosquitto)
                  +-------------+        +---------+
```

A saída do SCT-013 (~1 V pico para 30 A) é polarizada para metade da
referência do ADC (1,65 V) por um divisor resistivo simples — assim
amostras positivas e negativas cabem no intervalo 0–3,3 V.

## Build

Usa [PlatformIO](https://platformio.org/).

```bash
cd receita-1-olho-da-fabrica/nivel-1-diy/firmware-esp32
cp secrets.ini.example secrets.ini
# Edita secrets.ini: SSID, password, broker MQTT, MACHINE_ID
echo "extra_configs = secrets.ini" >> platformio.ini
pio run
pio run -t upload          # flashing
pio device monitor -b 115200
```

## Tópico MQTT publicado

O firmware publica em:

```
fabrica/<line>/<machine>/current
```

`<line>` e `<machine>` derivam de `MACHINE_ID`, com o ponto a separar
(ex.: `linha-3.maquina-1` → `fabrica/linha-3/maquina-1/current`).

## Payload

```json
{
  "machine": "linha-3.maquina-1",
  "current_a": 5.823,
  "uptime_ms": 13420
}
```

## O que NÃO faz

- Não guarda histórico. Se a rede cair, perde-se a leitura — para uma PME
  em telemetria nova, este trade-off é aceitável (próximo turno o
  problema é detectado de qualquer forma). Se for crítico, ver Nível 2.
- Não tem OTA updates. Updates via cabo.
- Sem TLS por defeito. A rede MQTT é uma rede industrial fechada;
  expor à internet exige Nível 2 com certificados.
