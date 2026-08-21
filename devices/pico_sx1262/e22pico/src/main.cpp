// Two operating modes on one SX1262 (Waveshare Pico-LoRa) -- RadioLib.
//
//   MODE_LORA     raw Ebyte channel, as before: 868.125 MHz, SF11/BW500,
//                  CR4/5, LDRO 1, sync word 0x55 (register 0x0740 = 54 54),
//                  preamble 8, 14 dBm, Ebyte framing (magic 2c 12, check
//                  bytes, target address, XOR 0x12), PONG replies and relay.
//   MODE_LORAWAN  LoRaWAN class A, EU868, OTAA against the ChirpStack on the
//                  dell (192.168.5.23), fed by the DLOS8N at 10.9.0.9.
//
// Only one of them runs at a time -- one radio chip, two worlds. The selected
// mode lives in flash (storage.h) and survives a power cut, together with
// the DevNonce and the LoRaWAN session.
//
// Switching works over the air from both sides, because the Pico has no WLAN
// and nobody is plugged into USB up on the mountain:
//
//   raw channel -> LoRaWAN   remote command "C>MODUS LORAWAN [minutes]", the
//                            same language the Brauneck relay station speaks
//                            (devices/pico_sx1262/fernwirk.py). The reply
//                            "A>0E22>..." still goes out on the raw channel,
//                            only then does the mode change.
//   LoRaWAN -> raw channel   downlink on FPort 10, byte 0 = 0x00, optionally
//                            two bytes of minutes until the return.
//
// The optional minute count is the return ticket: if nobody answers in the
// new mode, the node comes back on its own. It lives in RAM only -- a power
// cut in between leaves the node in the last mode that was written to flash.
//
// Reception on the raw channel closely follows the RadioLib example
// SX126x_PingPong: the DIO1 interrupt sets a flag, loop() reads the packet
// with readData() and schedules replies carrying Ebyte-framed timestamps
// (PONG). The NETID is repeated inside the PONG text (N00/NBB) so the
// receiver can read it off its UART -- transparent mode strips the header.
//
// Relay (Ebyte's name for this): with RELAY_ENABLE on, every received frame
// is forwarded once, with an "R" in front of the payload. Frames that were
// already forwarded (payload starts with "R") are not forwarded again --
// loop protection between several relays. Remote commands and their answers
// (C>/A>) are never forwarded, same as in repeater.py.
//
// USB commands: diag | tx | relais [on|off] | modus [lora|lorawan] |
//               lwstat | lwsend <text> | lwreset | src | boot
//   boot jumps into the ROM bootloader (RPI-RP2 drive for firmware.uf2).
//   src prints the node's own source -- it ships inside the flash, generated
//   by embed_source.py before every build. That way the node carries
//   its own blueprint; it can no longer live on a notebook alone.

#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <stdarg.h>

extern "C" {
#include "pico/bootrom.h"
}

// All LoRa parameters live in loraparms.h -- after every start (a power cut
// included) these values, and only these, apply.
#include "loraparms.h"
// The LoRaWAN side, including the mode used after the very first start.
#include "lorawanparms.h"
// Carries mode, DevNonce and session across a power cut.
#include "storage.h"
// AT interface (USB and the UART on GP0/GP1).
#include "atparms.h"
// The node's own source, re-embedded before every build.
#include "source_embed.h"

static const uint8_t ZIEL[3] = ADDRESS;          // NETID 00 + broadcast FFFF
static const uint8_t ZIEL_BB[3] = ADDRESS_NETIDBB; // NETID BB + broadcast FFFF

static bool relaisAn = RELAY_ENABLE;            // switchable at runtime

// Four hex digits taken from the device address -- see loraparms.h.
static char stationId[5] = "0000";

MbedSPI spi(PIN_MISO, PIN_MOSI, PIN_SCK);

// RadioLib keeps the diagnostic API protected; opened up for debugging.
class SX1262Offen : public SX1262 {
 public:
  SX1262Offen(Module* mod) : SX1262(mod) {}
  using SX126x::readRegister;
  using SX126x::getPacketType;
  using SX126x::getStatus;
  using SX126x::getDeviceErrors;
};

SX1262Offen radio = new Module(PIN_CS, PIN_DIO1, PIN_RST, PIN_BUSY, spi);

// Same radio chip, second role. RadioLib ships its own LoRaWAN stack; the
// node re-sets frequency, SF, sync word and IQ before every uplink, which is
// why both modes can share a single Module.
LoRaWANNode node(&radio, &LW_BAND, LW_SUBBAND);

static unsigned long empfangen = 0, beantwortet = 0;
volatile bool operationDone = false;    // set by setFlag()
static bool transmitFlag = false;       // last operation was a reply
static int transmissionState = RADIOLIB_ERR_NONE;

// Everything that has to survive a restart. Defaults for the very first
// start; after that whatever is in flash applies.
static Zustand zustand = { START_MODE, 0, 0, 0, {0}, {0} };

// --- LoRaWAN runtime state -------------------------------------------------
static bool lwBereit = false;                    // session active
static unsigned long lwNaechsterJoin = 0;
static unsigned long lwJoinPause = LW_JOIN_PAUSE_MS;
static unsigned long lwNaechsterUplink = 0;
static unsigned long lwUplinks = 0, lwDownlinks = 0;
static uint8_t lwSeitSicherung = 0;
static float letzteRssi = 0, letzteSnr = 0;      // for the uplink payload

