// ESP32 + ADXL345 vibration sensor — Recipe 2 Tier 1 firmware.
//
// PT: Captura 1 segundo de amostras de 3 eixos a 1 kHz e envia em JSON
// por MQTT. O servidor Python corre a FFT.
// EN: Captures 1 second of 3-axis samples at 1 kHz and ships them as a
// JSON payload over MQTT. The Python server runs the FFT.
//
// Topic published:
//     fabrica/<line>/<machine>/vibration
//
// Build-time defines (set via secrets.ini):
//     WIFI_SSID, WIFI_PASSWORD, MQTT_BROKER, MQTT_PORT, MACHINE_ID

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_ADXL345_U.h>

#ifndef WIFI_SSID
#define WIFI_SSID "FabricaIoT"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "change_me"
#endif
#ifndef MQTT_BROKER
#define MQTT_BROKER "192.168.1.10"
#endif
#ifndef MQTT_PORT
#define MQTT_PORT 1883
#endif
#ifndef MACHINE_ID
#define MACHINE_ID "prensa-250t.maquina-1"
#endif

constexpr int   SAMPLE_RATE_HZ = 1000;
constexpr int   WINDOW_SAMPLES = 1000;     // 1 second window
constexpr uint32_t SAMPLE_DELAY_US = 1000; // 1 kHz
constexpr uint32_t REST_BETWEEN_WINDOWS_MS = 5000;

WiFiClient    wifiClient;
PubSubClient  mqtt(wifiClient);
Adafruit_ADXL345_Unified accel(12345);
char          topic[96];

// Triple buffers of float samples — packed into the JSON payload.
float buf_x[WINDOW_SAMPLES];
float buf_y[WINDOW_SAMPLES];
float buf_z[WINDOW_SAMPLES];

static void build_topic() {
    String id = String(MACHINE_ID);
    int dot = id.indexOf('.');
    if (dot < 0) {
        snprintf(topic, sizeof(topic), "fabrica/%s/vibration", id.c_str());
    } else {
        String line = id.substring(0, dot);
        String machine = id.substring(dot + 1);
        snprintf(topic, sizeof(topic), "fabrica/%s/%s/vibration",
                 line.c_str(), machine.c_str());
    }
}

static void connect_wifi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.printf("[wifi] connecting to %s", WIFI_SSID);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print('.');
    }
    Serial.printf("\n[wifi] connected, IP=%s\n", WiFi.localIP().toString().c_str());
}

static void connect_mqtt() {
    mqtt.setServer(MQTT_BROKER, MQTT_PORT);
    mqtt.setBufferSize(48 * 1024); // 1000 samples * 3 axes * ~12 chars each
    String client_id = "esp32-vib-";
    client_id += MACHINE_ID;
    while (!mqtt.connected()) {
        Serial.printf("[mqtt] connecting as %s...", client_id.c_str());
        if (mqtt.connect(client_id.c_str())) {
            Serial.println(" ok");
        } else {
            Serial.printf(" failed rc=%d, retry in 2s\n", mqtt.state());
            delay(2000);
        }
    }
}

static void capture_window() {
    uint32_t next_us = micros();
    for (int i = 0; i < WINDOW_SAMPLES; i++) {
        sensors_event_t evt;
        accel.getEvent(&evt);
        buf_x[i] = evt.acceleration.x / 9.80665f; // m/s^2 -> g
        buf_y[i] = evt.acceleration.y / 9.80665f;
        buf_z[i] = evt.acceleration.z / 9.80665f;
        next_us += SAMPLE_DELAY_US;
        int32_t wait = (int32_t)(next_us - micros());
        if (wait > 0) {
            delayMicroseconds(wait);
        }
    }
}

static void publish_window() {
    JsonDocument doc;
    doc["machine"] = MACHINE_ID;
    doc["sample_rate_hz"] = SAMPLE_RATE_HZ;
    doc["uptime_ms"] = (uint32_t) millis();
    JsonArray ax = doc["x"].to<JsonArray>();
    JsonArray ay = doc["y"].to<JsonArray>();
    JsonArray az = doc["z"].to<JsonArray>();
    for (int i = 0; i < WINDOW_SAMPLES; i++) {
        ax.add(buf_x[i]);
        ay.add(buf_y[i]);
        az.add(buf_z[i]);
    }
    String payload;
    serializeJson(doc, payload);
    if (!mqtt.publish(topic, payload.c_str())) {
        Serial.printf("[mqtt] publish failed (%d bytes)\n", payload.length());
    }
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Wire.begin();
    if (!accel.begin()) {
        Serial.println("[adxl345] not found — check wiring!");
        while (true) delay(1000);
    }
    accel.setRange(ADXL345_RANGE_8_G);
    accel.setDataRate(ADXL345_DATARATE_3200_HZ);
    build_topic();
    connect_wifi();
    connect_mqtt();
}

void loop() {
    if (WiFi.status() != WL_CONNECTED) connect_wifi();
    if (!mqtt.connected()) connect_mqtt();
    mqtt.loop();

    capture_window();
    publish_window();

    delay(REST_BETWEEN_WINDOWS_MS);
}
