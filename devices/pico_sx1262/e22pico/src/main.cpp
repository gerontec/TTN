// E22-Profil-Rohkanal auf dem Pico (Waveshare SX1262 am SPI) -- RadioLib.
//
// Spiegelt lora_p2p.py/ebyte868.py: 868.125 MHz, SF11/BW500/CR4/5, LDRO 1,
// Syncword 0x55 (Register 0x0740 = 54 54), Praeambel 8, 14 dBm, dazu das
// Ebyte-Rahmenformat (Magic 2c 12, Pruefbytes, Zieladresse, XOR 0x12).
//
// Empfang eng nach RadioLib-Beispiel SX126x_PingPong: DIO1-Interrupt setzt
// eine Flagge, loop() liest das Paket mit readData() und antwortet sofort
// mit einem Ebyte-gerahmten Zeitstempel (PONG).
//
// USB-Kommandos: diag | tx | boot
//   boot springt in den ROM-Bootloader (RPI-RP2-Laufwerk fuer firmware.uf2).

#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <stdarg.h>

extern "C" {
#include "pico/bootrom.h"
}

// Alle LoRa-Parameter liegen in loraparms.h -- nach jedem Start (auch nach
// Stromausfall) gelten ausschliesslich diese Werte.
#include "loraparms.h"

static const uint8_t ZIEL[3] = ADRESSE;          // NETID 00 + Rundruf FFFF
static const uint8_t ZIEL_BB[3] = ADRESSE_NETIDBB; // NETID BB + Rundruf FFFF

MbedSPI spi(PIN_MISO, PIN_MOSI, PIN_SCK);

// RadioLib haelt die Diagnose-API protected; fuer die Fehlersuche offen.
class SX1262Offen : public SX1262 {
 public:
  SX1262Offen(Module* mod) : SX1262(mod) {}
  using SX126x::readRegister;
  using SX126x::getPacketType;
  using SX126x::getStatus;
  using SX126x::getDeviceErrors;
};

SX1262Offen radio = new Module(PIN_CS, PIN_DIO1, PIN_RST, PIN_BUSY, spi);

static unsigned long empfangen = 0, beantwortet = 0;
volatile bool operationDone = false;    // von setFlag() gesetzt
static bool transmitFlag = false;       // letzte Operation war eine Antwort
static int transmissionState = RADIOLIB_ERR_NONE;

// Antworten warten PONG_VERZOEGERUNG_MS, bis die Taubheit des E22 nach
// seiner eigenen Aussendung vorbei ist. Kleine Schlange fuer Serien.
struct AntwortSlot {
  unsigned long faellig;
  uint8_t rahmen[128];
  size_t len;
};
static AntwortSlot antworten[8];
static uint8_t antwortAnzahl = 0;

// Wird vom DIO1-Interrupt gerufen, wenn TX oder TX fertig ist.
static void setFlag(void) { operationDone = true; }

// Die mbed-UART hat kein printf; ein eigener Umweg ueber vsnprintf.
static void sag(const char* fmt, ...) {
  char buf[192];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  Serial.print(buf);
}

// adresse[3] = NETID, ZH, ZL. Vorgabe ist NETID 00 + Rundruf FFFF.
static size_t ebyteRahmen(const char* text, uint8_t* out,
                          const uint8_t* adresse = ZIEL) {
  size_t n = strlen(text);
  uint8_t xx = 0;
  for (size_t i = 0; i < n; i++) xx ^= (uint8_t)text[i];
  xx ^= 0xA0;
  size_t p = 0;
  out[p++] = MAGIC0;
  out[p++] = MAGIC1;
  out[p++] = xx;
  out[p++] = xx ^ 0xA1;
  out[p++] = adresse[0];
  out[p++] = adresse[1];
  out[p++] = adresse[2];
  out[p++] = (uint8_t)n;
  for (size_t i = 0; i < n; i++) out[p++] = (uint8_t)text[i] ^ XORKEY;
  return p;
}

