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
#include <esp_system.h>

#define FW_VERSION "TrackerD-P2P v2.9"

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

/* Der rote Alarmknopf: **GPIO 0, active LOW.**
 *
 * Ueber die Luft ausgemessen (AT+BTN funkt die Pinmaske, der Pico hoert mit):
 *   Ruhe      01011000   GPIO0 = 1
 *   gedrueckt 00011000   GPIO0 = 0
 * Einzige Aenderung, alle anderen Pins unveraendert. Passt zu
 * extiButton.h:9 BUTTON_PIN 0 und ESP_EXT1_WAKEUP_ALL_LOW.
 *
 * Am Pin haengt ein externer Pullup (Boot-Strapping), Ruhe ist deshalb HIGH.
 *
 * **Nur ueber Funk messbar.** Solange der USB-Port offen ist, treibt die
 * Auto-Reset-Schaltung GPIO 0 ueber DTR und verdeckt den Knopf vollstaendig --
 * jede serielle Messung zeigt dann entweder Rauschen oder einen konstanten
 * Pegel. Genau daran sind alle Versuche ueber die Konsole gescheitert.
 *
 * Nicht 25: das ist GPS_RESET (GPS.h:7). extiButtonLS.h nennt zwar
 * BUTTON_PIN1 25, das gilt an diesem Geraet nicht. */
#define PIN_BUTTON 0

/* Haltezeit bis zum Alarm. Dragino nimmt dafuer sys.exit_alarm_time, in
 * TrackerD.ino:1301 auf 2000 ms gesetzt -- derselbe Wert, damit der Knopf
 * sich in beiden Firmwares gleich anfuehlt. Ein kurzer Druck tut auch dort
 * nichts (attachClick ist auskommentiert). */
#define ALARM_HOLD_MS 2000

/* Defaults. Gesendet wird ab Werk auf **beiden** Profilen (cfgEbyte weiter
 * unten), empfangen dagegen immer nur auf einem -- der Funk kann zu einer Zeit
 * nur ein SF/BW/Syncword. Die Werte hier sind deshalb das Empfangsprofil, und
 * das ist das Ebyte-Profil: das E90-DTU ist die naehere Gegenstelle, und der
 * Rohkanal wird ohnehin vom Gateway mitgehoert.
 *
 * Umschalten: AT+EBYTE=0 (nur Rohkanal), =1 (nur Ebyte), =2 (beides).
 *
 * Die Konfiguration lebt nur im RAM, deshalb muessen die Werte hier stehen
 * und koennen nicht per AT nachgereicht werden -- sie waeren nach jedem Reset
 * wieder weg. */
static long     cfgFreq   = 868125000;
static int      cfgSf     = 11;
static long     cfgBw     = 500000;
static int      cfgCr     = 5;      /* 5..8 entspricht 4/5..4/8 */
static int      cfgPower  = 17;     /* dBm, PA_BOOST */
static int      cfgSync   = 0x58;
static int      cfgPre    = 8;
static bool     cfgCrc    = true;
static bool     rxEnabled = true;
static bool     hexOut    = false;  /* Empfang zusaetzlich als Hex */
/* Absenderkennung, vier Hexstellen. Vorgabe sind die letzten vier Stellen der
 * DevEUI A840414F1188076C - damit ist sie ohne Vergabeliste eindeutig. Muss
 * gueltiges Hex sein, sonst liest das Relais den Rahmen als "ohne Kennung". */
static char     cfgId[5]  = "076C";
static bool     cfgImplicit = false;   /* impliziter Header (feste Laenge) */
static int      cfgImplicitLen = 32;

/* LDRO: -1 = automatisch wie die Bibliothek es rechnet, 0/1 = erzwungen.
 * Muss zum Empfangsprofil oben passen, und das ist das Ebyte-Profil: dort ist
 * LDRO 1, obwohl die Symboldauer unter 16 ms liegt und die Bibliothek von
 * selbst auf 0 kaeme. Beim Senden setzt funkProfil() es ohnehin je Profil. */
static int      cfgLdro   = 1;

