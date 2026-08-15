/*
 * TrackerD P2P - rohes LoRa auf dem Dragino TrackerD (ESP32-PICO-D4 + RFM95W/SX1276).
 *
 * Laeuft als zweite Firmware im OTA-Slot app1. Die LoRaWAN-Firmware bleibt in
 * app0 liegen, die Keys im NVS werden nicht angefasst: diese Firmware schreibt
 * nichts ins NVS, die Konfiguration lebt nur im RAM und steht nach jedem Start
 * wieder auf den Defaults unten.
 *
 * Zurueck zu LoRaWAN: AT+LORAWAN (setzt die Bootpartition auf app0 und startet
 * neu) oder vom PC aus ../switch_app.py lorawan.
 *
 * Konsole: 115200 Baud, zeilenweise, CR/LF egal.
 */
#include <Arduino.h>
#include <SPI.h>
#include <LoRa.h>
#include <esp_ota_ops.h>

#define FW_VERSION "TrackerD-P2P v1.0"

/* Pinbelegung laut Dragino-Pinmapping (README des TrackerD-Repos) */
#define PIN_SCK    5
#define PIN_MISO  19
#define PIN_MOSI  27
#define PIN_NSS   18
#define PIN_RST   23
#define PIN_DIO0  26

#define LED_RED   15
#define LED_BLUE   2
#define LED_GREEN 13

/* Defaults: EU868, passend zur Werkseinstellung des EByte E22 (Syncword 0x12) */
static long     cfgFreq   = 868125000;
static int      cfgSf     = 7;
static long     cfgBw     = 125000;
static int      cfgCr     = 5;      /* 5..8 entspricht 4/5..4/8 */
static int      cfgPower  = 17;     /* dBm, PA_BOOST */
static int      cfgSync   = 0x12;
static int      cfgPre    = 8;
static bool     cfgCrc    = true;
static bool     rxEnabled = true;
static bool     hexOut    = false;  /* Empfang zusaetzlich als Hex */

static uint32_t rxCount = 0, txCount = 0;

static void blink(int pin, int ms)
{
    digitalWrite(pin, HIGH);
    delay(ms);
    digitalWrite(pin, LOW);
}

static void applyRadio()
{
    LoRa.idle();
    LoRa.setFrequency(cfgFreq);
    LoRa.setSpreadingFactor(cfgSf);
    LoRa.setSignalBandwidth(cfgBw);
    LoRa.setCodingRate4(cfgCr);
    LoRa.setPreambleLength(cfgPre);
    LoRa.setSyncWord(cfgSync);
    LoRa.setTxPower(cfgPower, PA_OUTPUT_PA_BOOST_PIN);
    if (cfgCrc) LoRa.enableCrc(); else LoRa.disableCrc();
    if (rxEnabled) LoRa.receive();
}

static void printCfg()
{
    Serial.printf("FREQ=%ld\r\n",   cfgFreq);
    Serial.printf("SF=%d\r\n",      cfgSf);
    Serial.printf("BW=%ld\r\n",     cfgBw);
    Serial.printf("CR=4/%d\r\n",    cfgCr);
    Serial.printf("POWER=%d\r\n",   cfgPower);
    Serial.printf("SYNCWORD=0x%02X\r\n", cfgSync);
    Serial.printf("PREAMBLE=%d\r\n", cfgPre);
    Serial.printf("CRC=%d\r\n",     cfgCrc ? 1 : 0);
    Serial.printf("RX=%d\r\n",      rxEnabled ? 1 : 0);
    Serial.printf("TXCNT=%lu RXCNT=%lu\r\n",
                  (unsigned long)txCount, (unsigned long)rxCount);
}

static void sendPacket(const uint8_t *buf, size_t len)
{
    LoRa.idle();
    LoRa.beginPacket();
    LoRa.write(buf, len);
    LoRa.endPacket();
    txCount++;
    blink(LED_BLUE, 30);
    if (rxEnabled) LoRa.receive();
    Serial.printf("+SEND: OK %u Byte\r\n", (unsigned)len);
}