static bool ebyteEntpacken(const uint8_t* roh, size_t len, char* out, size_t outsz) {
  if (len < 9 || roh[0] != MAGIC0 || roh[1] != MAGIC1) return false;
  size_t n = roh[7];
  if (len < 8 + n || n >= outsz) return false;
  uint8_t xx = 0;
  for (size_t i = 0; i < n; i++) {
    out[i] = (char)(roh[8 + i] ^ XORKEY);
    xx ^= (uint8_t)out[i];
  }
  out[n] = 0;
  return roh[2] == (uint8_t)(xx ^ 0xA0);
}

// Der SX126x hat kein Versionsregister wie der SX127x (dort 0x42 -> 0x12).
// Identifiziert wird ueber GetStatus, GetDeviceErrors und lesbare Register.
static void diag() {
  uint8_t sw[2] = {0, 0};
  radio.readRegister(0x0740, sw, 2);
  sag("diag: Status 0x%02X  DeviceErrors 0x%04X  PacketType 0x%02X  "
      "SyncReg 0x0740 = %02X %02X\n",
      radio.getStatus(), radio.getDeviceErrors(), radio.getPacketType(),
      sw[0], sw[1]);
  sag("diag: IRQ 0x%08lX\n", (unsigned long)radio.getIrqFlags());
}

void setup() {
  Serial.begin(115200);
  delay(2000);                  // USB-CDC erst bereit werden lassen

  spi.begin();
  int state = radio.begin(FREQ_MHZ, BW_KHZ, LORA_SF, LORA_CR, SYNCWORD,
                          POWER_DBM, PREAMBLE, TCXO_V);
  if (state != RADIOLIB_ERR_NONE) {
    sag("SX1262 begin fehlgeschlagen: %d\n", state);
    while (true) delay(1000);
  }
  // Beide Board-Fallen aus lora_p2p.py: DIO2 steuert den Antennenschalter,
  // und LDRO muss 1 sein (Ebyte-Werkswert; die Automatik kaeme auf 0 und
  // dann rastet nur der Header ein, waehrend jede Nutzlast CRC-Fehler hat).
  radio.setDio2AsRfSwitch(true);
  radio.forceLDRO(LDRO_ON);

  // Nach jedem Start (auch nach Stromausfall) die Parameter aus loraparms.h
  // einmal funken -- der Gateway hoert mit und traegt sie in die DB ein.
  char parm[96];
  snprintf(parm, sizeof(parm),
           "PARM %.3fMHz SF%d BW%.0f CR4/%d SYNC%02X LDRO%d PRE%d %ddBm",
           FREQ_MHZ, LORA_SF, BW_KHZ, LORA_CR, SYNCWORD, LDRO_ON ? 1 : 0,
           PREAMBLE, POWER_DBM);
  uint8_t rahmen[128];
  size_t n = ebyteRahmen(parm, rahmen);
  int pstate = radio.transmit(rahmen, n);
  sag("PARAMETER gefunkt: %s (%s)\n", parm,
      pstate == RADIOLIB_ERR_NONE ? "ok" : "FEHLER");

  radio.setDio1Action(setFlag);        // Interrupt auf DIO1
  state = radio.startReceive();        // Dauerverempfang
  if (state != RADIOLIB_ERR_NONE) {
    sag("startReceive fehlgeschlagen: %d\n", state);
    while (true) delay(1000);
  }

  sag("E22-Profil aktiv: %.3f MHz SF%d BW%.0f CR4/%d LDRO1 Sync 0x%02X %d dBm\n",
      FREQ_MHZ, LORA_SF, BW_KHZ, LORA_CR, SYNCWORD, POWER_DBM);
  Serial.println("warte auf Pakete -- Antwort je Paket mit Zeitstempel");
  Serial.println("Kommandos: diag | tx | boot");
  diag();
}