// Last reception, for AT+RECV / AT+RECVB. On the raw channel the port is 0.
static uint8_t letztePort = 0;
static uint8_t letzteDaten[128];
static size_t  letzteDatenLen = 0;

// --- pending mode change ---------------------------------------------------
// A mode change tears the radio chip down and back up; a reply still waiting
// to be sent would be lost. The change is therefore only noted down and
// carried out once the reply queue has drained.
static uint8_t wechselNach = 0xFF;               // 0xFF = nothing pending
static unsigned long wechselMinuten = 0;         // return after n minutes

// Return ticket: RAM only, see the head of this file.
static uint8_t rueckkehrModus = 0xFF;
static unsigned long rueckkehrFaellig = 0;

// Replies wait PONG_DELAY_MS until the E22 has recovered from its own
// transmission. A small queue for bursts.
struct AntwortSlot {
  unsigned long faellig;
  uint8_t rahmen[160];   // 8 header bytes + up to 128 payload ("R"+127)
  size_t len;
};
static AntwortSlot antworten[8];
static uint8_t antwortAnzahl = 0;

// Reports a reception to the AT interface; defined further down.
static void atEmpfangMelden(uint8_t port, const uint8_t* daten, size_t len);

// Called by the DIO1 interrupt when TX or RX has finished.
static void setFlag(void) { operationDone = true; }

// The mbed UART has no printf; a detour of our own via vsnprintf. Messages
// go to both interfaces, USB and AT UART -- a host on the two wires sees the
// same running commentary as someone on the USB cable.
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
  return m == MODE_LORAWAN ? "LoRaWAN" : "raw channel";
}

// adresse[3] = NETID, ZH, ZL. Default is NETID 00 + broadcast FFFF.
// Length-based variant so bytes without a terminating zero work (AT+SENDB).
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

// Puts a frame into the reply queue. A delay of 0 means straight away.
static bool antwortEinplanen(const char* text, const uint8_t* adresse,
                             unsigned long verzoegerung) {
  if (antwortAnzahl >= 8) return false;
  AntwortSlot& s = antworten[antwortAnzahl++];
  s.faellig = millis() + verzoegerung;
  s.len = ebyteRahmen(text, s.rahmen, adresse);
  return true;
}

// The SX126x has no version register like the SX127x (0x42 -> 0x12 there).
// Identification goes through GetStatus, GetDeviceErrors and readable regs.
static void diag() {
  uint8_t sw[2] = {0, 0};
  radio.readRegister(0x0740, sw, 2);
  sag("diag: Status 0x%02X  DeviceErrors 0x%04X  PacketType 0x%02X  "
      "SyncReg 0x0740 = %02X %02X\n",
      radio.getStatus(), radio.getDeviceErrors(), radio.getPacketType(),
      sw[0], sw[1]);
  sag("diag: IRQ 0x%08lX\n", (unsigned long)radio.getIrqFlags());
}

// --- flash -----------------------------------------------------------------

static void sicherungSchreiben(const char* warum) {
  if (zustandSichern(zustand))
    sag("flash: saved (%s, seq %lu)\n", warum, (unsigned long)zustandFolge());
  else
    sag("flash: SAVE FAILED (%s)\n", warum);
}

// --- operating modes -------------------------------------------------------

// Bring up the raw Ebyte channel and go into continuous receive.
static bool rohBetriebEinrichten() {
  radio.clearDio1Action();
  int state = radio.begin(FREQ_MHZ, BW_KHZ, LORA_SF, LORA_CR, SYNCWORD,
                          POWER_DBM, PREAMBLE, TCXO_V);
  if (state != RADIOLIB_ERR_NONE) {
    sag("SX1262 begin failed: %d\n", state);
    return false;
  }
  // Both board traps from lora_p2p.py: DIO2 drives the antenna switch, and
  // LDRO must be 1 (Ebyte factory value; the automatic setting would pick 0,
  // and then only the header locks while every payload fails its CRC).
  radio.setDio2AsRfSwitch(true);
  radio.forceLDRO(LDRO_ON);

  // Whatever the LoRaWAN mode left behind no longer applies.
  antwortAnzahl = 0;
  transmitFlag = false;
  operationDone = false;

  radio.setDio1Action(setFlag);        // interrupt on DIO1
  state = radio.startReceive();        // continuous receive
  if (state != RADIOLIB_ERR_NONE) {
    sag("startReceive failed: %d\n", state);
    return false;
  }
  return true;
}

// Prepare the radio chip for LoRaWAN. Frequency, SF, sync word, preamble and
// IQ are set by RadioLib's LoRaWAN stack before every uplink -- what is left
// here is only what the stack does not touch.
static bool lorawanBetriebEinrichten() {
  radio.clearDio1Action();             // the stack installs its own
  int state = radio.begin(FREQ_MHZ, BW_KHZ, LORA_SF, LORA_CR, SYNCWORD,
                          POWER_DBM, PREAMBLE, TCXO_V);
  if (state != RADIOLIB_ERR_NONE) {
    sag("SX1262 begin failed: %d\n", state);
    return false;
  }
  radio.setDio2AsRfSwitch(true);       // antenna switch, as on the raw channel
  // IMPORTANT: the raw channel forces LDRO 1. LoRaWAN needs the automatic
  // setting, otherwise DR5 (SF7 BW125) would carry an LDRO bit the gateway
  // does not expect -- the uplink would be unreadable.
  radio.autoLDRO();

  lwBereit = false;
  lwSeitSicherung = 0;
  lwNaechsterJoin = millis();          // first join attempt right away
  lwJoinPause = LW_JOIN_PAUSE_MS;
  return true;
}

