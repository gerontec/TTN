// Zwei Betriebsarten auf einem SX1262 (Waveshare Pico-LoRa) -- RadioLib.
//
//   MODUS_LORA     roher Ebyte-Kanal, wie bisher: 868.125 MHz, SF11/BW500,
//                  CR4/5, LDRO 1, Syncword 0x55 (Register 0x0740 = 54 54),
//                  Praeambel 8, 14 dBm, Ebyte-Rahmen (Magic 2c 12, Pruef-
//                  bytes, Zieladresse, XOR 0x12), PONG-Antworten und Relais.
//   MODUS_LORAWAN  LoRaWAN Class A, EU868, OTAA gegen den ChirpStack auf dem
//                  dell (192.168.5.23), den der DLOS8N 10.9.0.9 beliefert.
//
// Es laeuft immer nur eine davon -- ein Funkchip, zwei Welten. Die gewaehlte
// Betriebsart liegt im Flash (speicher.h) und ueberlebt den Stromausfall,
// zusammen mit DevNonce und LoRaWAN-Sitzung.
//
// Umgeschaltet wird von beiden Seiten ueber die Luft, weil der Pico kein WLAN
// hat und auf dem Berg niemand am USB steckt:
//
//   roher Kanal -> LoRaWAN   Fernwirkbefehl "C>MODUS LORAWAN [Minuten]",
//                            gleiche Sprache wie die Relaisstelle Brauneck
//                            (devices/pico_sx1262/fernwirk.py). Die Antwort
//                            "A>0E22>..." geht noch auf dem rohen Kanal raus,
//                            erst danach wird umgeschaltet.
//   LoRaWAN -> roher Kanal   Downlink auf FPort 10, Byte 0 = 0x00, optional
//                            zwei Bytes Minuten bis zur Rueckkehr.
//
// Die optionale Minutenangabe ist die Rueckfahrkarte: geht die Gegenseite in
// der neuen Betriebsart nicht ans Funkgeraet, kommt der Knoten von selbst
// zurueck. Sie steht nur im RAM -- ein Stromausfall in der Zwischenzeit laesst
// den Knoten in der zuletzt gesicherten Betriebsart aufwachen.
//
// Empfang auf dem rohen Kanal eng nach RadioLib-Beispiel SX126x_PingPong:
// DIO1-Interrupt setzt eine Flagge, loop() liest das Paket mit readData() und
// plant Antworten mit Ebyte-gerahmten Zeitstempeln (PONG). Die NETID steht im
// PONG-Text (N00/NBB), damit der Empfaenger sie an der UART ablesen kann --
// der Transparentmodus streicht den Rahmenkopf.
//
// Relais (Ebyte-Name): wenn RELAIS_ENABLE an ist, wird jeder empfangene
// Rahmen einmal weitergesendet, mit "R" vor der Nutzlast. Schon weiter-
// geleitete Rahmen (Nutzlast beginnt mit "R") werden nicht nochmal
// weitergeleitet -- Schleifenschutz zwischen mehreren Relais. Fernwirkbefehle
// und -antworten (C>/A>) gehen nie weiter, wie bei repeater.py.
//
// USB-Kommandos: diag | tx | relais [on|off] | modus [lora|lorawan] |
//                lwstat | lwsend <text> | lwreset | src | boot
//   boot springt in den ROM-Bootloader (RPI-RP2-Laufwerk fuer firmware.uf2).
//   src gibt den eigenen Quelltext aus -- er liegt mit im Flash, erzeugt von
//   quelltext_einbetten.py vor jedem Bau. Damit traegt der Knoten seine
//   Bauvorlage selbst; sie kann nicht mehr nur auf einem Notebook liegen.

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
// Die LoRaWAN-Seite, samt Betriebsart nach dem allerersten Start.
#include "lorawanparms.h"
// Betriebsart, DevNonce und Sitzung ueber den Stromausfall retten.
#include "speicher.h"
// AT-Schnittstelle (USB und UART auf GP0/GP1).
#include "atparms.h"
// Der eigene Quelltext, vor jedem Bau neu eingebettet.
#include "quelltext.h"

static const uint8_t ZIEL[3] = ADRESSE;          // NETID 00 + Rundruf FFFF
static const uint8_t ZIEL_BB[3] = ADRESSE_NETIDBB; // NETID BB + Rundruf FFFF

static bool relaisAn = RELAIS_ENABLE;            // zur Laufzeit schaltbar

// Vier Hexstellen aus der Geraeteadresse -- siehe loraparms.h.
static char stationId[5] = "0000";

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

// Derselbe Funkchip, zweite Rolle. RadioLib bringt den LoRaWAN-Stack selbst
// mit; der Knoten stellt Frequenz, SF, Syncword und IQ vor jedem Uplink neu
// ein, deshalb koennen sich beide Betriebsarten ein Module teilen.
LoRaWANNode node(&radio, &LW_BAND, LW_SUBBAND);

static unsigned long empfangen = 0, beantwortet = 0;
volatile bool operationDone = false;    // von setFlag() gesetzt
static bool transmitFlag = false;       // letzte Operation war eine Antwort
static int transmissionState = RADIOLIB_ERR_NONE;

// Was den Neustart ueberleben muss. Vorgabe fuer den allerersten Start; danach
// gilt, was im Flash steht.
static Zustand zustand = { STARTMODUS, 0, 0, 0, {0}, {0} };

// --- LoRaWAN-Laufzeit ------------------------------------------------------
static bool lwBereit = false;                    // Sitzung aktiv
static unsigned long lwNaechsterJoin = 0;
static unsigned long lwJoinPause = LW_JOIN_PAUSE_MS;
static unsigned long lwNaechsterUplink = 0;
static unsigned long lwUplinks = 0, lwDownlinks = 0;
static uint8_t lwSeitSicherung = 0;
static float letzteRssi = 0, letzteSnr = 0;      // fuer die Uplink-Nutzlast

// Letzter Empfang, fuer AT+RECV / AT+RECVB. Im rohen Betrieb ist der Port 0.
static uint8_t letztePort = 0;
static uint8_t letzteDaten[128];
static size_t  letzteDatenLen = 0;

// --- vorgemerkter Betriebsartwechsel ---------------------------------------
// Ein Wechsel reisst den Funkchip neu auf; eine noch nicht gesendete Antwort
// waere verloren. Deshalb wird der Wechsel nur vorgemerkt und erst
// ausgefuehrt, wenn die Antwortschlange leer ist.
static uint8_t wechselNach = 0xFF;               // 0xFF = nichts vorgemerkt
static unsigned long wechselMinuten = 0;         // Rueckkehr nach n Minuten

// Rueckfahrkarte: nur im RAM, siehe Kopf der Datei.
static uint8_t rueckkehrModus = 0xFF;
static unsigned long rueckkehrFaellig = 0;

// Antworten warten PONG_VERZOEGERUNG_MS, bis die Taubheit des E22 nach
// seiner eigenen Aussendung vorbei ist. Kleine Schlange fuer Serien.
struct AntwortSlot {
  unsigned long faellig;
  uint8_t rahmen[160];   // 8 Kopfbytes + bis zu 128 Nutzlast ("R"+127)
  size_t len;
};
static AntwortSlot antworten[8];
static uint8_t antwortAnzahl = 0;

