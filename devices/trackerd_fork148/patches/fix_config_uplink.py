#!/usr/bin/env python3
"""Alle 20 Minuten ein Konfigrahmen als JSON auf fPort 9.

Ueber Funk war bisher nicht nachpruefbar, womit das Geraet gerade arbeitet:
der Statusrahmen (fPort 5) kommt nur nach einem Join, und **welcher der beiden
OTA-Slots laeuft, verraet er gar nicht** -- beide Staende tragen denselben
Versionsstring, sonst loeste jeder Wechsel einen DATA_CLEAR aus.

Deshalb hier ein eigener Rahmen: die aktive App-Partition und die
Einstellungen, die das Verhalten bestimmen, als lesbares JSON.

Drei Entscheidungen, die im Code nicht sichtbar waeren:

* **Gezaehlt wird Schlafzeit, nicht Aufwacher.** Im Bewegungstakt (MTDC 180 s)
  oder im Alarm (ATDC 60 s) waeren "alle 20 Minuten" sonst 7 bis 20 Rahmen je
  Stunde. `cfg_elapsed` summiert die Dauer, die vor jedem Deep Sleep am Timer
  steht; ein Weckruf ueber Taste oder Beschleunigungssensor kuerzt den Schlaf
  und laesst den Rahmen entsprechend frueher faellig werden.
* **Der Rahmen haengt sich an den laufenden Wachzyklus.** Er wird in
  sys_sleep() abgeschickt, nachdem der regulaere Uplink durch ist -- kein
  zweites Aufwachen, kein GPS-Zyklus, kein verlorener Fix. Den os_runloop
  dreht danach gps_send() weiter, bis EV_TXCOMPLETE `send_complete` setzt.
* **Unbestaetigt, auch bei PNACKMD=1.** Der Rahmen traegt keine Position; ein
  ACK dafuer wuerde nur Downlink-Budget kosten.

Abgeschickt wird nur auf dem regulaeren Schlafweg (sys_sleep()). Endet ein
Wachzyklus ueber den Zweig `exti_flag == 2` in alarm_state() -- der Weg nach
einem Weckruf durch Taste oder Beschleunigungssensor --, bleibt der Rahmen
faellig und geht im naechsten regulaeren Zyklus raus. Dort eine Sendeschleife
einzubauen hiesse, in einem Pfad zu warten, der genau dafuer nicht gebaut ist.

Passt das volle JSON nicht in die aktuelle Datenrate, geht eine kurze Fassung
raus. Das ist kein Schoenheitsfehler: unter DR3 sind nur 51 Byte Nutzlast
moeglich, ein zu langer Rahmen wird von LMIC stillschweigend verworfen.
"""
import os
import re
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

if "CFG_INTERVAL_MS" in s:
    sys.exit("schon gepatcht")

# --- 1. Include fuer esp_ota_get_running_partition() -------------------------
marker = '#include "driver/rtc_io.h"'
if s.count(marker) != 1:
    sys.exit("Include-Anker nicht eindeutig (%d)" % s.count(marker))
s = s.replace(marker, marker + '\n#include "esp_ota_ops.h"')

# --- 2. Zaehler, Konstanten, Helfer ------------------------------------------
anker = ('RTC_DATA_ATTR int probe_count = 0;   '
         '/* Verbindungsprobe: jeder 10. Uplink bestaetigt */')
if s.count(anker) != 1:
    sys.exit("RTC-Block nicht eindeutig (%d)" % s.count(anker))

block = anker + r'''

/* --- Konfigrahmen: alle 20 min ein JSON auf fPort 9 ----------------------- */
#define CFG_PORT        9
#define CFG_INTERVAL_MS 1200000UL          /* 20 min */

RTC_DATA_ATTR uint32_t cfg_elapsed = 0;    /* ms Schlaf seit dem letzten Rahmen */
RTC_DATA_ATTR uint8_t  cfg_seen    = 0;    /* 0 = Kaltstart, einmal sofort senden */
static uint8_t cfg_due = 0;                /* dieser Wachzyklus schickt ihn */

/* Vor jedem Deep Sleep aufgerufen: die Dauer, die gleich am Timer steht. */
static void cfg_note_sleep(uint32_t ms) { cfg_elapsed += ms; }

/* Welcher OTA-Slot laeuft? Ueber den Versionsstring ist das nicht zu sehen,
   beide Staende melden denselben -- ein anderer wuerde bei jedem Wechsel
   DATA_CLEAR ausloesen und TDC, INTWK und alles andere loeschen. */
static int cfg_app_slot(void)
{
  const esp_partition_t *part = esp_ota_get_running_partition();
  if(part == NULL)              return -1;
  if(part->address == 0x010000) return 0;
  if(part->address == 0x1F0000) return 1;
  return -1;
}

/* Groesster Anwendungsrumpf der aktuellen Datenrate (EU868), mit Reserve fuer
   MAC-Kommandos. LMIC verwirft einen zu langen Rahmen ohne Meldung. */
static uint8_t cfg_maxpay(void)
{
  uint8_t max;
  switch(LMIC.datarate)
  {
    case 0: case 1: case 2: max = 51;  break;
    case 3:                 max = 115; break;
    default:                max = 222; break;
  }
  return (max > 15) ? (max - 15) : 0;
}
'''
s = s.replace(anker, block)

# --- 3. Der Rahmen selbst, vor device_send() ---------------------------------
anker = "void device_send(osjob_t* j)\n{"
if s.count(anker) != 1:
    sys.exit("device_send() nicht eindeutig (%d)" % s.count(anker))

