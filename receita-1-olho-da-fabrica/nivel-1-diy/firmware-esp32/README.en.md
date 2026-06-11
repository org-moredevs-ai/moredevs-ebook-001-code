# ESP32 firmware — Recipe 1 Tier 1

> ESP32 + SCT-013, reads motor current and publishes over MQTT every second.

🇬🇧 EN (this file) · [🇵🇹 PT](README.md)

## Hardware

| Item | Reference part |
|---|---|
| MCU | ESP32 DevKitC-32E |
| Current sensor | SCT-013 (voltage-output version, 30 A) |
| Burden resistor | 33 Ω (already inside the voltage-output SCT-013) |
| Power | USB-C 5 V, 1 A |
| Enclosure | IP54, 80 × 60 × 40 mm |

## Quick schematic

```
                  +-------------+        +---------+
[Motor] ====> |  SCT-013    | -----> |  ESP32  | --- WiFi ---> MQTT broker
              |  (clamp)    |  V_out |  GPIO34 |                (Mosquitto)
                  +-------------+        +---------+
```

The SCT-013 output (~1 V peak for 30 A) is biased to the ADC mid-rail
(1.65 V) via a resistor divider so positive and negative samples fit in
the 0–3.3 V range.

## Build

Uses [PlatformIO](https://platformio.org/).

```bash
cd receita-1-olho-da-fabrica/nivel-1-diy/firmware-esp32
cp secrets.ini.example secrets.ini
# Edit secrets.ini: SSID, password, MQTT broker, MACHINE_ID
echo "extra_configs = secrets.ini" >> platformio.ini
pio run
pio run -t upload          # flash
pio device monitor -b 115200
```

## Published MQTT topic

The firmware publishes to:

```
fabrica/<line>/<machine>/current
```

`<line>` and `<machine>` are derived from `MACHINE_ID`, splitting on the
dot (e.g. `linha-3.maquina-1` → `fabrica/linha-3/maquina-1/current`).

## Payload

```json
{
  "machine": "linha-3.maquina-1",
  "current_a": 5.823,
  "uptime_ms": 13420
}
```

## What it does NOT do

- No local history. If the network drops, samples are lost — acceptable
  trade-off when a factory is moving from zero telemetry to some
  telemetry. If business-critical, go to Tier 2.
- No OTA updates. Updates over cable.
- No TLS by default. The MQTT network is the factory's private LAN.
  Exposing it to the internet needs Tier 2 with certificates.