// Meldet einen Empfang an die AT-Schnittstelle; unten definiert.
static void atEmpfangMelden(uint8_t port, const uint8_t* daten, size_t len);

// Wird vom DIO1-Interrupt gerufen, wenn TX oder TX fertig ist.
static void setFlag(void) { operationDone = true; }

// Die mbed-UART hat kein printf; ein eigener Umweg ueber vsnprintf.
// Meldungen gehen an beide Schnittstellen, USB und AT-UART -- ein Host an den
// zwei Draehten sieht denselben Betriebsfunk wie jemand am USB-Kabel.
static void sag(const char* fmt, ...) {
  char buf[192];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  Serial.print(buf);
#if AT_UART_AN
  Serial1.print(buf);
#endif
}

static const char* modusName(uint8_t m) {
  return m == MODUS_LORAWAN ? "LoRaWAN" : "roher Kanal";
}

// adresse[3] = NETID, ZH, ZL. Vorgabe ist NETID 00 + Rundruf FFFF.
// Laengenvariante, damit auch Bytes ohne Nullabschluss gehen (AT+SENDB).
static size_t ebyteRahmenN(const uint8_t* daten, size_t n, uint8_t* out,
                           const uint8_t* adresse = ZIEL) {
  uint8_t xx = 0;
  for (size_t i = 0; i < n; i++) xx ^= daten[i];
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
  for (size_t i = 0; i < n; i++) out[p++] = daten[i] ^ XORKEY;
  return p;
}