sender = r'''/* Liefert true, wenn der Rahmen in der Sendeschlange liegt. Nur dann darf der
   Aufrufer send_complete zuruecksetzen -- sonst wartet sys_sleep() ewig auf ein
   EV_TXCOMPLETE, das nie kommt, und das Geraet schlaeft nicht mehr ein. */
bool config_send(void)
{
    if (LMIC.opmode & OP_TXRXPEND)
    {
      Serial.println(F("OP_TXRXPEND, not sending"));
      return false;
    }
    char json[200];
    int n;
    sensor.bat = BatGet();
    /* Zeiten in Sekunden, Schalter als 0/1 -- so, wie AT+... sie liest.
       `pt` bleibt hex, weil AT+PT hex nimmt und ausgibt. */
    n = snprintf(json, sizeof(json),
        "{\"app\":%d,\"fw\":\"%s\",\"tdc\":%u,\"mtdc\":%u,\"atdc\":%u,"
        "\"atst\":%u,\"intwk\":%u,\"lon\":%u,\"pnack\":%u,\"pm\":%u,"
        "\"fd\":%u,\"ftime\":%u,\"pdop\":%u,\"pt\":\"%02x\",\"bat\":%u}",
        cfg_app_slot(), Pro_version,
        (unsigned)(sys.sys_time / 1000), (unsigned)(sys.mtdc / 1000),
        (unsigned)(sys.atdc / 1000), (unsigned)sys.atst,
        (unsigned)sys.Intwk, (unsigned)sys.lon, (unsigned)sys.PNACKmd,
        (unsigned)sys.pedometer, (unsigned)sys.fall_detection,
        (unsigned)(sys.Positioning_time / 1000), (unsigned)sys.pdop_value,
        (unsigned)sys.TF[0], (unsigned)sensor.bat);
    if(n < 0 || (uint8_t)n > cfg_maxpay())
    {
      n = snprintf(json, sizeof(json),
          "{\"app\":%d,\"fw\":\"%s\",\"intwk\":%u,\"tdc\":%u}",
          cfg_app_slot(), Pro_version, (unsigned)sys.Intwk,
          (unsigned)(sys.sys_time / 1000));
      Serial.println("config: kurze Fassung, Datenrate zu klein");
    }
    if(n < 0 || (uint8_t)n > cfg_maxpay())
    {
      Serial.println("config: passt nicht, Rahmen faellt aus");
      return false;
    }
    sys.port = CFG_PORT;
    Serial.printf("config: %s\r\n", json);
    /* Unbestaetigt, auch bei PNACKMD=1: der Rahmen traegt keine Position. */
    LMIC_setTxData2(CFG_PORT, (uint8_t*)json, n, 0);
    Serial.println(F("Packet queued"));
    return true;
}

''' + anker
s = s.replace(anker, sender)

# --- 4. Faelligkeit beim Aufwachen bestimmen ---------------------------------
anker = """  sys.eeprom_init();
  sys.config_Read();
  print_wakeup_reason();"""
if s.count(anker) != 1:
    sys.exit("setup()-Anker nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, anker + r'''
  /* Konfigrahmen faellig? Nach einem Kaltstart einmal sofort -- dann steht
     gleich nach dem Flashen in der Datenbank, welcher Slot laeuft. */
  if(cfg_seen == 0 || cfg_elapsed >= CFG_INTERVAL_MS)
  {
    cfg_due = 1;
    cfg_seen = 1;
  }''')

# --- 5. Absenden, sobald der regulaere Rahmen durch ist ----------------------
anker = """  if (!timeCriticalJobs && send_complete == true && !(LMIC.opmode & OP_TXRXPEND))
  {
    GXHT3x_LowPower();"""
if s.count(anker) != 1:
    sys.exit("sys_sleep()-Anker nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, r'''  if (!timeCriticalJobs && send_complete == true && !(LMIC.opmode & OP_TXRXPEND))
  {
    /* Der regulaere Rahmen ist raus. Ist der Konfigrahmen faellig, geht er
       jetzt hinterher -- gleicher Wachzyklus, eigener Uplink. */
    if(cfg_due == 1)
    {
      cfg_due = 0;
      if(config_send())
      {
        cfg_elapsed = 0;
        send_complete = false;
        return;
      }
    }
    GXHT3x_LowPower();''')

# --- 6. Schlafdauer mitzaehlen ----------------------------------------------
# Es gibt zwei Schlafwege: sys_sleep() fuer den regulaeren Takt und den Zweig
# `exti_flag == 2` in alarm_state(), der nach einem Weckruf ueber Taste oder
# Beschleunigungssensor genommen wird. Beide setzen den Weckzeitpunkt an je
# vier Stellen; eine davon zu vergessen hiesse, dass die Uhr in genau diesem
# Betriebsfall stehen bleibt.
muster = re.compile(r'( *)esp_sleep_enable_timer_wakeup\(([^;]+?)\*1000\);')
treffer = muster.findall(s)
if len(treffer) != 8:
    sys.exit("erwartet 8 Weckzeitpunkte, gefunden %d" % len(treffer))
s = muster.sub(lambda m: "%scfg_note_sleep(%s);\n%sesp_sleep_enable_timer_wakeup(%s*1000);"
               % (m.group(1), m.group(2).strip(), m.group(1), m.group(2)), s)

open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
print("gepatcht:", p)