/* Betriebsart: 0 = nur Rohkanal, 1 = nur Ebyte, 2 = beides nacheinander.
 *
 * Die beiden Netze schliessen sich am Syncword aus und lassen sich nicht
 * vereinen: Ebyte liegt ab Werk auf 0x58, der SX1302 des DLOS8N kennt nur ein
 * Syncword fuer den ganzen Chip und dort nur 0x34 oder 0x12 (RAWKANAL.md).
 * SF und Bandbreite koennte man am Gateway nachziehen, das Syncword nicht.
 *
 * Deshalb Modus 2 als Vorgabe: dieselbe Nachricht geht zweimal raus, einmal
 * fuer das Gateway und einmal fuer das E90. Das kostet Luftzeit, ist aber der
 * einzige Weg, beide Wege offen zu halten. */
#define SENDE_ROH    0
#define SENDE_EBYTE  1
#define SENDE_BEIDE  2
static int      cfgEbyte  = SENDE_BEIDE;

/* Rohkanal (DLOS8N chan_Lora_std, Relais Brauneck) */
#define ROH_SF    7
#define ROH_BW    125000L
#define ROH_SYNC  0x34
/* E90-DTU(900SL33), an der Luft ausgemessen */
#define EBY_SF    11
#define EBY_BW    500000L
#define EBY_SYNC  0x58

/* Pin-Diagnose (AT+BTN). Der Zustand liegt auf Dateiebene, weil die Abtastung
 * aus loop() kommt und nicht aus handleLine(): ein sekundenlang blockierender
 * AT-Befehl laesst loop() nie zurueckkehren und der Task-Watchdog setzt das
 * Geraet zurueck (rst:0x8 TG1WDT_SYS_RESET). Genau daran sind die ersten
 * Messlaeufe gescheitert -- sie lieferten deshalb gar keine Ausgabe. */
/* 16 und 17 sind hier RAUS: auf dem ESP32-PICO-D4 haengen sie am internen
 * Speicher. Ein pinMode() darauf laesst die Firmware sofort mit
 * Interrupt-Watchdog neu starten (Neustartgrund 5) -- das Geraet kam nicht
 * einmal bis zur Startmeldung und funkte deshalb gar nichts.
 * Ebenfalls raus: 12 (GPS_POWER), 4/34/35 (Batterie), 6-11 (Flash). */
static const int btnPins[] = { 25, 0, 14, 21, 22, 32, 33, 36 };
#define BTN_ANZAHL (int)(sizeof(btnPins) / sizeof(btnPins[0]))
static uint32_t btnBis = 0, btnNaechste = 0;

/* Pin-Zustaende ueber die Luft melden, statt ueber die serielle Schnittstelle.
 * Grund: schon das Oeffnen des USB-Ports setzt den ESP32 ueber die
 * Auto-Reset-Leitungen zurueck -- jedes serielle Kommando landete deshalb im
 * Bootvorgang. Ueber Funk gemessen faellt das ganze Problem weg.
 *
 * Gesendet wird auf dem Rohkanal (SF7/BW125), nicht im Ebyte-Profil: rund
 * 40 ms Luftzeit statt ueber 300 ms. Das Fenster ist bewusst kurz, damit der
 * Duty Cycle im 868er Band nicht ueber Gebuehr belastet wird. */
#define PINTX_INTERVALL 2000UL
#define PINTX_FENSTER   300000UL   /* 5 min: lang genug, dass das Fenster nicht mitten im Test ablaeuft */
static uint32_t pinTxBis = 0, pinTxNaechste = 0;

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
    /* Nach SF und Bandbreite, weil beide das LDRO-Bit neu berechnen. */
    if (cfgLdro >= 0) LoRa.forceLdo(cfgLdro != 0);
    if (rxEnabled) LoRa.receive(cfgImplicit ? cfgImplicitLen : 0);
}