void loop() {
  static unsigned long letzterPuls = 0;

  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "boot") {
      Serial.println("springe in den Bootloader...");
      Serial.flush();
      delay(50);
      reset_usb_boot(0, 0);
    } else if (cmd == "diag") {
      diag();
    } else if (cmd == "tx") {
      char text[64];
      snprintf(text, sizeof(text), "CTEST t=%lu ms", (unsigned long)millis());
      uint8_t rahmen[96];
      size_t n = ebyteRahmen(text, rahmen);
      radio.standby();
      int txstate = radio.transmit(rahmen, n);
      sag("tx %s: %s\n", text, txstate == RADIOLIB_ERR_NONE ? "ok" : "FEHLER");
      radio.startReceive();
    }
  }

  if (millis() - letzterPuls >= 30000) {
    letzterPuls = millis();
    sag("alive: %lu empfangen, %lu beantwortet, %u in Schlange\n",
        empfangen, beantwortet, antwortAnzahl);
  }

  // Faellige Antwort senden, falls der Sender frei ist.
  if (!transmitFlag && antwortAnzahl > 0 &&
      (long)(millis() - antworten[0].faellig) >= 0) {
    AntwortSlot s = antworten[0];
    for (uint8_t i = 1; i < antwortAnzahl; i++) antworten[i - 1] = antworten[i];
    antwortAnzahl--;
    transmissionState = radio.startTransmit(s.rahmen, s.len);
    if (transmissionState == RADIOLIB_ERR_NONE) {
      transmitFlag = true;
    } else {
      sag("  -> Antwort TX FEHLER %d\n", transmissionState);
      radio.startReceive();
    }
  }

  if (!operationDone) return;
  operationDone = false;

  if (transmitFlag) {
    // Die Zeitstempel-Antwort ist raus -- wieder hoeren.
    transmitFlag = false;
    if (transmissionState == RADIOLIB_ERR_NONE) {
      beantwortet++;
    } else {
      sag("  -> Antwort TX FEHLER %d\n", transmissionState);
    }
    radio.startReceive();
    return;
  }

  // Ein Paket kam herein.
  empfangen++;
  size_t len = radio.getPacketLength();
  uint8_t buf[256];
  if (len > sizeof(buf)) len = sizeof(buf);
  int state = radio.readData(buf, len);
  float rssi = radio.getRSSI();
  float snr = radio.getSNR();

  sag("RX #%lu RSSI %.0f dBm SNR %.1f dB %u B:",
      empfangen, rssi, snr, (unsigned)len);
  for (size_t i = 0; i < len; i++) sag(" %02x", buf[i]);
  Serial.println();

  if (state == RADIOLIB_ERR_NONE) {
    char nutz[128];
    if (ebyteEntpacken(buf, len, nutz, sizeof(nutz))) {
      sag("  Ebyte-Rahmen ok: %s\n", nutz);
    }
    // Antwort zweifach einplanen: NETID 00 und NETID BB, je Rundruf FFFF.
    // Die Verzoegerung wartet die Taubheit des Senders nach seiner eigenen
    // Aussendung ab; das zweite Paket kommt kurz nach dem ersten.
    char antwort[64];
    snprintf(antwort, sizeof(antwort), "PONG %lu t=%lu ms",
             empfangen, (unsigned long)millis());
    const uint8_t* ziele[2] = {ZIEL, ZIEL_BB};
    for (int i = 0; i < 2; i++) {
      if (antwortAnzahl >= 8) {
        sag("  -> Antwort verworfen (Schlange voll)\n");
        break;
      }
      AntwortSlot& s = antworten[antwortAnzahl++];
      s.faellig = millis() + PONG_VERZOEGERUNG_MS + i * 500;
      s.len = ebyteRahmen(antwort, s.rahmen, ziele[i]);
      sag("  -> geplant (%s NETID): %s\n", i == 0 ? "00" : "BB", antwort);
    }
  } else {
    sag("  nicht beantwortet (Fehler %d)\n", state);
  }
  radio.startReceive();
}
