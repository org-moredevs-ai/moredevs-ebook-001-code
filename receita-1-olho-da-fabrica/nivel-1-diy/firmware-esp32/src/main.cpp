// ESP32 + SCT-013 current sensor — Recipe 1 Tier 1 firmware.
//
// PT: Lê amostras do ADC, calcula o RMS da corrente e publica o valor
// como payload JSON em MQTT a cada segundo. Reconnecta WiFi e MQTT
// automaticamente. O servidor de ingest consome o tópico canónico
// fabrica/<line>/<machine>/current.
// EN: Samples the ADC, computes the current RMS and publishes a JSON
// payload over MQTT once per second. Auto-reconnects WiFi and MQTT.
// The ingest server consumes the canonical topic
// fabrica/<line>/<machine>/current.
//
// Build-time configuration (see platformio.ini secrets.ini sample):
//   WIFI_SSID, WIFI_PASSWORD, MQTT_BROKER, MACHINE_ID
//   SENSOR_CALIBRATION_A_PER_V (default 30.0, matches SCT-013 30A clamp)

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

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
#define MACHINE_ID "linha-0.maquina-0"
#endif
#ifndef SENSOR_CALIBRATION_A_PER_V
#define SENSOR_CALIBRATION_A_PER_V 30.0f
#endif

constexpr int   ADC_PIN          = 34;
constexpr int   N_SAMPLES        = 200;
constexpr int   SAMPLE_DELAY_US  = 500;     // 200 samples in ~100 ms
constexpr float ADC_REF_V        = 3.3f;
constexpr int   ADC_MAX_COUNTS   = 4095;
constexpr int   ADC_BIAS_COUNTS  = 2048;    // SCT-013 biased to mid-rail
constexpr uint32_t PUBLISH_PERIOD_MS = 1000;

WiFiClient    wifiClient;
PubSubClient  mqtt(wifiClient);
char          topic[96];

static void build_topic() {
    // Convert "linha-3.maquina-1" -> "fabrica/linha-3/maquina-1/current"
    String id = String(MACHINE_ID);
    int dot = id.indexOf('.');
    if (dot < 0) {
        snprintf(topic, sizeof(topic), "fabrica/%s/current", id.c_str());
    } else {
        String line = id.substring(0, dot);
        String machine = id.substring(dot + 1);
        snprintf(topic, sizeof(topic), "fabrica/%s/%s/current",
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
    String client_id = "esp32-";
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

static float read_rms_current() {
    double sum_sq = 0.0;
    for (int i = 0; i < N_SAMPLES; i++) {
        int raw = analogRead(ADC_PIN);
        float v = (raw - ADC_BIAS_COUNTS) * (ADC_REF_V / (float) ADC_MAX_COUNTS);
        sum_sq += (double) v * v;
        delayMicroseconds(SAMPLE_DELAY_US);
    }
    float v_rms = sqrtf((float) (sum_sq / N_SAMPLES));
    return v_rms * SENSOR_CALIBRATION_A_PER_V;
}

void setup() {
    Serial.begin(115200);
    delay(500);
    analogReadResolution(12);
    analogSetPinAttenuation(ADC_PIN, ADC_11db);
    build_topic();
    connect_wifi();
    connect_mqtt();
}

void loop() {
    if (WiFi.status() != WL_CONNECTED) {
        connect_wifi();
    }
    if (!mqtt.connected()) {
        connect_mqtt();
    }
    mqtt.loop();

    float current_a = read_rms_current();

    JsonDocument doc;
    doc["machine"]   = MACHINE_ID;
    doc["current_a"] = current_a;
    doc["uptime_ms"] = (uint32_t) millis();

    char payload[160];
    size_t n = serializeJson(doc, payload, sizeof(payload));
    if (n > 0) {
        mqtt.publish(topic, payload, false);
    }

    delay(PUBLISH_PERIOD_MS - 100);
}