static void printCfg()
{
    Serial.printf("FREQ=%ld\r\n",   cfgFreq);
    Serial.printf("SF=%d\r\n",      cfgSf);
    Serial.printf("BW=%ld\r\n",     cfgBw);
    Serial.printf("CR=4/%d\r\n",    cfgCr);
    Serial.printf("POWER=%d\r\n",   cfgPower);
    Serial.printf("ID=%s\r\n",      cfgId);
    Serial.printf("SYNCWORD=0x%02X\r\n", cfgSync);
    Serial.printf("PREAMBLE=%d\r\n", cfgPre);
    Serial.printf("CRC=%d\r\n",     cfgCrc ? 1 : 0);
    Serial.printf("IH=%d PLEN=%d\r\n", cfgImplicit ? 1 : 0, cfgImplicitLen);
    Serial.printf("RX=%d\r\n",      rxEnabled ? 1 : 0);
    Serial.printf("LDRO=%s\r\n",    cfgLdro < 0 ? "auto" : (cfgLdro ? "1" : "0"));
    Serial.printf("EBYTE=%d (%s)\r\n", cfgEbyte,
                  cfgEbyte == SENDE_BEIDE ? "roh+Ebyte" :
                  (cfgEbyte == SENDE_EBYTE ? "nur Ebyte" : "nur roh"));
    Serial.printf("TXCNT=%lu RXCNT=%lu\r\n",
                  (unsigned long)txCount, (unsigned long)rxCount);
}

/* Jedes Paket traegt "IIII>" voran. Der Praefix sitzt hier und nicht in den
 * einzelnen AT-Befehlen, damit AT+SEND und AT+SENDB ihn gleichermassen
 * bekommen. AT+TXTEST bleibt bewusst aussen vor: das ist ein rohes Messmuster
 * fuer die RSSI-Messung der Gegenstelle, keine Nachricht. */
/* Rahmen des E90-DTU. Aufbau und Pruefsummenregel sind an zwei Geraeten
 * ausgemessen, siehe ../pico_sx1262/EBYTE_E90.md:
 *
 *     2c 12 XX YY NN HH LL SS | Nutzlast XOR 0x12
 *
 * XX ist das XOR ueber die Klartext-Nutzlast, danach ^ 0xA0; YY ist XX ^ 0xA1.
 * Ein Rahmen mit falschem XX wird verworfen.
 *
 * NN ist die NETID und muss 0 sein: der Repeater leitet gemessen nur weiter,
 * wenn sie mit seiner eigenen uebereinstimmt (3/3 bei 0x00, 0/3 bei allen
 * anderen). Die Adresse HH LL ist ihm dagegen gleichgueltig. */
static size_t ebyteWrap(const uint8_t *in, size_t len, uint8_t *out, size_t cap)
{
    if (len > 240) len = 240;
    if (len + 8 > cap) len = cap - 8;
    uint8_t x = 0;
    for (size_t i = 0; i < len; i++) x ^= in[i];
    uint8_t xx = (uint8_t)(x ^ 0xA0);
    out[0] = 0x2C; out[1] = 0x12;
    out[2] = xx;   out[3] = (uint8_t)(xx ^ 0xA1);
    out[4] = 0x00;                 /* NETID 0, sonst leitet der Repeater nicht */
    out[5] = 0x00; out[6] = 0x00;  /* Adresse, fuer den Repeater belanglos */
    out[7] = (uint8_t)len;
    for (size_t i = 0; i < len; i++) out[8 + i] = (uint8_t)(in[i] ^ 0x12);
    return len + 8;
}

/* Funk auf eines der beiden Profile stellen. LDRO muss nach SF und Bandbreite
 * kommen, weil beide es neu berechnen. */
static void funkProfil(int sf, long bw, int sync, bool ldro)
{
    LoRa.idle();
    LoRa.setSpreadingFactor(sf);
    LoRa.setSignalBandwidth(bw);
    LoRa.setSyncWord(sync);
    LoRa.forceLdo(ldro);
}

static void einmalSenden(const uint8_t *daten, size_t len)
{
    LoRa.beginPacket();
    LoRa.write(daten, len);
    LoRa.endPacket();
    txCount++;
}