static void modusSetzen(uint8_t neu, bool sichern) {
  // Save the session when leaving LoRaWAN mode. Without this the uplink
  // counter falls back to the last saved state (LW_SESSION_EVERY) when
  // switching back, and the network server drops the next uplinks as replays
  // -- measured on 21 Aug 2026: after the switch FCntUp was 0 again and
  // ChirpStack said nothing about it.
  if (zustand.modus == MODE_LORAWAN && neu != MODE_LORAWAN && lwBereit) {
    memcpy(zustand.sitzung, node.getBufferSession(), sizeof(zustand.sitzung));
    zustand.hatSitzung = 1;
    lwSeitSicherung = 0;
    sichern = true;
  }
  zustand.modus = neu;
  bool ok = (neu == MODE_LORAWAN) ? lorawanBetriebEinrichten()
                                   : rohBetriebEinrichten();
  if (sichern) sicherungSchreiben("mode");
  sag("mode: %s%s\n", modusName(neu), ok ? "" : " (RADIO ERROR)");
}

// Note a mode change; it runs as soon as the reply queue has drained.
static void wechselVormerken(uint8_t neu, unsigned long minuten) {
  wechselNach = neu;
  wechselMinuten = minuten;
}

// --- LoRaWAN ---------------------------------------------------------------

static void lorawanJoin() {
  static const uint8_t appKey[] = LW_APP_KEY;

  // nwkKey = NULL: LoRaWAN 1.0.x, there is only the AppKey. A second key
  // would switch RadioLib to 1.1, and the join would fail against the device
  // profile (LORAWAN_1_0_3) in ChirpStack.
  int16_t state = node.beginOTAA(LW_JOIN_EUI, LW_DEV_EUI, NULL, appKey);
  if (state != RADIOLIB_ERR_NONE) {
    sag("beginOTAA failed: %d\n", state);
    lwNaechsterJoin = millis() + lwJoinPause;
    return;
  }

  // The order is mandatory: beginOTAA clears nonces and session and computes
  // the key checksum that setBufferNonces compares against.
  if (zustand.hatNonces) {
    int16_t n = node.setBufferNonces(zustand.nonces);
    if (n != RADIOLIB_ERR_NONE) {
      sag("stored nonces discarded (%d) -- fresh join\n", n);
      zustand.hatNonces = 0;
      zustand.hatSitzung = 0;
    }
  }
  if (zustand.hatSitzung) {
    int16_t s = node.setBufferSession(zustand.sitzung);
    if (s != RADIOLIB_ERR_NONE) {
      sag("stored session discarded (%d) -- new join\n", s);
      zustand.hatSitzung = 0;
    }
  }

  sag("LoRaWAN: joining (DevEUI %08lX%08lX) ...\n",
      (unsigned long)(LW_DEV_EUI >> 32), (unsigned long)(LW_DEV_EUI & 0xFFFFFFFFUL));
  state = node.activateOTAA();

  // Even a failed attempt burns a DevNonce -- it must never repeat, so it is
  // saved in every case.
  memcpy(zustand.nonces, node.getBufferNonces(), sizeof(zustand.nonces));
  zustand.hatNonces = 1;

  if (state == RADIOLIB_LORAWAN_NEW_SESSION || state == RADIOLIB_LORAWAN_SESSION_RESTORED) {
    lwBereit = true;
    node.setADR(LW_ADR);
    node.setDatarate(LW_DATARATE);
    memcpy(zustand.sitzung, node.getBufferSession(), sizeof(zustand.sitzung));
    zustand.hatSitzung = 1;
    sicherungSchreiben(state == RADIOLIB_LORAWAN_NEW_SESSION ? "join"
                                                             : "session");
    sag("LoRaWAN up: DevAddr %08lX, %s\n", (unsigned long)node.getDevAddr(),
        state == RADIOLIB_LORAWAN_NEW_SESSION ? "newly joined"
                                              : "session resumed");
    lwNaechsterUplink = millis();       // first uplink right away
    lwJoinPause = LW_JOIN_PAUSE_MS;
  } else {
    sicherungSchreiben("DevNonce");
    lwNaechsterJoin = millis() + lwJoinPause;
    sag("LoRaWAN: join failed (%d), next attempt in %lu s\n",
        state, lwJoinPause / 1000UL);
    lwJoinPause *= 2;
    if (lwJoinPause > LW_JOIN_PAUSE_MAX_MS) lwJoinPause = LW_JOIN_PAUSE_MAX_MS;
  }
}

// 8 bytes, big endian: uptime [min], frames received and answered on the raw
// channel, RSSI and SNR of the last raw packet.
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