static int hexVal(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

/* "AT+X=wert" -> gibt Zeiger auf "wert" oder NULL */
static const char *argOf(const String &line, const char *cmd)
{
    size_t n = strlen(cmd);
    if (!line.startsWith(cmd)) return NULL;
    if (line.length() == n) return "";
    if (line[n] != '=') return NULL;
    return line.c_str() + n + 1;
}

static void bootLoRaWAN()
{
    const esp_partition_t *p =
        esp_partition_find_first(ESP_PARTITION_TYPE_APP,
                                 ESP_PARTITION_SUBTYPE_APP_OTA_0, NULL);
    if (!p) { Serial.println("AT_ERROR: app0 nicht gefunden"); return; }
    esp_err_t e = esp_ota_set_boot_partition(p);
    if (e != ESP_OK) { Serial.printf("AT_ERROR: %d\r\n", e); return; }
    Serial.println("OK - starte LoRaWAN-Firmware (app0)");
    Serial.flush();
    delay(200);
    esp_restart();
}

static void handleLine(String line)
{
    line.trim();
    if (!line.length()) return;
    const char *a;

    if (line == "AT")                       { Serial.println("OK"); return; }
    if (line == "AT+VER=?" || line == "AT+VER") { Serial.println(FW_VERSION); return; }
    if (line == "AT+CFG")                   { printCfg(); Serial.println("OK"); return; }
    if (line == "AT+LORAWAN")               { bootLoRaWAN(); return; }
    if (line == "ATZ")                      { Serial.println("OK"); Serial.flush(); esp_restart(); }

    if ((a = argOf(line, "AT+FRE"))) {
        if (!*a) { Serial.printf("%ld\r\nOK\r\n", cfgFreq); return; }
        double mhz = atof(a);
        cfgFreq = (mhz < 10000) ? (long)(mhz * 1000000.0 + 0.5) : atol(a);
        applyRadio(); Serial.printf("FREQ=%ld\r\nOK\r\n", cfgFreq); return;
    }
    if ((a = argOf(line, "AT+SF"))) {
        if (!*a) { Serial.printf("%d\r\nOK\r\n", cfgSf); return; }
        int v = atoi(a);
        if (v < 6 || v > 12) { Serial.println("AT_PARAM_ERROR"); return; }
        cfgSf = v; applyRadio(); Serial.println("OK"); return;
    }
    if ((a = argOf(line, "AT+BW"))) {
        if (!*a) { Serial.printf("%ld\r\nOK\r\n", cfgBw); return; }
        long v = atol(a);
        if (v < 10000) v *= 1000;           /* "125" wie "125000" nehmen */
        cfgBw = v; applyRadio(); Serial.println("OK"); return;
    }
    if ((a = argOf(line, "AT+CR"))) {
        if (!*a) { Serial.printf("4/%d\r\nOK\r\n", cfgCr); return; }
        int v = atoi(a);
        if (v >= 1 && v <= 4) v += 4;       /* 1..4 wie bei Dragino */
        if (v < 5 || v > 8) { Serial.println("AT_PARAM_ERROR"); return; }
        cfgCr = v; applyRadio(); Serial.println("OK"); return;
    }
    if ((a = argOf(line, "AT+POWER"))) {
        if (!*a) { Serial.printf("%d\r\nOK\r\n", cfgPower); return; }
        int v = atoi(a);
        if (v < 2 || v > 20) { Serial.println("AT_PARAM_ERROR"); return; }
        cfgPower = v; applyRadio(); Serial.println("OK"); return;
    }
    if ((a = argOf(line, "AT+SYNCWORD"))) {
        if (!*a) { Serial.printf("0x%02X\r\nOK\r\n", cfgSync); return; }
        cfgSync = (int)strtol(a, NULL, 0) & 0xFF;
        applyRadio(); Serial.println("OK"); return;
    }
    if ((a = argOf(line, "AT+PREAMBLE"))) {
        if (!*a) { Serial.printf("%d\r\nOK\r\n", cfgPre); return; }
        cfgPre = atoi(a); applyRadio(); Serial.println("OK"); return;
    }
    if ((a = argOf(line, "AT+CRC"))) {
        if (!*a) { Serial.printf("%d\r\nOK\r\n", cfgCrc); return; }
        cfgCrc = atoi(a) != 0; applyRadio(); Serial.println("OK"); return;
    }
    if ((a = argOf(line, "AT+RX"))) {
        if (!*a) { Serial.printf("%d\r\nOK\r\n", rxEnabled); return; }
        rxEnabled = atoi(a) != 0;
        if (rxEnabled) LoRa.receive(); else LoRa.idle();
        Serial.println("OK"); return;
    }
    if ((a = argOf(line, "AT+HEX"))) {
        hexOut = atoi(a) != 0; Serial.println("OK"); return;
    }
    if ((a = argOf(line, "AT+SEND"))) {
        if (!*a) { Serial.println("AT_PARAM_ERROR"); return; }
        sendPacket((const uint8_t *)a, strlen(a)); return;
    }
    if ((a = argOf(line, "AT+SENDB"))) {
        size_t n = strlen(a);
        if (!n || (n & 1)) { Serial.println("AT_PARAM_ERROR"); return; }
        uint8_t buf[255];
        size_t len = 0;
        for (size_t i = 0; i + 1 < n && len < sizeof(buf); i += 2) {
            int hi = hexVal(a[i]), lo = hexVal(a[i + 1]);
            if (hi < 0 || lo < 0) { Serial.println("AT_PARAM_ERROR"); return; }
            buf[len++] = (uint8_t)((hi << 4) | lo);
        }
        sendPacket(buf, len); return;
    }
    Serial.println("AT_ERROR");
}

void setup()
{
    Serial.begin(115200);
    pinMode(LED_RED, OUTPUT);
    pinMode(LED_BLUE, OUTPUT);
    pinMode(LED_GREEN, OUTPUT);
    digitalWrite(LED_RED, LOW);
    digitalWrite(LED_BLUE, LOW);
    digitalWrite(LED_GREEN, LOW);

    delay(200);
    Serial.println();
    Serial.println(FW_VERSION);

    SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_NSS);
    LoRa.setPins(PIN_NSS, PIN_RST, PIN_DIO0);
    if (!LoRa.begin(cfgFreq)) {
        Serial.println("AT_ERROR: SX1276 antwortet nicht");
        while (1) { blink(LED_RED, 200); delay(200); }
    }
    applyRadio();
    printCfg();
    Serial.println("bereit - AT+CFG zeigt alles, AT+LORAWAN geht zurueck");
}

void loop()
{
    static String line;
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') { handleLine(line); line = ""; }
        else if (line.length() < 300) line += c;
    }

    int sz = LoRa.parsePacket();
    if (sz > 0) {
        uint8_t buf[256];
        int len = 0;
        while (LoRa.available() && len < (int)sizeof(buf) - 1)
            buf[len++] = (uint8_t)LoRa.read();
        buf[len] = 0;
        rxCount++;
        Serial.printf("+RX: len=%d rssi=%d snr=%.1f \"%s\"",
                      len, LoRa.packetRssi(), LoRa.packetSnr(), (char *)buf);
        if (hexOut) {
            Serial.print(" hex=");
            for (int i = 0; i < len; i++) Serial.printf("%02X", buf[i]);
        }
        Serial.println();
        blink(LED_GREEN, 30);
    }
}