static void sendPacket(const uint8_t *buf, size_t len)
{
    uint8_t out[255];
    size_t hdr = 0;
    for (const char *p = cfgId; *p; ++p) out[hdr++] = (uint8_t)*p;
    out[hdr++] = '>';
    if (len > sizeof(out) - hdr) len = sizeof(out) - hdr;
    memcpy(out + hdr, buf, len);

    /* Im Ebyte-Rahmen wandert das fertige Paket samt Absenderkennung als
     * Nutzlast hinein -- die Kennung bleibt so erhalten. */
    uint8_t roh[255];
    size_t  rohLen = ebyteWrap(out, hdr + len, roh, sizeof(roh));

    LoRa.idle();
    if (cfgEbyte == SENDE_ROH || cfgEbyte == SENDE_BEIDE) {
        funkProfil(ROH_SF, ROH_BW, ROH_SYNC, false);
        einmalSenden(out, hdr + len);
    }
    if (cfgEbyte == SENDE_EBYTE || cfgEbyte == SENDE_BEIDE) {
        funkProfil(EBY_SF, EBY_BW, EBY_SYNC, true);
        einmalSenden(roh, rohLen);
    }
    /* Danach steht der Funk auf dem zuletzt benutzten Profil -- im
     * Doppelbetrieb also auf Ebyte. Empfangen wird immer nur auf einem. */
    blink(LED_BLUE, 30);
    if (rxEnabled) LoRa.receive(cfgImplicit ? cfgImplicitLen : 0);
    Serial.printf("+SEND: OK %s (Kennung %s)\r\n",
                  cfgEbyte == SENDE_BEIDE ? "roh + Ebyte"
                    : (cfgEbyte == SENDE_EBYTE ? "Ebyte" : "roh"), cfgId);
}

/* Alarm senden. Geht durch sendPacket, bekommt also die Absenderkennung
 * "IIII>" wie jedes andere Paket -- das Relais wertet sie aus. */
static void sendeAlarm(const char *grund)
{
    digitalWrite(LED_RED, HIGH);
    sendPacket((const uint8_t *)"ALARM", 5);
    Serial.printf("+ALARM: gesendet (%s)\r\n", grund);
    delay(150);
    digitalWrite(LED_RED, LOW);
}

/* Den Knopf pollen statt per Interrupt: die Haltezeit muss ohnehin gemessen
 * werden, und aus einer ISR heraus zu senden waere hier falsch. Der Aufruf
 * kommt aus loop() und darf nicht blockieren. */