// Downlink on the control port: back to the raw channel, optionally timed.
static void lorawanDownlink(const uint8_t* daten, size_t len, uint8_t port) {
  sag("downlink FPort %u, %u B:", port, (unsigned)len);
  for (size_t i = 0; i < len; i++) sag(" %02x", daten[i]);
  sag("\n");

  atEmpfangMelden(port, daten, len);

  if (port != LW_CONTROL_PORT || len < 1) return;

  switch (daten[0]) {
    case 0x00: {                       // to the raw channel
      unsigned long minuten = 0;
      if (len >= 3) minuten = ((unsigned long)daten[1] << 8) | daten[2];
      sag("control command: raw channel%s\n", minuten ? ", return noted" : "");
      wechselVormerken(MODE_LORA, minuten);
      break;
    }
    case 0x01:                         // stay where we are
      sag("control command: staying on LoRaWAN\n");
      rueckkehrModus = 0xFF;
      rueckkehrFaellig = 0;
      break;
    case 0x02:                         // switch the relay
      if (len >= 2) {
        relaisAn = daten[1] != 0;
        sag("control command: relay %s\n", relaisAn ? "on" : "off");
      }
      break;
    default:
      sag("control command unknown: 0x%02x\n", daten[0]);
      break;
  }
}

// One uplink including both receive windows. sendReceive blocks for a few
// seconds while doing so -- class A knows no other way.
static void lorawanUplink(const uint8_t* nutz, size_t len, uint8_t port) {
  uint8_t ab[255];                     // as in the RadioLib example
  size_t abLen = sizeof(ab);
  LoRaWANEvent_t hin, her;

  int16_t state = node.sendReceive(nutz, len, port, ab, &abLen, LW_CONFIRMED,
                                   &hin, &her);

  if (state < RADIOLIB_ERR_NONE) {
    sag("uplink ERROR %d\n", state);
    if (state == RADIOLIB_ERR_NETWORK_NOT_JOINED || state == RADIOLIB_ERR_SESSION_DISCARDED) {
      lwBereit = false;                // session gone -- join again
      zustand.hatSitzung = 0;
      lwNaechsterJoin = millis() + LW_JOIN_PAUSE_MS;
    }
    lwNaechsterUplink = millis() + 60UL * 1000UL;
    return;
  }

  lwUplinks++;
  sag("uplink %lu: FCntUp %lu, DR %u, %lu ms air time\n", lwUplinks,
      (unsigned long)node.getFCntUp(), hin.datarate,
      (unsigned long)node.getLastToA());

  // Session goes to flash only every nth uplink, see LW_SESSION_EVERY.
  if (++lwSeitSicherung >= LW_SESSION_EVERY) {
    memcpy(zustand.sitzung, node.getBufferSession(), sizeof(zustand.sitzung));
    zustand.hatSitzung = 1;
    sicherungSchreiben("session");
    lwSeitSicherung = 0;
  }

  // Next uplink: the later of the wanted interval and the duty cycle lock.
  unsigned long wartet = (unsigned long)node.timeUntilUplink();
  lwNaechsterUplink = millis() + (wartet > LW_INTERVAL_MS ? wartet : LW_INTERVAL_MS);

  if (state > 0) {                     // downlink in window 1 or 2
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

// --- remote control over the raw channel -----------------------------------
// Same language as the Brauneck relay station (fernwirk.py): command
// "C>NAME [value]", answer "A><id>>text". Deliberately without
// authentication -- whoever is in radio range can reconfigure the node. For a
// crisis system that is the right trade: radio carries precisely when nothing
// else does.

static void grossSchreiben(char* s) {
  for (; *s; s++) if (*s >= 'a' && *s <= 'z') *s -= 32;
}

static void befehlAusfuehren(const char* befehl, char* out, size_t outsz) {
  char name[16] = "", wert[16] = "", zusatz[16] = "";
  sscanf(befehl, "%15s %15s %15s", name, wert, zusatz);
  grossSchreiben(name);
  grossSchreiben(wert);

  if (strcmp(name, "MODE") == 0) {
    if (wert[0] == 0) {
      snprintf(out, outsz, "MODE %s", zustand.modus == MODE_LORAWAN ? "LORAWAN" : "LORA");
      return;
    }
    uint8_t neu;
    if (strcmp(wert, "LORAWAN") == 0) neu = MODE_LORAWAN;
    else if (strcmp(wert, "LORA") == 0) neu = MODE_LORA;
    else { snprintf(out, outsz, "MODE: LORA or LORAWAN"); return; }
    unsigned long minuten = zusatz[0] ? strtoul(zusatz, NULL, 10) : 0;
    wechselVormerken(neu, minuten);
    if (minuten)
      snprintf(out, outsz, "MODE %s, return in %lu min", wert, minuten);
    else
      snprintf(out, outsz, "MODE %s", wert);
    return;
  }

  if (strcmp(name, "STATUS") == 0) {
    snprintf(out, outsz, "id%s %s rx%lu tx%lu %lus relay%d lw%lu",
             stationId, zustand.modus == MODE_LORAWAN ? "LORAWAN" : "LORA",
             empfangen, beantwortet, millis() / 1000UL, relaisAn ? 1 : 0,
             lwUplinks);
    return;
  }

  if (strcmp(name, "RELAY") == 0 && (wert[0] == '0' || wert[0] == '1')) {
    relaisAn = wert[0] == '1';
    snprintf(out, outsz, "RELAY %s", relaisAn ? "on" : "off");
    return;
  }

  if (strcmp(name, "ID") == 0) {
    // Read-only: the id is the device address, not freely chosen.
    snprintf(out, outsz, "ID %s", stationId);
    return;
  }

  if (strcmp(name, "PING") == 0) {
    snprintf(out, outsz, "PONG %lus", millis() / 1000UL);
    return;
  }

  snprintf(out, outsz, "unknown: %s", name);
}

// --- AT interface ----------------------------------------------------------
// The command set of the Dragino devices, so the node can be integrated like
// an LA66 (atparms.h explains the template and the deviations). Answers go
// only to the interface that asked; running commentary (sag) goes to both.

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

// "A8 40 41 ..." as in the LA66's AT+CFG.
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
  atAntwort(s, "AT+APPKEY=<in device>");
  atAntwort(s, "AT+DADDR=%08lX", (unsigned long)(lwBereit ? node.getDevAddr() : 0));
  atAntwort(s, "AT+NJM=1");
  atAntwort(s, "AT+NJS=%d", lwBereit ? 1 : 0);
  atAntwort(s, "AT+CLASS=A");
  atAntwort(s, "AT+ADR=%d", LW_ADR ? 1 : 0);
  atAntwort(s, "AT+DR=%d", LW_DATARATE);
  atAntwort(s, "AT+FCU=%lu", (unsigned long)(lwBereit ? node.getFCntUp() : 0));
  atAntwort(s, "AT+LORAWAN=%d", zustand.modus == MODE_LORAWAN ? 1 : 0);
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
  atAntwort(s, "AT                      is anyone there");
  atAntwort(s, "AT?                     this list");
  atAntwort(s, "ATZ                     restart");
  atAntwort(s, "AT+CFG                  show everything");
  atAntwort(s, "AT+LORAWAN=0|1[,min]    0 = raw channel, 1 = LoRaWAN");
  atAntwort(s, "AT+JOIN                 trigger an OTAA join");
  atAntwort(s, "AT+NJS=?                1 = session active");
  atAntwort(s, "AT+SEND=<cfm>,<port>,<len>,<text>");
  atAntwort(s, "AT+SENDB=<cfm>,<port>,<len>,<hex>");
  atAntwort(s, "AT+RECV=?  AT+RECVB=?   last reception (text resp. hex)");
  atAntwort(s, "AT+RELAY=0|1            relay of the raw channel");
  atAntwort(s, "AT+DEUI=? AT+APPEUI=? AT+DADDR=? AT+FCU=? AT+DR=? AT+ADR=?");
  atAntwort(s, "AT+FRE=? AT+SF=? AT+BW=? AT+CR=? AT+POWER=? AT+SYNCWORD=?");
  atAntwort(s, "  (raw channel parameters are read-only, see loraparms.h)");
}

// Sending from the AT set: a LoRaWAN uplink in LoRaWAN mode, an Ebyte frame
// on the raw channel. One command, two carriers -- that is the whole point.
static bool atSenden(Stream &s, const uint8_t* daten, size_t len, uint8_t port,
                     bool bestaetigt) {
  if (zustand.modus == MODE_LORAWAN) {
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
    lwNaechsterUplink = millis() + (wartet > LW_INTERVAL_MS ? wartet : LW_INTERVAL_MS);
    return true;
  }
  if (len > 128) { atAntwort(s, "AT_PARAM_ERROR"); return false; }
  uint8_t rahmen[160];
  size_t n = ebyteRahmenN(daten, len, rahmen);
  radio.standby();
  int st = radio.transmit(rahmen, n);
  radio.startReceive();
  // transmit() blocks, but the DIO1 interrupt sets the flag anyway -- without
  // clearing it the main loop counted the node's own transmission as an empty
  // reception (measured: "RX #1 ... 0 B").
  operationDone = false;
  if (st != RADIOLIB_ERR_NONE) { atAntwort(s, "AT_ERROR (%d)", st); return false; }
  return true;
}

// zeile is everything after "AT". Returns true when "OK" should follow.
static bool atBefehl(Stream &s, char* zeile) {
  if (zeile[0] == 0) return true;                    // plain AT
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

  // --- read-only identifiers ---
  if (strcmp(name, "DEUI") == 0)   { char e[24]; atEui(e, sizeof(e), LW_DEV_EUI);  atAntwort(s, "%s", e); return true; }
  if (strcmp(name, "APPEUI") == 0) { char e[24]; atEui(e, sizeof(e), LW_JOIN_EUI); atAntwort(s, "%s", e); return true; }
  if (strcmp(name, "APPKEY") == 0) { atAntwort(s, "<in device>"); return true; }
  if (strcmp(name, "ID") == 0)     { atAntwort(s, "%s", stationId); return true; }
  // VERSION as an alias: Dragino firmwares do not all spell it the same.
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

  // --- raw channel parameters: readable, not writable ---
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

  // --- operating mode ---
  if (strcmp(name, "LORAWAN") == 0) {
    if (!wert || frage) {
      atAntwort(s, "%d", zustand.modus == MODE_LORAWAN ? 1 : 0);
      return true;
    }
    char* komma = strchr(wert, ',');
    unsigned long minuten = 0;
    if (komma) { *komma = 0; minuten = strtoul(komma + 1, NULL, 10); }
    if (wert[0] != '0' && wert[0] != '1') { atAntwort(s, "AT_PARAM_ERROR"); return false; }
    wechselVormerken(wert[0] == '1' ? MODE_LORAWAN : MODE_LORA, minuten);
    return true;
  }

  if (strcmp(name, "RELAY") == 0) {
    if (!wert || frage) { atAntwort(s, "%d", relaisAn ? 1 : 0); return true; }
    if (wert[0] != '0' && wert[0] != '1') { atAntwort(s, "AT_PARAM_ERROR"); return false; }
    relaisAn = wert[0] == '1';
    return true;
  }

  // --- LoRaWAN operation ---
  if (strcmp(name, "ADR") == 0) {
    if (!wert || frage) { atAntwort(s, "%d", LW_ADR ? 1 : 0); return true; }
    node.setADR(wert[0] == '1');
    return true;
  }
  if (strcmp(name, "DR") == 0) {
    if (!wert || frage) { atAntwort(s, "%d", LW_DATARATE); return true; }
    if (node.setDatarate((uint8_t)strtoul(wert, NULL, 10)) != RADIOLIB_ERR_NONE) {
      atAntwort(s, "AT_PARAM_ERROR");
      return false;
    }
    return true;
  }
  if (strcmp(name, "JOIN") == 0) {
    if (zustand.modus != MODE_LORAWAN) { atAntwort(s, "AT_ERROR"); return false; }
    lwNaechsterJoin = millis();
    lwBereit = false;
    return true;
  }

  // --- sending and receiving ---
  if (strcmp(name, "SEND") == 0 || strcmp(name, "SENDB") == 0) {
    bool binaer = strcmp(name, "SENDB") == 0;
    if (!wert) { atAntwort(s, "AT_PARAM_ERROR"); return false; }
    // <confirmed>,<fPort>,<length>,<data> -- the LA66 format.
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
    // The LA66 length field is checked, not believed.
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

// Reports a reception unsolicited, LA66 format, on both interfaces.
static void atEmpfangMelden(uint8_t port, const uint8_t* daten, size_t len) {
  if (len == 0) return;      // pure MAC downlinks (FPort 0) carry no data
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

// Read line by line without stalling the main loop -- readStringUntil would
// block for up to a second and shift the PONG timing.
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

// --- start -----------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(2000);                  // let USB CDC come up first

  snprintf(stationId, sizeof(stationId), "%04lX",
           (unsigned long)(LW_DEV_EUI & 0xFFFFUL));

#if AT_UART_AN
  // The AT UART on GP0 (TX) / GP1 (RX) -- the way in for a host without USB.
  Serial1.begin(AT_UART_BAUD);
#endif

  spi.begin();

  // Mode, DevNonce and session from flash -- or the defaults.
  if (zustandLaden(zustand))
    sag("flash: state loaded (seq %lu, %s, nonces %d, session %d)\n",
        (unsigned long)zustandFolge(), modusName(zustand.modus),
        zustand.hatNonces, zustand.hatSitzung);
  else
    sag("flash: nothing stored yet, default %s\n", modusName(zustand.modus));

  if (zustand.modus == MODE_LORAWAN) {
    if (!lorawanBetriebEinrichten()) while (true) delay(1000);
  } else {
    if (!rohBetriebEinrichten()) while (true) delay(1000);

    // After every start (a power cut included) broadcast the parameters from
    // loraparms.h once -- the gateway listens in and files them in the DB.
    char parm[96];
    snprintf(parm, sizeof(parm),
             "PARM %.3fMHz SF%d BW%.0f CR4/%d SYNC%02X LDRO%d PRE%d %ddBm",
             FREQ_MHZ, LORA_SF, BW_KHZ, LORA_CR, SYNCWORD, LDRO_ON ? 1 : 0,
             PREAMBLE, POWER_DBM);
    uint8_t rahmen[128];
    size_t n = ebyteRahmen(parm, rahmen);
    radio.standby();
    int pstate = radio.transmit(rahmen, n);
    sag("parameters broadcast: %s (%s)\n", parm,
        pstate == RADIOLIB_ERR_NONE ? "ok" : "ERROR");
    radio.startReceive();
    operationDone = false;

    sag("E22 profile active: %.3f MHz SF%d BW%.0f CR4/%d LDRO1 sync 0x%02X %d dBm\n",
        FREQ_MHZ, LORA_SF, BW_KHZ, LORA_CR, SYNCWORD, POWER_DBM);
    sag("waiting for packets -- one timestamped reply per packet\n");
  }

  sag("station %s, mode %s, relay %s\n", stationId,
      modusName(zustand.modus), relaisAn ? "on" : "off");
  sag("commands: diag | tx | relay [on|off] | mode [lora|lorawan] |\n");
  sag("          lwstat | lwsend <text> | lwreset | src | boot\n");
  sag("AT set as on the LA66: AT | AT? | AT+CFG | AT+SENDB=... | AT+LORAWAN=0|1\n");
  sag("over the air: C>MODE LORAWAN [min] | C>STATUS | C>RELAY 0|1\n");
  diag();
}

// Prints the embedded source over USB. In small bites, because the CDC
// interface only takes a few hundred bytes at a time -- in one go it silently
// swallows the rest.
static void quelltextAusgeben(const char *name, const char *text) {
  size_t laenge = strlen(text);
  sag("---- %s (%u bytes) ----\n", name, (unsigned)laenge);
  for (size_t i = 0; i < laenge; i += 128) {
    size_t n = laenge - i < 128 ? laenge - i : 128;
    Serial.write((const uint8_t *)text + i, n);
    Serial.flush();
  }
  // A newline only if the file does not end with one anyway: that keeps the
  // dump byte-identical to the original (`src > main.cpp` is enough).
  if (laenge && text[laenge - 1] != '\n') Serial.write('\n');
  sag("---- end of %s ----\n", name);
}

static void lwstat() {
  sag("LoRaWAN: %s, uplinks %lu, downlinks %lu\n",
      lwBereit ? "session active" : "not joined", lwUplinks, lwDownlinks);
  if (lwBereit) {
    sag("  DevAddr %08lX, FCntUp %lu, next uplink in %ld s\n",
        (unsigned long)node.getDevAddr(), (unsigned long)node.getFCntUp(),
        (long)(lwNaechsterUplink - millis()) / 1000L);
  } else if (zustand.modus == MODE_LORAWAN) {
    sag("  next join in %ld s\n", (long)(lwNaechsterJoin - millis()) / 1000L);
  }
  sag("  flash: seq %lu, nonces %d, session %d\n",
      (unsigned long)zustandFolge(), zustand.hatNonces, zustand.hatSitzung);
  if (rueckkehrModus != 0xFF)
    sag("  return to %s in %ld s\n", modusName(rueckkehrModus),
        (long)(rueckkehrFaellig - millis()) / 1000L);
}

// --- console commands ------------------------------------------------------

static void usbKommando(String cmd) {
  if (cmd == "boot") {
    sag("jumping into the bootloader...\n");
    Serial.flush();
    delay(50);
    reset_usb_boot(0, 0);
  } else if (cmd == "diag") {
    diag();
  } else if (cmd == "relay on") {
    relaisAn = true;
    sag("relay: on\n");
  } else if (cmd == "relay off") {
    relaisAn = false;
    sag("relay: off\n");
  } else if (cmd == "relay") {
    sag("relay: %s\n", relaisAn ? "on" : "off");
  } else if (cmd == "src") {
    for (size_t i = 0; i < SOURCE_COUNT; i++)
      quelltextAusgeben(SOURCE_NAMES[i], SOURCE_TEXTS[i]);
  } else if (cmd == "mode") {
    sag("mode: %s\n", modusName(zustand.modus));
  } else if (cmd == "mode lora") {
    rueckkehrModus = 0xFF;
    modusSetzen(MODE_LORA, true);
  } else if (cmd == "mode lorawan") {
    rueckkehrModus = 0xFF;
    modusSetzen(MODE_LORAWAN, true);
  } else if (cmd == "lwstat") {
    lwstat();
  } else if (cmd == "lwreset") {
    // Drop session and nonces -- the next join starts from zero. The network
    // server has to be reset as well, otherwise it rejects the repeated
    // DevNonce as a replay.
    node.clearSession();
    zustand.hatNonces = 0;
    zustand.hatSitzung = 0;
    memset(zustand.nonces, 0, sizeof(zustand.nonces));
    memset(zustand.sitzung, 0, sizeof(zustand.sitzung));
    sicherungSchreiben("lwreset");
    lwBereit = false;
    lwNaechsterJoin = millis();
    sag("LoRaWAN: session and nonces cleared\n");
  } else if (cmd.startsWith("lwsend ")) {
    if (zustand.modus != MODE_LORAWAN || !lwBereit) {
      sag("lwsend: only with an active LoRaWAN session\n");
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
    sag("tx %s: %s\n", text, txstate == RADIOLIB_ERR_NONE ? "ok" : "ERROR");
    radio.startReceive();
    operationDone = false;          // do not count our own transmission as RX
  }
}

// One incoming line: either an AT command or a short plain command.
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

// --- raw channel -----------------------------------------------------------

static void rohSchleife() {
  // Send a due reply if the transmitter is free.
  if (!transmitFlag && antwortAnzahl > 0 &&
      (long)(millis() - antworten[0].faellig) >= 0) {
    AntwortSlot s = antworten[0];
    for (uint8_t i = 1; i < antwortAnzahl; i++) antworten[i - 1] = antworten[i];
    antwortAnzahl--;
    transmissionState = radio.startTransmit(s.rahmen, s.len);
    if (transmissionState == RADIOLIB_ERR_NONE) {
      transmitFlag = true;
    } else {
      sag("  -> reply TX ERROR %d\n", transmissionState);
      radio.startReceive();
    }
  }

  if (!operationDone) return;
  operationDone = false;

  if (transmitFlag) {
    // The timestamp reply is out -- listen again.
    transmitFlag = false;
    if (transmissionState == RADIOLIB_ERR_NONE) {
      beantwortet++;
    } else {
      sag("  -> reply TX ERROR %d\n", transmissionState);
    }
    radio.startReceive();
    return;
  }

  // A packet came in.
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
      sag("  Ebyte frame ok: %s\n", nutz);
      atEmpfangMelden(0, (const uint8_t*)nutz, strlen(nutz));

      // A forwarded frame carries an "R" in front; the command behind it
      // still counts, otherwise nothing could be reached through a relay.
      const char* text = nutz[0] == 'R' ? nutz + 1 : nutz;
      bool istBefehl  = text[0] == 'C' && text[1] == '>';
      bool istAntwort = text[0] == 'A' && text[1] == '>';

      // Relay: forward the frame once, with an "R" in front of the payload.
      // The NETID is crossed over as the E90-DTU does it (00 <-> BB) so the
      // forward reaches the other group; the target address is kept. Frames
      // whose payload already starts with "R" have been forwarded before --
      // loop protection between several relays. Remote commands and their
      // answers are never forwarded (as in repeater.py).
      if (relaisAn && nutz[0] != 'R' && !istBefehl && !istAntwort) {
        char weiter[144];
        snprintf(weiter, sizeof(weiter), "R%s", nutz);
        uint8_t netid = buf[4];
        if (netid == 0x00) netid = 0xBB;
        else if (netid == 0xBB) netid = 0x00;
        const uint8_t orig[3] = {netid, buf[5], buf[6]};
        if (antwortEinplanen(weiter, orig, 0))   // at once, ahead of the PONGs
          sag("  -> relay (immediate, NETID %02X): %s\n", netid, weiter);
        else
          sag("  -> relay dropped (queue full)\n");
      }

      if (istBefehl) {
        // Remote control: answer at once, no PONG. A pending mode change
        // waits until this answer has gone out.
        char ergebnis[96];
        befehlAusfuehren(text + 2, ergebnis, sizeof(ergebnis));
        char antwort[128];
        snprintf(antwort, sizeof(antwort), "A>%s>%s", stationId, ergebnis);
        if (antwortEinplanen(antwort, ZIEL, 0))
          sag("  -> remote command: %s\n", antwort);
        else
          sag("  -> remote answer dropped (queue full)\n");
        radio.startReceive();
        return;
      }
      if (istAntwort) {              // someone else's answer, nothing to do
        radio.startReceive();
        return;
      }
    }
    // Schedule the reply twice: NETID 00 and NETID BB, broadcast FFFF each.
    // The delay waits out the sender's deafness after its own transmission;
    // the second packet follows shortly after the first. The NETID is also
    // written into the text (N00/NBB) because the receiver cannot see the
    // frame header in transparent mode.
    const uint8_t* ziele[2] = {ZIEL, ZIEL_BB};
    const char* netids[2] = {"00", "BB"};
    char antwort[64];
    for (int i = 0; i < 2; i++) {
      snprintf(antwort, sizeof(antwort), "PONG %lu N%s t=%lu ms",
               empfangen, netids[i], (unsigned long)millis());
      if (!antwortEinplanen(antwort, ziele[i], PONG_DELAY_MS + i * 500)) {
        sag("  -> reply dropped (queue full)\n");
        break;
      }
      sag("  -> scheduled (NETID %s): %s\n", netids[i], antwort);
    }
  } else {
    sag("  not answered (error %d)\n", state);
  }
  radio.startReceive();
}

void loop() {
  static unsigned long letzterPuls = 0;

  // Serve both interfaces: short plain commands as before, and everything
  // starting with "AT" in the Dragino set (atparms.h).
  static Zeilenleser vomUsb = {{0}, 0};
  char* zeile;
  if (vomUsb.lesen(Serial, &zeile)) kommandoZeile(Serial, zeile);
#if AT_UART_AN
  static Zeilenleser vonUart = {{0}, 0};
  if (vonUart.lesen(Serial1, &zeile)) kommandoZeile(Serial1, zeile);
#endif

  if (millis() - letzterPuls >= 30000) {
    letzterPuls = millis();
    if (zustand.modus == MODE_LORAWAN)
      sag("alive: LoRaWAN %s, %lu uplinks, %lu downlinks\n",
          lwBereit ? "up" : "waiting for join", lwUplinks, lwDownlinks);
    else
      sag("alive: %lu received, %lu answered, %u queued, relay %s\n",
          empfangen, beantwortet, antwortAnzahl, relaisAn ? "on" : "off");
  }

  if (zustand.modus == MODE_LORAWAN) {
    lorawanSchleife();
  } else {
    rohSchleife();
  }

  // A mode change requested over the air runs only once the answer to it has
  // been sent -- otherwise bringing the radio back up would tear it away.
  if (wechselNach != 0xFF && antwortAnzahl == 0 && !transmitFlag) {
    uint8_t neu = wechselNach;
    unsigned long minuten = wechselMinuten;
    wechselNach = 0xFF;
    wechselMinuten = 0;
    if (neu != zustand.modus) {
      modusSetzen(neu, true);
      if (minuten) {
        rueckkehrModus = (neu == MODE_LORAWAN) ? MODE_LORA : MODE_LORAWAN;
        rueckkehrFaellig = millis() + minuten * 60000UL;
        sag("return to %s in %lu min noted (RAM only)\n",
            modusName(rueckkehrModus), minuten);
      } else {
        rueckkehrModus = 0xFF;
        rueckkehrFaellig = 0;
      }
    }
  }

  // Return ticket: come back if nobody answers in the new mode.
  if (rueckkehrModus != 0xFF && (long)(millis() - rueckkehrFaellig) >= 0) {
    uint8_t zurueck = rueckkehrModus;
    rueckkehrModus = 0xFF;
    rueckkehrFaellig = 0;
    sag("return due -> %s\n", modusName(zurueck));
    modusSetzen(zurueck, true);
  }
}