static size_t ebyteRahmen(const char* text, uint8_t* out,
                          const uint8_t* adresse = ZIEL) {
  return ebyteRahmenN((const uint8_t*)text, strlen(text), out, adresse);
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

// Stellt einen Rahmen in die Antwortschlange. faellig = 0 heisst sofort.
static bool antwortEinplanen(const char* text, const uint8_t* adresse,
                             unsigned long verzoegerung) {
  if (antwortAnzahl >= 8) return false;
  AntwortSlot& s = antworten[antwortAnzahl++];
  s.faellig = millis() + verzoegerung;
  s.len = ebyteRahmen(text, s.rahmen, adresse);
  return true;
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

// --- Flash -----------------------------------------------------------------

static void sicherungSchreiben(const char* warum) {
  if (zustandSichern(zustand))
    sag("Flash: gesichert (%s, Folge %lu)\n", warum, (unsigned long)zustandFolge());
  else
    sag("Flash: Sicherung FEHLGESCHLAGEN (%s)\n", warum);
}

// --- Betriebsarten ---------------------------------------------------------

// Rohen Ebyte-Kanal aufsetzen und auf Dauerempfang gehen.
static bool rohBetriebEinrichten() {
  radio.clearDio1Action();
  int state = radio.begin(FREQ_MHZ, BW_KHZ, LORA_SF, LORA_CR, SYNCWORD,
                          POWER_DBM, PREAMBLE, TCXO_V);
  if (state != RADIOLIB_ERR_NONE) {
    sag("SX1262 begin fehlgeschlagen: %d\n", state);
    return false;
  }
  // Beide Board-Fallen aus lora_p2p.py: DIO2 steuert den Antennenschalter,
  // und LDRO muss 1 sein (Ebyte-Werkswert; die Automatik kaeme auf 0 und
  // dann rastet nur der Header ein, waehrend jede Nutzlast CRC-Fehler hat).
  radio.setDio2AsRfSwitch(true);
  radio.forceLDRO(LDRO_ON);

  // Was aus dem LoRaWAN-Betrieb liegen geblieben ist, gilt nicht mehr.
  antwortAnzahl = 0;
  transmitFlag = false;
  operationDone = false;

  radio.setDio1Action(setFlag);        // Interrupt auf DIO1
  state = radio.startReceive();        // Dauerempfang
  if (state != RADIOLIB_ERR_NONE) {
    sag("startReceive fehlgeschlagen: %d\n", state);
    return false;
  }
  return true;
}

// Funkchip fuer LoRaWAN vorbereiten. Frequenz, SF, Syncword, Praeambel und IQ
// setzt RadioLibs LoRaWAN-Stack vor jedem Uplink selbst -- hier bleibt nur,
// was er nicht anfasst.
static bool lorawanBetriebEinrichten() {
  radio.clearDio1Action();             // der Stack setzt sich seinen eigenen
  int state = radio.begin(FREQ_MHZ, BW_KHZ, LORA_SF, LORA_CR, SYNCWORD,
                          POWER_DBM, PREAMBLE, TCXO_V);
  if (state != RADIOLIB_ERR_NONE) {
    sag("SX1262 begin fehlgeschlagen: %d\n", state);
    return false;
  }
  radio.setDio2AsRfSwitch(true);       // Antennenschalter, wie im Rohbetrieb
  // WICHTIG: der rohe Kanal erzwingt LDRO 1. LoRaWAN braucht die Automatik,
  // sonst laege bei DR5 (SF7 BW125) ein LDRO-Bit gesetzt, das das Gateway
  // nicht erwartet -- der Uplink waere unlesbar.
  radio.autoLDRO();

  lwBereit = false;
  lwSeitSicherung = 0;
  lwNaechsterJoin = millis();          // erster Join sofort
  lwJoinPause = LW_JOIN_PAUSE_MS;
  return true;
}

static void modusSetzen(uint8_t neu, bool sichern) {
  // Beim Verlassen des LoRaWAN-Betriebs die Sitzung sichern. Sonst faellt der
  // Uplink-Zaehler beim Zurueckschalten auf den zuletzt gesicherten Stand
  // zurueck (LW_SITZUNG_ALLE), und der Netzwerkserver verwirft die naechsten
  // Uplinks als Wiederholung -- gemessen am 21.08.: nach dem Wechsel stand
  // FCntUp wieder auf 0, ChirpStack schwieg dazu.
  if (zustand.modus == MODUS_LORAWAN && neu != MODUS_LORAWAN && lwBereit) {
    memcpy(zustand.sitzung, node.getBufferSession(), sizeof(zustand.sitzung));
    zustand.hatSitzung = 1;
    lwSeitSicherung = 0;
    sichern = true;
  }
  zustand.modus = neu;
  bool ok = (neu == MODUS_LORAWAN) ? lorawanBetriebEinrichten()
                                   : rohBetriebEinrichten();
  if (sichern) sicherungSchreiben("Betriebsart");
  sag("Betriebsart: %s%s\n", modusName(neu), ok ? "" : " (Funk FEHLER)");
}

// Wechsel vormerken; ausgefuehrt wird er, sobald die Antwortschlange leer ist.
static void wechselVormerken(uint8_t neu, unsigned long minuten) {
  wechselNach = neu;
  wechselMinuten = minuten;
}

// --- LoRaWAN ---------------------------------------------------------------

static void lorawanJoin() {
  static const uint8_t appKey[] = LW_APP_KEY;

  // nwkKey = NULL: LoRaWAN 1.0.x, es gibt nur den AppKey. Ein zweiter
  // Schluessel wuerde RadioLib auf 1.1 umstellen, und der Join scheiterte am
  // Geraeteprofil (LORAWAN_1_0_3) im ChirpStack.
  int16_t state = node.beginOTAA(LW_JOIN_EUI, LW_DEV_EUI, NULL, appKey);
  if (state != RADIOLIB_ERR_NONE) {
    sag("beginOTAA fehlgeschlagen: %d\n", state);
    lwNaechsterJoin = millis() + lwJoinPause;
    return;
  }

  // Reihenfolge ist Pflicht: beginOTAA loescht Nonces und Sitzung und rechnet
  // die Schluesselpruefsumme, gegen die setBufferNonces vergleicht.
  if (zustand.hatNonces) {
    int16_t n = node.setBufferNonces(zustand.nonces);
    if (n != RADIOLIB_ERR_NONE) {
      sag("gesicherte Nonces verworfen (%d) -- frischer Join\n", n);
      zustand.hatNonces = 0;
      zustand.hatSitzung = 0;
    }
  }
  if (zustand.hatSitzung) {
    int16_t s = node.setBufferSession(zustand.sitzung);
    if (s != RADIOLIB_ERR_NONE) {
      sag("gesicherte Sitzung verworfen (%d) -- neuer Join\n", s);
      zustand.hatSitzung = 0;
    }
  }

  sag("LoRaWAN: Join laeuft (DevEUI %08lX%08lX) ...\n",
      (unsigned long)(LW_DEV_EUI >> 32), (unsigned long)(LW_DEV_EUI & 0xFFFFFFFFUL));
  state = node.activateOTAA();

  // Auch ein gescheiterter Versuch verbraucht einen DevNonce -- der darf sich
  // nie wiederholen, also wird er in jedem Fall gesichert.
  memcpy(zustand.nonces, node.getBufferNonces(), sizeof(zustand.nonces));
  zustand.hatNonces = 1;

  if (state == RADIOLIB_LORAWAN_NEW_SESSION || state == RADIOLIB_LORAWAN_SESSION_RESTORED) {
    lwBereit = true;
    node.setADR(LW_ADR);
    node.setDatarate(LW_DATENRATE);
    memcpy(zustand.sitzung, node.getBufferSession(), sizeof(zustand.sitzung));
    zustand.hatSitzung = 1;
    sicherungSchreiben(state == RADIOLIB_LORAWAN_NEW_SESSION ? "Join"
                                                             : "Sitzung");
    sag("LoRaWAN aktiv: DevAddr %08lX, %s\n", (unsigned long)node.getDevAddr(),
        state == RADIOLIB_LORAWAN_NEW_SESSION ? "neu gejoint"
                                              : "Sitzung fortgesetzt");
    lwNaechsterUplink = millis();       // erster Uplink sofort
    lwJoinPause = LW_JOIN_PAUSE_MS;
  } else {
    sicherungSchreiben("DevNonce");
    lwNaechsterJoin = millis() + lwJoinPause;
    sag("LoRaWAN: Join fehlgeschlagen (%d), naechster Versuch in %lu s\n",
        state, lwJoinPause / 1000UL);
    lwJoinPause *= 2;
    if (lwJoinPause > LW_JOIN_PAUSE_MAX_MS) lwJoinPause = LW_JOIN_PAUSE_MAX_MS;
  }
}

// 8 Byte, gross-endian: Laufzeit [min], empfangene und beantwortete Rahmen des
// rohen Kanals, RSSI und SNR des letzten rohen Pakets.
static size_t lorawanNutzlast(uint8_t* out) {
  unsigned long minuten = millis() / 60000UL;
  uint16_t lauf = minuten > 0xFFFF ? 0xFFFF : (uint16_t)minuten;
  uint16_t rx = empfangen > 0xFFFF ? 0xFFFF : (uint16_t)empfangen;
  uint16_t tx = beantwortet > 0xFFFF ? 0xFFFF : (uint16_t)beantwortet;
  out[0] = (uint8_t)(lauf >> 8); out[1] = (uint8_t)lauf;
  out[2] = (uint8_t)(rx >> 8);   out[3] = (uint8_t)rx;
  out[4] = (uint8_t)(tx >> 8);   out[5] = (uint8_t)tx;
  out[6] = (uint8_t)(int8_t)letzteRssi;
  out[7] = (uint8_t)(int8_t)letzteSnr;
  return 8;
}

// Downlink auf dem Steuerport: zurueck auf den rohen Kanal, optional befristet.
static void lorawanDownlink(const uint8_t* daten, size_t len, uint8_t port) {
  sag("Downlink FPort %u, %u B:", port, (unsigned)len);
  for (size_t i = 0; i < len; i++) sag(" %02x", daten[i]);
  sag("\n");

  atEmpfangMelden(port, daten, len);

  if (port != LW_STEUERPORT || len < 1) return;

  switch (daten[0]) {
    case 0x00: {                       // auf den rohen Kanal
      unsigned long minuten = 0;
      if (len >= 3) minuten = ((unsigned long)daten[1] << 8) | daten[2];
      sag("Steuerbefehl: roher Kanal%s\n", minuten ? ", Rueckkehr vorgemerkt" : "");
      wechselVormerken(MODUS_LORA, minuten);
      break;
    }
    case 0x01:                         // bleiben, wo wir sind
      sag("Steuerbefehl: LoRaWAN bleibt\n");
      rueckkehrModus = 0xFF;
      rueckkehrFaellig = 0;
      break;
    case 0x02:                         // Relais schalten
      if (len >= 2) {
        relaisAn = daten[1] != 0;
        sag("Steuerbefehl: Relais %s\n", relaisAn ? "an" : "aus");
      }
      break;
    default:
      sag("Steuerbefehl unbekannt: 0x%02x\n", daten[0]);
      break;
  }
}

// Ein Uplink samt der beiden Empfangsfenster. sendReceive blockiert dabei
// einige Sekunden -- Class A kennt keinen anderen Weg.
static void lorawanUplink(const uint8_t* nutz, size_t len, uint8_t port) {
  uint8_t ab[255];                     // wie im RadioLib-Beispiel
  size_t abLen = sizeof(ab);
  LoRaWANEvent_t hin, her;

  int16_t state = node.sendReceive(nutz, len, port, ab, &abLen, LW_BESTAETIGT,
                                   &hin, &her);

  if (state < RADIOLIB_ERR_NONE) {
    sag("Uplink FEHLER %d\n", state);
    if (state == RADIOLIB_ERR_NETWORK_NOT_JOINED || state == RADIOLIB_ERR_SESSION_DISCARDED) {
      lwBereit = false;                // Sitzung hin -- neu joinen
      zustand.hatSitzung = 0;
      lwNaechsterJoin = millis() + LW_JOIN_PAUSE_MS;
    }
    lwNaechsterUplink = millis() + 60UL * 1000UL;
    return;
  }

  lwUplinks++;
  sag("Uplink %lu: FCntUp %lu, DR %u, %lu ms Sendezeit\n", lwUplinks,
      (unsigned long)node.getFCntUp(), hin.datarate,
      (unsigned long)node.getLastToA());

  // Sitzung nur jeden n-ten Uplink in den Flash, siehe LW_SITZUNG_ALLE.
  if (++lwSeitSicherung >= LW_SITZUNG_ALLE) {
    memcpy(zustand.sitzung, node.getBufferSession(), sizeof(zustand.sitzung));
    zustand.hatSitzung = 1;
    sicherungSchreiben("Sitzung");
    lwSeitSicherung = 0;
  }

  // Naechster Uplink: der spaetere von Wunschtakt und Duty-Cycle-Sperre.
  unsigned long wartet = (unsigned long)node.timeUntilUplink();
  lwNaechsterUplink = millis() + (wartet > LW_INTERVALL_MS ? wartet : LW_INTERVALL_MS);

  if (state > 0) {                     // Downlink in Fenster 1 oder 2
    lwDownlinks++;
    lorawanDownlink(ab, abLen, her.fPort);
  }
}

static void lorawanSchleife() {
  if (!lwBereit) {
    if ((long)(millis() - lwNaechsterJoin) >= 0) lorawanJoin();
    return;
  }
  if ((long)(millis() - lwNaechsterUplink) < 0) return;

  uint8_t nutz[8];
  size_t n = lorawanNutzlast(nutz);
  lorawanUplink(nutz, n, LW_PORT);
}

// --- Fernwirken ueber den rohen Kanal --------------------------------------
// Sprache wie bei der Relaisstelle Brauneck (fernwirk.py): Befehl "C>NAME
// [wert]", Antwort "A><Kennung>>text". Bewusst ohne Authentisierung -- wer in
// Funkreichweite ist, kann den Knoten umstellen. Fuer ein Krisensystem ist das
// die richtige Abwaegung: der Funk traegt genau dann, wenn sonst nichts mehr
// geht.

static void grossSchreiben(char* s) {
  for (; *s; s++) if (*s >= 'a' && *s <= 'z') *s -= 32;
}

static void befehlAusfuehren(const char* befehl, char* out, size_t outsz) {
  char name[16] = "", wert[16] = "", zusatz[16] = "";
  sscanf(befehl, "%15s %15s %15s", name, wert, zusatz);
  grossSchreiben(name);
  grossSchreiben(wert);

  if (strcmp(name, "MODUS") == 0) {
    if (wert[0] == 0) {
      snprintf(out, outsz, "MODUS %s", zustand.modus == MODUS_LORAWAN ? "LORAWAN" : "LORA");
      return;
    }
    uint8_t neu;
    if (strcmp(wert, "LORAWAN") == 0) neu = MODUS_LORAWAN;
    else if (strcmp(wert, "LORA") == 0) neu = MODUS_LORA;
    else { snprintf(out, outsz, "MODUS: LORA oder LORAWAN"); return; }
    unsigned long minuten = zusatz[0] ? strtoul(zusatz, NULL, 10) : 0;
    wechselVormerken(neu, minuten);
    if (minuten)
      snprintf(out, outsz, "MODUS %s, Rueckkehr in %lu min", wert, minuten);
    else
      snprintf(out, outsz, "MODUS %s", wert);
    return;
  }

  if (strcmp(name, "STATUS") == 0) {
    snprintf(out, outsz, "id%s %s empf%lu ant%lu %lus relais%d lw%lu",
             stationId, zustand.modus == MODUS_LORAWAN ? "LORAWAN" : "LORA",
             empfangen, beantwortet, millis() / 1000UL, relaisAn ? 1 : 0,
             lwUplinks);
    return;
  }

  if (strcmp(name, "RELAY") == 0 && (wert[0] == '0' || wert[0] == '1')) {
    relaisAn = wert[0] == '1';
    snprintf(out, outsz, "RELAY %s", relaisAn ? "an" : "aus");
    return;
  }

  if (strcmp(name, "ID") == 0) {
    // Nur lesbar: die Kennung ist die Geraeteadresse, nicht frei waehlbar.
    snprintf(out, outsz, "ID %s", stationId);
    return;
  }

  if (strcmp(name, "PING") == 0) {
    snprintf(out, outsz, "PONG %lus", millis() / 1000UL);
    return;
  }

  snprintf(out, outsz, "unbekannt: %s", name);
}

// --- AT-Schnittstelle ------------------------------------------------------
// Das Kommando-Set der Dragino-Geraete, damit sich der Knoten wie ein LA66
// einbinden laesst (atparms.h erklaert Vorlage und Abweichungen). Antworten
// gehen nur an die Schnittstelle, die gefragt hat; Betriebsmeldungen (sag)
// weiterhin an beide.

static void atAntwort(Stream &s, const char* fmt, ...) {
  char buf[192];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  s.print(buf);
  s.print("\r\n");
}

static void atHex(Stream &s, const uint8_t* daten, size_t len) {
  char zeile[3 * 64 + 1];
  size_t p = 0;
  for (size_t i = 0; i < len && p + 2 < sizeof(zeile); i++)
    p += snprintf(zeile + p, sizeof(zeile) - p, "%02x", daten[i]);
  zeile[p] = 0;
  s.print(zeile);
}

// "A8 40 41 ..." wie im AT+CFG des LA66.
static void atEui(char* out, size_t outsz, uint64_t eui) {
  size_t p = 0;
  for (int i = 7; i >= 0; i--)
    p += snprintf(out + p, outsz - p, "%02X%s", (uint8_t)(eui >> (i * 8)), i ? " " : "");
}

static bool hexBytes(const char* text, uint8_t* out, size_t maxLen, size_t* len) {
  size_t n = strlen(text);
  if (n % 2 || n / 2 > maxLen) return false;
  for (size_t i = 0; i < n; i += 2) {
    char paar[3] = { text[i], text[i + 1], 0 };
    char* ende;
    long v = strtol(paar, &ende, 16);
    if (*ende) return false;
    out[i / 2] = (uint8_t)v;
  }
  *len = n / 2;
  return true;
}

static void atCfg(Stream &s) {
  char eui[24];
  atEui(eui, sizeof(eui), LW_DEV_EUI);
  atAntwort(s, "AT+DEUI=%s", eui);
  atEui(eui, sizeof(eui), LW_JOIN_EUI);
  atAntwort(s, "AT+APPEUI=%s", eui);
  atAntwort(s, "AT+APPKEY=<im Geraet>");
  atAntwort(s, "AT+DADDR=%08lX", (unsigned long)(lwBereit ? node.getDevAddr() : 0));
  atAntwort(s, "AT+NJM=1");
  atAntwort(s, "AT+NJS=%d", lwBereit ? 1 : 0);
  atAntwort(s, "AT+CLASS=A");
  atAntwort(s, "AT+ADR=%d", LW_ADR ? 1 : 0);
  atAntwort(s, "AT+DR=%d", LW_DATENRATE);
  atAntwort(s, "AT+FCU=%lu", (unsigned long)(lwBereit ? node.getFCntUp() : 0));
  atAntwort(s, "AT+LORAWAN=%d", zustand.modus == MODUS_LORAWAN ? 1 : 0);
  atAntwort(s, "AT+FRE=%.3f", FREQ_MHZ);
  atAntwort(s, "AT+SF=%d", LORA_SF);
  atAntwort(s, "AT+BW=%.0f", BW_KHZ);
  atAntwort(s, "AT+CR=%d", LORA_CR);
  atAntwort(s, "AT+POWER=%d", POWER_DBM);
  atAntwort(s, "AT+SYNCWORD=%02X", SYNCWORD);
  atAntwort(s, "AT+PREAMBLE=%d", PREAMBLE);
  atAntwort(s, "AT+RELAY=%d", relaisAn ? 1 : 0);
  atAntwort(s, "AT+ID=%s", stationId);
  atAntwort(s, "AT+RSSI=%.0f", letzteRssi);
  atAntwort(s, "AT+SNR=%.1f", letzteSnr);
  atAntwort(s, "AT+UPTIME=%lu", millis() / 1000UL);
  atAntwort(s, "AT+VER=%s %s", AT_VERSION, stationId);
}

static void atHilfe(Stream &s) {
  atAntwort(s, "AT                      Lebenszeichen");
  atAntwort(s, "AT?                     diese Liste");
  atAntwort(s, "ATZ                     Neustart");
  atAntwort(s, "AT+CFG                  alles anzeigen");
  atAntwort(s, "AT+LORAWAN=0|1[,min]    0 = roher Kanal, 1 = LoRaWAN");
  atAntwort(s, "AT+JOIN                 OTAA-Join ausloesen");
  atAntwort(s, "AT+NJS=?                1 = Sitzung aktiv");
  atAntwort(s, "AT+SEND=<cfm>,<port>,<len>,<text>");
  atAntwort(s, "AT+SENDB=<cfm>,<port>,<len>,<hex>");
  atAntwort(s, "AT+RECV=?  AT+RECVB=?   letzter Empfang (Text bzw. Hex)");
  atAntwort(s, "AT+RELAY=0|1            Relais des rohen Kanals");
  atAntwort(s, "AT+DEUI=? AT+APPEUI=? AT+DADDR=? AT+FCU=? AT+DR=? AT+ADR=?");
  atAntwort(s, "AT+FRE=? AT+SF=? AT+BW=? AT+CR=? AT+POWER=? AT+SYNCWORD=?");
  atAntwort(s, "  (Parameter des rohen Kanals nur lesbar, siehe loraparms.h)");
}

// Senden aus dem AT-Set: im LoRaWAN-Betrieb ein Uplink, im rohen Betrieb ein
// Ebyte-Rahmen. Derselbe Befehl, zwei Traeger -- das ist der ganze Zweck.
static bool atSenden(Stream &s, const uint8_t* daten, size_t len, uint8_t port,
                     bool bestaetigt) {
  if (zustand.modus == MODUS_LORAWAN) {
    if (!lwBereit) { atAntwort(s, "AT_NO_NETWORK_JOINED"); return false; }
    uint8_t ab[255];
    size_t abLen = sizeof(ab);
    LoRaWANEvent_t hin, her;
    int16_t st = node.sendReceive(daten, len, port, ab, &abLen, bestaetigt, &hin, &her);
    if (st < RADIOLIB_ERR_NONE) { atAntwort(s, "AT_ERROR (%d)", st); return false; }
    lwUplinks++;
    if (st > 0) {
      lwDownlinks++;
      lorawanDownlink(ab, abLen, her.fPort);
    }
    unsigned long wartet = (unsigned long)node.timeUntilUplink();
    lwNaechsterUplink = millis() + (wartet > LW_INTERVALL_MS ? wartet : LW_INTERVALL_MS);
    return true;
  }
  if (len > 128) { atAntwort(s, "AT_PARAM_ERROR"); return false; }
  uint8_t rahmen[160];
  size_t n = ebyteRahmenN(daten, len, rahmen);
  radio.standby();
  int st = radio.transmit(rahmen, n);
  radio.startReceive();
  // transmit() blockiert, der DIO1-Interrupt setzt die Flagge trotzdem --
  // ohne dieses Zuruecksetzen zaehlte die Hauptschleife die eigene Aussendung
  // als leeren Empfang mit (gemessen: "RX #1 ... 0 B").
  operationDone = false;
  if (st != RADIOLIB_ERR_NONE) { atAntwort(s, "AT_ERROR (%d)", st); return false; }
  return true;
}

// zeile ist alles hinter "AT". Rueckgabe: true = "OK" anhaengen.
static bool atBefehl(Stream &s, char* zeile) {
  if (zeile[0] == 0) return true;                    // schlichtes AT
  if (strcmp(zeile, "?") == 0) { atHilfe(s); return true; }
  if (strcmp(zeile, "Z") == 0) {                     // ATZ
    atAntwort(s, "OK");
    s.flush();
    delay(50);
    NVIC_SystemReset();
  }
  if (zeile[0] != '+') { atAntwort(s, "AT_ERROR"); return false; }

  char* name = zeile + 1;
  char* wert = strchr(name, '=');
  if (wert) *wert++ = 0;
  for (char* c = name; *c; c++) if (*c >= 'a' && *c <= 'z') *c -= 32;
  bool frage = wert && strcmp(wert, "?") == 0;

  // --- nur lesbare Kennungen ---
  if (strcmp(name, "DEUI") == 0)   { char e[24]; atEui(e, sizeof(e), LW_DEV_EUI);  atAntwort(s, "%s", e); return true; }
  if (strcmp(name, "APPEUI") == 0) { char e[24]; atEui(e, sizeof(e), LW_JOIN_EUI); atAntwort(s, "%s", e); return true; }
  if (strcmp(name, "APPKEY") == 0) { atAntwort(s, "<im Geraet>"); return true; }
  if (strcmp(name, "ID") == 0)     { atAntwort(s, "%s", stationId); return true; }
  // VERSION als Zweitname: nicht jede Dragino-Firmware heisst es gleich.
  if (strcmp(name, "VER") == 0 || strcmp(name, "VERSION") == 0)
    { atAntwort(s, "%s %s", AT_VERSION, stationId); return true; }
  if (strcmp(name, "CLASS") == 0)  { atAntwort(s, "A"); return true; }
  if (strcmp(name, "NJM") == 0)    { atAntwort(s, "1"); return true; }
  if (strcmp(name, "NJS") == 0)    { atAntwort(s, "%d", lwBereit ? 1 : 0); return true; }
  if (strcmp(name, "DADDR") == 0)  { atAntwort(s, "%08lX", (unsigned long)(lwBereit ? node.getDevAddr() : 0)); return true; }
  if (strcmp(name, "FCU") == 0)    { atAntwort(s, "%lu", (unsigned long)(lwBereit ? node.getFCntUp() : 0)); return true; }
  if (strcmp(name, "RSSI") == 0)   { atAntwort(s, "%.0f", letzteRssi); return true; }
  if (strcmp(name, "SNR") == 0)    { atAntwort(s, "%.1f", letzteSnr); return true; }
  if (strcmp(name, "CFG") == 0)    { atCfg(s); return true; }

  // --- Parameter des rohen Kanals: lesen ja, setzen nein ---
  struct { const char* n; const char* fmt; double wert; } fest[] = {
    { "FRE", "%.3f", FREQ_MHZ }, { "SF", "%.0f", (double)LORA_SF },
    { "BW", "%.0f", BW_KHZ },    { "CR", "%.0f", (double)LORA_CR },
    { "POWER", "%.0f", (double)POWER_DBM },
    { "PREAMBLE", "%.0f", (double)PREAMBLE },
  };
  for (size_t i = 0; i < sizeof(fest) / sizeof(fest[0]); i++) {
    if (strcmp(name, fest[i].n) != 0) continue;
    if (wert && !frage) { atAntwort(s, "AT_ERROR"); return false; }   // loraparms.h
    atAntwort(s, fest[i].fmt, fest[i].wert);
    return true;
  }
  if (strcmp(name, "SYNCWORD") == 0) {
    if (wert && !frage) { atAntwort(s, "AT_ERROR"); return false; }
    atAntwort(s, "%02X", SYNCWORD);
    return true;
  }

  // --- Betriebsart ---
  if (strcmp(name, "LORAWAN") == 0) {
    if (!wert || frage) {
      atAntwort(s, "%d", zustand.modus == MODUS_LORAWAN ? 1 : 0);
      return true;
    }
    char* komma = strchr(wert, ',');
    unsigned long minuten = 0;
    if (komma) { *komma = 0; minuten = strtoul(komma + 1, NULL, 10); }
    if (wert[0] != '0' && wert[0] != '1') { atAntwort(s, "AT_PARAM_ERROR"); return false; }
    wechselVormerken(wert[0] == '1' ? MODUS_LORAWAN : MODUS_LORA, minuten);
    return true;
  }

  if (strcmp(name, "RELAY") == 0) {
    if (!wert || frage) { atAntwort(s, "%d", relaisAn ? 1 : 0); return true; }
    if (wert[0] != '0' && wert[0] != '1') { atAntwort(s, "AT_PARAM_ERROR"); return false; }
    relaisAn = wert[0] == '1';
    return true;
  }

  // --- LoRaWAN-Betrieb ---
  if (strcmp(name, "ADR") == 0) {
    if (!wert || frage) { atAntwort(s, "%d", LW_ADR ? 1 : 0); return true; }
    node.setADR(wert[0] == '1');
    return true;
  }
  if (strcmp(name, "DR") == 0) {
    if (!wert || frage) { atAntwort(s, "%d", LW_DATENRATE); return true; }
    if (node.setDatarate((uint8_t)strtoul(wert, NULL, 10)) != RADIOLIB_ERR_NONE) {
      atAntwort(s, "AT_PARAM_ERROR");
      return false;
    }
    return true;
  }
  if (strcmp(name, "JOIN") == 0) {
    if (zustand.modus != MODUS_LORAWAN) { atAntwort(s, "AT_ERROR"); return false; }
    lwNaechsterJoin = millis();
    lwBereit = false;
    return true;
  }

  // --- Senden und Empfangen ---
  if (strcmp(name, "SEND") == 0 || strcmp(name, "SENDB") == 0) {
    bool binaer = strcmp(name, "SENDB") == 0;
    if (!wert) { atAntwort(s, "AT_PARAM_ERROR"); return false; }
    // <bestaetigt>,<fPort>,<laenge>,<daten> -- Format des LA66.
    char* teil[4] = { wert, NULL, NULL, NULL };
    int n = 1;
    for (char* c = wert; *c && n < 4; c++)
      if (*c == ',') { *c = 0; teil[n++] = c + 1; }
    if (n < 4) { atAntwort(s, "AT_PARAM_ERROR"); return false; }
    bool bestaetigt = strtoul(teil[0], NULL, 10) != 0;
    uint8_t port = (uint8_t)strtoul(teil[1], NULL, 10);
    size_t angesagt = strtoul(teil[2], NULL, 10);
    uint8_t daten[128];
    size_t len;
    if (binaer) {
      if (!hexBytes(teil[3], daten, sizeof(daten), &len)) { atAntwort(s, "AT_PARAM_ERROR"); return false; }
    } else {
      len = strlen(teil[3]);
      if (len > sizeof(daten)) { atAntwort(s, "AT_PARAM_ERROR"); return false; }
      memcpy(daten, teil[3], len);
    }
    // Die Laengenangabe des LA66 wird geprueft, nicht geglaubt.
    if (angesagt != len) { atAntwort(s, "AT_PARAM_ERROR"); return false; }
    return atSenden(s, daten, len, port ? port : LW_PORT, bestaetigt);
  }
  if (strcmp(name, "RECV") == 0) {
    char text[129];
    size_t n = letzteDatenLen < sizeof(text) - 1 ? letzteDatenLen : sizeof(text) - 1;
    memcpy(text, letzteDaten, n);
    text[n] = 0;
    atAntwort(s, "%u:%s", letztePort, text);
    return true;
  }
  if (strcmp(name, "RECVB") == 0) {
    char zeile2[8];
    snprintf(zeile2, sizeof(zeile2), "%u:", letztePort);
    s.print(zeile2);
    atHex(s, letzteDaten, letzteDatenLen);
    s.print("\r\n");
    return true;
  }

  atAntwort(s, "AT_ERROR");
  return false;
}

// Meldet einen Empfang unaufgefordert im LA66-Format an beide Schnittstellen.
static void atEmpfangMelden(uint8_t port, const uint8_t* daten, size_t len) {
  if (len == 0) return;      // reine MAC-Downlinks (FPort 0) sind keine Daten
  letztePort = port;
  letzteDatenLen = len < sizeof(letzteDaten) ? len : sizeof(letzteDaten);
  memcpy(letzteDaten, daten, letzteDatenLen);
#if AT_RECV_MELDEN
  char kopf[24];
  snprintf(kopf, sizeof(kopf), "AT+RECVB=%u:", port);
  Serial.print(kopf);
  atHex(Serial, letzteDaten, letzteDatenLen);
  Serial.print("\r\n");
#if AT_UART_AN
  Serial1.print(kopf);
  atHex(Serial1, letzteDaten, letzteDatenLen);
  Serial1.print("\r\n");
#endif
#endif
}

// Zeilenweise lesen, ohne die Hauptschleife anzuhalten -- readStringUntil
// wuerde bis zu einer Sekunde blockieren und die PONG-Zeitpunkte verschieben.
struct Zeilenleser {
  char puffer[192];
  size_t len;
  bool lesen(Stream &s, char** zeile) {
    while (s.available()) {
      char c = (char)s.read();
      if (c == '\n' || c == '\r') {
        if (len == 0) continue;
        puffer[len] = 0;
        len = 0;
        *zeile = puffer;
        return true;
      }
      if (len < sizeof(puffer) - 1) puffer[len++] = c;
    }
    return false;
  }
};

// --- Start -----------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(2000);                  // USB-CDC erst bereit werden lassen

  snprintf(stationId, sizeof(stationId), "%04lX",
           (unsigned long)(LW_DEV_EUI & 0xFFFFUL));

#if AT_UART_AN
  // Die AT-UART auf GP0 (TX) / GP1 (RX) -- der Weg fuer einen Host ohne USB.
  Serial1.begin(AT_UART_BAUD);
#endif

  spi.begin();

  // Betriebsart, DevNonce und Sitzung aus dem Flash -- oder die Vorgaben.
  if (zustandLaden(zustand))
    sag("Flash: Stand geladen (Folge %lu, %s, Nonces %d, Sitzung %d)\n",
        (unsigned long)zustandFolge(), modusName(zustand.modus),
        zustand.hatNonces, zustand.hatSitzung);
  else
    sag("Flash: noch kein Stand, Vorgabe %s\n", modusName(zustand.modus));

  if (zustand.modus == MODUS_LORAWAN) {
    if (!lorawanBetriebEinrichten()) while (true) delay(1000);
  } else {
    if (!rohBetriebEinrichten()) while (true) delay(1000);

    // Nach jedem Start (auch nach Stromausfall) die Parameter aus loraparms.h
    // einmal funken -- der Gateway hoert mit und traegt sie in die DB ein.
    char parm[96];
    snprintf(parm, sizeof(parm),
             "PARM %.3fMHz SF%d BW%.0f CR4/%d SYNC%02X LDRO%d PRE%d %ddBm",
             FREQ_MHZ, LORA_SF, BW_KHZ, LORA_CR, SYNCWORD, LDRO_ON ? 1 : 0,
             PREAMBLE, POWER_DBM);
    uint8_t rahmen[128];
    size_t n = ebyteRahmen(parm, rahmen);
    radio.standby();
    int pstate = radio.transmit(rahmen, n);
    sag("PARAMETER gefunkt: %s (%s)\n", parm,
        pstate == RADIOLIB_ERR_NONE ? "ok" : "FEHLER");
    radio.startReceive();
    operationDone = false;

    sag("E22-Profil aktiv: %.3f MHz SF%d BW%.0f CR4/%d LDRO1 Sync 0x%02X %d dBm\n",
        FREQ_MHZ, LORA_SF, BW_KHZ, LORA_CR, SYNCWORD, POWER_DBM);
    sag("warte auf Pakete -- Antwort je Paket mit Zeitstempel\n");
  }

  sag("Station %s, Betriebsart %s, Relais %s\n", stationId,
      modusName(zustand.modus), relaisAn ? "an" : "aus");
  sag("Kommandos: diag | tx | relais [on|off] | modus [lora|lorawan] |\n");
  sag("           lwstat | lwsend <text> | lwreset | src | boot\n");
  sag("AT-Set wie beim LA66: AT | AT? | AT+CFG | AT+SENDB=... | AT+LORAWAN=0|1\n");
  sag("ueber die Luft: C>MODUS LORAWAN [min] | C>STATUS | C>RELAY 0|1\n");
  diag();
}

// Gibt den eingebetteten Quelltext ueber USB aus. In Haeppchen, weil die
// CDC-Schnittstelle nur einige hundert Byte auf einmal fasst -- am Stueck
// verschluckt sie den Rest lautlos.
static void quelltextAusgeben(const char *name, const char *text) {
  size_t laenge = strlen(text);
  sag("---- %s (%u Byte) ----\n", name, (unsigned)laenge);
  for (size_t i = 0; i < laenge; i += 128) {
    size_t n = laenge - i < 128 ? laenge - i : 128;
    Serial.write((const uint8_t *)text + i, n);
    Serial.flush();
  }
  // Zeilenumbruch nur, wenn die Datei nicht ohnehin mit einem endet: so ist
  // das Ausgelesene byteidentisch mit der Vorlage (`src > main.cpp` genuegt).
  if (laenge && text[laenge - 1] != '\n') Serial.write('\n');
  sag("---- Ende %s ----\n", name);
}

static void lwstat() {
  sag("LoRaWAN: %s, Uplinks %lu, Downlinks %lu\n",
      lwBereit ? "Sitzung aktiv" : "nicht gejoint", lwUplinks, lwDownlinks);
  if (lwBereit) {
    sag("  DevAddr %08lX, FCntUp %lu, naechster Uplink in %ld s\n",
        (unsigned long)node.getDevAddr(), (unsigned long)node.getFCntUp(),
        (long)(lwNaechsterUplink - millis()) / 1000L);
  } else if (zustand.modus == MODUS_LORAWAN) {
    sag("  naechster Join in %ld s\n", (long)(lwNaechsterJoin - millis()) / 1000L);
  }
  sag("  Flash: Folge %lu, Nonces %d, Sitzung %d\n",
      (unsigned long)zustandFolge(), zustand.hatNonces, zustand.hatSitzung);
  if (rueckkehrModus != 0xFF)
    sag("  Rueckkehr nach %s in %ld s\n", modusName(rueckkehrModus),
        (long)(rueckkehrFaellig - millis()) / 1000L);
}

// --- USB-Kommandos ---------------------------------------------------------

static void usbKommando(String cmd) {
  if (cmd == "boot") {
    sag("springe in den Bootloader...\n");
    Serial.flush();
    delay(50);
    reset_usb_boot(0, 0);
  } else if (cmd == "diag") {
    diag();
  } else if (cmd == "relais on") {
    relaisAn = true;
    sag("Relais: an\n");
  } else if (cmd == "relais off") {
    relaisAn = false;
    sag("Relais: aus\n");
  } else if (cmd == "relais") {
    sag("Relais: %s\n", relaisAn ? "an" : "aus");
  } else if (cmd == "src") {
    for (size_t i = 0; i < QUELLTEXT_ANZAHL; i++)
      quelltextAusgeben(QUELLTEXT_NAMEN[i], QUELLTEXT_TEXTE[i]);
  } else if (cmd == "modus") {
    sag("Betriebsart: %s\n", modusName(zustand.modus));
  } else if (cmd == "modus lora") {
    rueckkehrModus = 0xFF;
    modusSetzen(MODUS_LORA, true);
  } else if (cmd == "modus lorawan") {
    rueckkehrModus = 0xFF;
    modusSetzen(MODUS_LORAWAN, true);
  } else if (cmd == "lwstat") {
    lwstat();
  } else if (cmd == "lwreset") {
    // Sitzung und Nonces verwerfen -- der naechste Join faengt bei null an.
    // Der Netzwerkserver muss dann ebenfalls zuruecksetzen, sonst weist er den
    // wiederholten DevNonce als Replay ab.
    node.clearSession();
    zustand.hatNonces = 0;
    zustand.hatSitzung = 0;
    memset(zustand.nonces, 0, sizeof(zustand.nonces));
    memset(zustand.sitzung, 0, sizeof(zustand.sitzung));
    sicherungSchreiben("lwreset");
    lwBereit = false;
    lwNaechsterJoin = millis();
    sag("LoRaWAN: Sitzung und Nonces geloescht\n");
  } else if (cmd.startsWith("lwsend ")) {
    if (zustand.modus != MODUS_LORAWAN || !lwBereit) {
      sag("lwsend: nur mit aktiver LoRaWAN-Sitzung\n");
    } else {
      String text = cmd.substring(7);
      lorawanUplink((const uint8_t*)text.c_str(), text.length(), LW_PORT);
    }
  } else if (cmd == "tx") {
    char text[64];
    snprintf(text, sizeof(text), "CTEST t=%lu ms", (unsigned long)millis());
    uint8_t rahmen[96];
    size_t n = ebyteRahmen(text, rahmen);
    radio.standby();
    int txstate = radio.transmit(rahmen, n);
    sag("tx %s: %s\n", text, txstate == RADIOLIB_ERR_NONE ? "ok" : "FEHLER");
    radio.startReceive();
    operationDone = false;          // eigene Aussendung nicht als Empfang zaehlen
  }
}

// Eine eingegangene Zeile: AT-Befehl oder kurzes Klartext-Kommando.
static void kommandoZeile(Stream &s, char* zeile) {
  while (*zeile == ' ') zeile++;
  if ((zeile[0] == 'A' || zeile[0] == 'a') && (zeile[1] == 'T' || zeile[1] == 't')) {
    if (atBefehl(s, zeile + 2)) atAntwort(s, "OK");
    return;
  }
  String kurz(zeile);
  kurz.trim();
  usbKommando(kurz);
}

// --- roher Kanal -----------------------------------------------------------

static void rohSchleife() {
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
  letzteRssi = rssi;
  letzteSnr = snr;

  sag("RX #%lu RSSI %.0f dBm SNR %.1f dB %u B:",
      empfangen, rssi, snr, (unsigned)len);
  for (size_t i = 0; i < len; i++) sag(" %02x", buf[i]);
  sag("\n");

  if (state == RADIOLIB_ERR_NONE) {
    char nutz[128];
    if (ebyteEntpacken(buf, len, nutz, sizeof(nutz))) {
      sag("  Ebyte-Rahmen ok: %s\n", nutz);
      atEmpfangMelden(0, (const uint8_t*)nutz, strlen(nutz));

      // Ein weitergeleiteter Rahmen traegt ein "R" davor; der Befehl dahinter
      // gilt trotzdem, sonst waere ueber ein Relais nichts zu erreichen.
      const char* text = nutz[0] == 'R' ? nutz + 1 : nutz;
      bool istBefehl  = text[0] == 'C' && text[1] == '>';
      bool istAntwort = text[0] == 'A' && text[1] == '>';

      // Relais: den Rahmen einmal weiterschicken, mit "R" vor der Nutzlast.
      // Die NETID wird gekreuzt wie beim E90-DTU (00 <-> BB), damit die
      // Weiterleitung die andere Gruppe erreicht; das Ziel bleibt erhalten.
      // Rahmen, deren Nutzlast schon mit "R" beginnt, sind bereits
      // weitergeleitet -- Schleifenschutz zwischen mehreren Relais.
      // Fernwirkbefehle und -antworten gehen nie weiter (wie repeater.py).
      if (relaisAn && nutz[0] != 'R' && !istBefehl && !istAntwort) {
        char weiter[144];
        snprintf(weiter, sizeof(weiter), "R%s", nutz);
        uint8_t netid = buf[4];
        if (netid == 0x00) netid = 0xBB;
        else if (netid == 0xBB) netid = 0x00;
        const uint8_t orig[3] = {netid, buf[5], buf[6]};
        if (antwortEinplanen(weiter, orig, 0))   // sofort, vor den PONGs dran
          sag("  -> Relais (sofort, NETID %02X): %s\n", netid, weiter);
        else
          sag("  -> Relais verworfen (Schlange voll)\n");
      }

      if (istBefehl) {
        // Fernwirken: Antwort sofort, kein PONG. Ein vorgemerkter
        // Betriebsartwechsel wartet, bis diese Antwort raus ist.
        char ergebnis[96];
        befehlAusfuehren(text + 2, ergebnis, sizeof(ergebnis));
        char antwort[128];
        snprintf(antwort, sizeof(antwort), "A>%s>%s", stationId, ergebnis);
        if (antwortEinplanen(antwort, ZIEL, 0))
          sag("  -> Fernwirken: %s\n", antwort);
        else
          sag("  -> Fernwirk-Antwort verworfen (Schlange voll)\n");
        radio.startReceive();
        return;
      }
      if (istAntwort) {              // fremde Antwort, nichts zu tun
        radio.startReceive();
        return;
      }
    }
    // Antwort zweifach einplanen: NETID 00 und NETID BB, je Rundruf FFFF.
    // Die Verzoegerung wartet die Taubheit des Senders nach seiner eigenen
    // Aussendung ab; das zweite Paket kommt kurz nach dem ersten. Die
    // NETID steht zusaetzlich im Text (N00/NBB), weil der Empfaenger den
    // Rahmenkopf im Transparentmodus nicht sieht.
    const uint8_t* ziele[2] = {ZIEL, ZIEL_BB};
    const char* netids[2] = {"00", "BB"};
    char antwort[64];
    for (int i = 0; i < 2; i++) {
      snprintf(antwort, sizeof(antwort), "PONG %lu N%s t=%lu ms",
               empfangen, netids[i], (unsigned long)millis());
      if (!antwortEinplanen(antwort, ziele[i], PONG_VERZOEGERUNG_MS + i * 500)) {
        sag("  -> Antwort verworfen (Schlange voll)\n");
        break;
      }
      sag("  -> geplant (NETID %s): %s\n", netids[i], antwort);
    }
  } else {
    sag("  nicht beantwortet (Fehler %d)\n", state);
  }
  radio.startReceive();
}

void loop() {
  static unsigned long letzterPuls = 0;

  // Beide Schnittstellen bedienen: kurze Klartext-Kommandos wie bisher, und
  // alles, was mit "AT" anfaengt, im Dragino-Set (atparms.h).
  static Zeilenleser vomUsb = {{0}, 0};
  char* zeile;
  if (vomUsb.lesen(Serial, &zeile)) kommandoZeile(Serial, zeile);
#if AT_UART_AN
  static Zeilenleser vonUart = {{0}, 0};
  if (vonUart.lesen(Serial1, &zeile)) kommandoZeile(Serial1, zeile);
#endif

  if (millis() - letzterPuls >= 30000) {
    letzterPuls = millis();
    if (zustand.modus == MODUS_LORAWAN)
      sag("alive: LoRaWAN %s, %lu Uplinks, %lu Downlinks\n",
          lwBereit ? "aktiv" : "wartet auf Join", lwUplinks, lwDownlinks);
    else
      sag("alive: %lu empfangen, %lu beantwortet, %u in Schlange, Relais %s\n",
          empfangen, beantwortet, antwortAnzahl, relaisAn ? "an" : "aus");
  }

  if (zustand.modus == MODUS_LORAWAN) {
    lorawanSchleife();
  } else {
    rohSchleife();
  }

  // Ein per Funk vorgemerkter Wechsel wird erst ausgefuehrt, wenn die Antwort
  // darauf gesendet ist -- sonst reisst der Neuaufbau des Funkchips sie weg.
  if (wechselNach != 0xFF && antwortAnzahl == 0 && !transmitFlag) {
    uint8_t neu = wechselNach;
    unsigned long minuten = wechselMinuten;
    wechselNach = 0xFF;
    wechselMinuten = 0;
    if (neu != zustand.modus) {
      modusSetzen(neu, true);
      if (minuten) {
        rueckkehrModus = (neu == MODUS_LORAWAN) ? MODUS_LORA : MODUS_LORAWAN;
        rueckkehrFaellig = millis() + minuten * 60000UL;
        sag("Rueckkehr nach %s in %lu min vorgemerkt (nur im RAM)\n",
            modusName(rueckkehrModus), minuten);
      } else {
        rueckkehrModus = 0xFF;
        rueckkehrFaellig = 0;
      }
    }
  }

  // Rueckfahrkarte: zurueck, falls in der neuen Betriebsart niemand antwortet.
  if (rueckkehrModus != 0xFF && (long)(millis() - rueckkehrFaellig) >= 0) {
    uint8_t zurueck = rueckkehrModus;
    rueckkehrModus = 0xFF;
    rueckkehrFaellig = 0;
    sag("Rueckkehr faellig -> %s\n", modusName(zurueck));
    modusSetzen(zurueck, true);
  }
}