static void pruefeKnopf()
{
    static bool     letzter    = false;
    static uint32_t seitWann   = 0;
    static bool     gemeldet   = false;

    bool gedrueckt = (digitalRead(PIN_BUTTON) == LOW);   /* active low */

    if (gedrueckt != letzter) {
        /* Jede Flanke setzt die Uhr zurueck. Das entprellt zugleich: waehrend
         * es prellt, kommt die Haltezeit nie zustande. */
        letzter  = gedrueckt;
        seitWann = millis();
        if (!gedrueckt) gemeldet = false;   /* erst nach Loslassen wieder scharf */
        return;
    }
    if (!gedrueckt || gemeldet) return;
    if (millis() - seitWann < ALARM_HOLD_MS) return;

    gemeldet = true;                        /* genau ein Alarm je Druck */
    sendeAlarm("Knopf");
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
    if ((a = argOf(line, "AT+ID"))) {
        if (!*a) { Serial.printf("%s\r\nOK\r\n", cfgId); return; }
        if (strlen(a) != 4) { Serial.println("AT_PARAM_ERROR"); return; }
        for (int i = 0; i < 4; i++) {
            if (hexVal(a[i]) < 0) { Serial.println("AT_PARAM_ERROR"); return; }
            cfgId[i] = (a[i] >= 'a' && a[i] <= 'f') ? a[i] - 32 : a[i];
        }
        cfgId[4] = 0;
        Serial.printf("ID=%s\r\nOK\r\n", cfgId); return;
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
    if ((a = argOf(line, "AT+SCAN"))) {
        /* Rohes RSSI mitschreiben. Zeigt Traeger auch dann, wenn die
         * Demodulation scheitert - trennt "nichts kommt an" von
         * "kommt an, aber falsche Modulationsparameter". */
        int secs = *a ? atoi(a) : 5;
        if (secs < 1) secs = 1;
        if (secs > 60) secs = 60;
        LoRa.receive();
        int mn = 999, mx = -999;
        long sum = 0, n = 0;
        uint32_t t0 = millis();
        while (millis() - t0 < (uint32_t)secs * 1000) {
            int r = LoRa.rssi();
            if (r < mn) mn = r;
            if (r > mx) mx = r;
            sum += r; n++;
            delay(20);
        }
        Serial.printf("+SCAN: freq=%ld bw=%ld n=%ld min=%d max=%d avg=%.1f\r\n",
                      cfgFreq, cfgBw, n, mn, mx, n ? (double)sum / n : 0.0);
        Serial.println("OK");
        return;
    }
    if ((a = argOf(line, "AT+BURST"))) {
        /* Misst die Laenge der Energiepakete statt sie zu dekodieren.
         * Die Symbolzeit ist 2^SF/BW, die Sendedauer skaliert damit
         * direkt mit SF und BW - aus der Burstlaenge laesst sich also
         * ablesen, womit die Gegenstelle moduliert. */
        int secs = *a ? atoi(a) : 10;
        if (secs < 1) secs = 1;
        if (secs > 60) secs = 60;
        LoRa.receive();
        const int thresh = -90;
        bool in = false;
        uint32_t start = 0;
        int peak = -999, bursts = 0;
        uint32_t t0 = millis();
        Serial.printf("+BURST: Schwelle %d dBm, %d s\r\n", thresh, secs);
        while (millis() - t0 < (uint32_t)secs * 1000) {
            int r = LoRa.rssi();
            if (!in && r > thresh) {
                in = true; start = millis(); peak = r;
            } else if (in) {
                if (r > peak) peak = r;
                if (r <= thresh) {
                    uint32_t len = millis() - start;
                    in = false;
                    if (len >= 3 && bursts < 40) {
                        Serial.printf("  burst %2d: %4lu ms, peak %d dBm\r\n",
                                      ++bursts, (unsigned long)len, peak);
                    }
                }
            }
        }
        Serial.printf("+BURST: %d Pakete\r\nOK\r\n", bursts);
        return;
    }
    if ((a = argOf(line, "AT+IRQ"))) {
        /* Rohe Modem-IRQ-Flags. ValidHeader ohne RxDone heisst: SF und BW
         * stimmen, es hakt danach. Gar kein Flag heisst: falsches SF/BW,
         * falsches Syncword oder impliziter Header. */
        int secs = *a ? atoi(a) : 10;
        if (secs < 1) secs = 1;
        if (secs > 60) secs = 60;
        LoRa.receive();
        uint8_t seen = 0;
        uint32_t t0 = millis();
        while (millis() - t0 < (uint32_t)secs * 1000) {
            uint8_t f = LoRa.readIrqFlags();
            if (f) { seen |= f; LoRa.clearIrqFlags(f); }
            delayMicroseconds(500);
        }
        Serial.printf("+IRQ: 0x%02X  rxtimeout=%d rxdone=%d crcerr=%d "
                      "validheader=%d caddetect=%d\r\n", seen,
                      !!(seen & 0x80), !!(seen & 0x40), !!(seen & 0x20),
                      !!(seen & 0x10), !!(seen & 0x01));
        Serial.println("OK");
        return;
    }
    if ((a = argOf(line, "AT+IH"))) {
        if (!*a) { Serial.printf("%d\r\nOK\r\n", cfgImplicit ? 1 : 0); return; }
        cfgImplicit = atoi(a) != 0;
        applyRadio(); Serial.println("OK"); return;
    }
    if ((a = argOf(line, "AT+PLEN"))) {
        if (!*a) { Serial.printf("%d\r\nOK\r\n", cfgImplicitLen); return; }
        cfgImplicitLen = atoi(a);
        applyRadio(); Serial.println("OK"); return;
    }
    if ((a = argOf(line, "AT+SEND"))) {
        if (!*a) { Serial.println("AT_PARAM_ERROR"); return; }
        sendPacket((const uint8_t *)a, strlen(a)); return;
    }
    if ((a = argOf(line, "AT+TXTEST"))) {
        /* Dauerfeuer, damit die Gegenstelle in Ruhe RSSI messen kann. */
        int secs = *a ? atoi(a) : 10;
        if (secs < 1) secs = 1;
        if (secs > 120) secs = 120;
        static const uint8_t pat[32] = {
            0x54, 0x52, 0x41, 0x43, 0x4B, 0x45, 0x52, 0x44,
            0x54, 0x52, 0x41, 0x43, 0x4B, 0x45, 0x52, 0x44,
            0x54, 0x52, 0x41, 0x43, 0x4B, 0x45, 0x52, 0x44,
            0x54, 0x52, 0x41, 0x43, 0x4B, 0x45, 0x52, 0x44 };
        uint32_t t0 = millis();
        int sent = 0;
        while (millis() - t0 < (uint32_t)secs * 1000) {
            LoRa.idle();
            LoRa.beginPacket();
            LoRa.write(pat, sizeof(pat));
            LoRa.endPacket();
            sent++; txCount++;
            digitalWrite(LED_BLUE, sent & 1);
        }
        digitalWrite(LED_BLUE, LOW);
        if (rxEnabled) LoRa.receive();
        Serial.printf("+TXTEST: %d Pakete in %d s\r\nOK\r\n", sent, secs);
        return;
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
    /* Ganzes Profil auf das E90-DTU umstellen bzw. zurueck auf den
     * Brauneck-Rohkanal. Einzeln liessen sich alle Werte auch per AT+SF,
     * AT+BW usw. setzen -- als Sammelbefehl ist es aber schwerer, einen davon
     * zu vergessen, und LDRO waere sonst gar nicht erreichbar. */
    if ((a = argOf(line, "AT+EBYTE"))) {
        if (*a == '1' || *a == '2') {
            cfgFreq = 868125000; cfgSf = EBY_SF; cfgBw = EBY_BW; cfgCr = 5;
            cfgSync = EBY_SYNC; cfgPre = 8; cfgCrc = true;
            cfgLdro = 1; cfgEbyte = (*a == '2') ? SENDE_BEIDE : SENDE_EBYTE;
        } else if (*a == '0') {
            cfgFreq = 868125000; cfgSf = ROH_SF; cfgBw = ROH_BW; cfgCr = 5;
            cfgSync = ROH_SYNC; cfgPre = 8; cfgCrc = true;
            cfgLdro = -1; cfgEbyte = SENDE_ROH;
        } else { Serial.println("AT_PARAM_ERROR"); return; }
        applyRadio();
        printCfg();
        Serial.println("OK");
        return;
    }
    /* Pin-Diagnose: mehrere Kandidaten gleichzeitig beobachten und jede
     * Aenderung melden. Der Knopfpin steht zwar in Draginos extiButtonLS
     * (GPIO 25), das gilt aber fuer deren Firmware -- ob er unter dieser
     * ohne die dortige Initialisierung genauso liegt, muss gemessen werden.
     * Die Kandidaten sind freie Pins; SPI (5,18,19,23,26,27), LEDs (2,13,15)
     * und Flash (6-11) bleiben aussen vor. */
    if ((a = argOf(line, "AT+BTN"))) {
        int secs = *a ? atoi(a) : 15;
        if (secs < 1) secs = 1;
        if (secs > 120) secs = 120;
        /* PULLDOWN, nicht PULLUP: Dragino gibt den Knopf als active high an
         * (ext1-Wakeup mit ESP_EXT1_WAKEUP_ANY_HIGH auf GPIO 25). Ein
         * active-high Knopf liest am Pullup gedrueckt wie losgelassen als 1 --
         * der Unterschied waere gar nicht messbar. */
        for (int i = 0; i < BTN_ANZAHL; i++) {
            int p = btnPins[i];
            pinMode(p, (p >= 34) ? INPUT : INPUT_PULLDOWN);
        }
        Serial.print("+BTN: Pins ");
        for (int i = 0; i < BTN_ANZAHL; i++) Serial.printf("%d ", btnPins[i]);
        Serial.printf("\r\n+BTN: %d s, alle 250 ms - druecken und halten\r\n", secs);
        btnBis = millis() + (uint32_t)secs * 1000;
        btnNaechste = millis();
        Serial.println("OK");
        return;
    }
    /* Denselben Alarm ohne Knopf ausloesen -- fuer Tests, wenn niemand am
     * Geraet steht. */
    if (!strcasecmp(line.c_str(), "AT+ALARM")) {
        sendeAlarm("AT+ALARM");
        Serial.println("OK");
        return;
    }
    Serial.println("AT_ERROR");
}

void setup()
{
    Serial.begin(115200);
    pinMode(LED_RED, OUTPUT);
    pinMode(LED_BLUE, OUTPUT);
    pinMode(LED_GREEN, OUTPUT);
    pinMode(PIN_BUTTON, INPUT_PULLUP);   /* active low, Ruhe HIGH */
    digitalWrite(LED_RED, LOW);
    digitalWrite(LED_BLUE, LOW);
    digitalWrite(LED_GREEN, LOW);

    delay(200);
    Serial.println();
    Serial.println(FW_VERSION);
    /* Neustartgrund im Klartext. Spart das Raten, wenn das Geraet mitten im
     * Betrieb neu startet: 6 = Task-Watchdog, 5 = Deep Sleep, 1 = Power-On,
     * 3 = Software, 4 = Interrupt-Watchdog, 12 = Brownout. */
    {
        static const char *grund[] = {
            "unbekannt", "Power-On", "extern", "Software", "Panik",
            "Interrupt-WDT", "Task-WDT", "WDT", "Deep-Sleep", "Brownout", "SDIO" };
        int r = (int)esp_reset_reason();
        Serial.printf("Neustartgrund: %d (%s)\r\n", r,
                      (r >= 0 && r <= 10) ? grund[r] : "?");
    }

    SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_NSS);
    LoRa.setPins(PIN_NSS, PIN_RST, PIN_DIO0);
    if (!LoRa.begin(cfgFreq)) {
        Serial.println("AT_ERROR: SX1276 antwortet nicht");
        while (1) { blink(LED_RED, 200); delay(200); }
    }
    applyRadio();
    printCfg();
    /* Diagnosefenster gleich beim Start, damit dafuer kein serielles
     * Kommando noetig ist -- das wuerde das Geraet nur wieder resetten. */
    for (int i = 0; i < BTN_ANZAHL; i++) {
        int p = btnPins[i];
        pinMode(p, (p >= 34) ? INPUT : INPUT_PULLDOWN);
    }
    pinTxBis = millis() + PINTX_FENSTER;
    pinTxNaechste = millis();
    Serial.printf("Pin-Funkdiagnose %lu s, Reihenfolge: ", PINTX_FENSTER / 1000);
    for (int i = 0; i < BTN_ANZAHL; i++) Serial.printf("%d ", btnPins[i]);
    Serial.println();
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

    /* Pin-Diagnose haeppchenweise, damit loop() zurueckkehrt und der
     * Watchdog ruhig bleibt. */
    if (btnBis) {
        if ((int32_t)(millis() - btnBis) >= 0) {
            btnBis = 0;
            Serial.println("+BTN: fertig");
        } else if ((int32_t)(millis() - btnNaechste) >= 0) {
            btnNaechste += 250;
            Serial.printf("+BTN %5lu ", (unsigned long)millis());
            for (int i = 0; i < BTN_ANZAHL; i++)
                Serial.print(digitalRead(btnPins[i]) ? '1' : '0');
            Serial.println();
        }
    }

    /* Pin-Zustaende funken, solange das Fenster laeuft. */
    if (pinTxBis) {
        if ((int32_t)(millis() - pinTxBis) >= 0) {
            pinTxBis = 0;
        } else if ((int32_t)(millis() - pinTxNaechste) >= 0) {
            pinTxNaechste = millis() + PINTX_INTERVALL;
            uint8_t maske = 0;
            for (int i = 0; i < BTN_ANZAHL; i++)
                if (digitalRead(btnPins[i])) maske |= (1 << i);
            char txt[16];
            snprintf(txt, sizeof(txt), "PIN%02X", maske);
            int alt = cfgEbyte;
            cfgEbyte = SENDE_ROH;          /* kurze Luftzeit fuer die Diagnose */
            sendPacket((const uint8_t *)txt, strlen(txt));
            cfgEbyte = alt;
        }
    }

    pruefeKnopf();

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
