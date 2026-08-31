#!/usr/bin/env python3
"""Alarm endet nach 99 Uplinks -- gezaehlt nur im Speicher.

Der Werksstand beendet einen Alarm nie von allein. Er haette die Mechanik:
`sys.alarm_count++` in `TrackerD.ino` zaehlt die Alarmrahmen, und ein Block
prueft auf `== 60`. Erreicht wird die 60 nie, weil `setup()` den Zaehler bei
jedem Aufwachen nullt -- und jeder Alarmzyklus ist wegen des Deep Sleep ein
eigener Boot. Gemessen am 31.08.2026: ein versehentlich ausgeloester Alarm lief
ueber eine Stunde und erzeugte im ATDC-Takt 338 Uplinks.

Dieser Patch laesst `sys.alarm_count` unangetastet und zaehlt selbst. Der
Grund ist die Vorgabe, **nicht ins NVRAM zu schreiben**: `alarm_count` wandert
ueber `config_Write()` ins EEPROM (`common.cpp` 517 schreibt, 777 liest), jede
Runde also ein Schreibzugriff auf den Flash. Der eigene Zaehler liegt in
`RTC_DATA_ATTR` -- er ueberlebt den Deep Sleep zwischen zwei Alarmrahmen, aber
keinen Stromausfall und keinen Reset. Dann faengt die Zaehlung von vorn an;
der Alarm laeuft entsprechend laenger, geht aber nicht verloren.

**Ein Schreibzugriff bleibt, und der ist unvermeidbar:** `sys.alarm` selbst
liegt im EEPROM (`common.cpp` 505 schreibt, 765 liest) und wird beim Booten
zurueckgelesen. Ohne `config_Write()` am Ende stuende der Alarm nach dem
naechsten Aufwachen wieder auf 1. Geschrieben wird also der *Alarmzustand*,
nicht der Zaehler -- genau einmal, beim Beenden.

Gezaehlt werden die beiden Wege, auf denen waehrend eines Alarms Uplinks
hinausgehen: `do_send()` (Position, fPort 2/3) und `Alarm_send()` (fPort 7).
Der Statusrahmen aus `device_send()` (fPort 5) zaehlt nicht mit -- er gehoert
zum Join und nicht zum Alarm.

Der ausloesende Rahmen geht noch mit gesetztem Alarmbit hinaus: der Zaehler
wird gerufen, nachdem die Nutzlast steht, aber vor `LMIC_setTxData2()`.
Beendet wird mit genau denselben Zuweisungen wie der Zehnfach-Klick in
`attachMultiClick()`, damit es nur einen Ausstiegsweg im Verhalten gibt.
"""
import os
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

if "alarm_uplink_zaehlen" in s:
    sys.exit("schon gepatcht")

# --- 1. Zaehler und Ausstieg, direkt vor do_send() --------------------------
anker = "void do_send(osjob_t* j)"
if s.count(anker) != 1:
    sys.exit("do_send nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, """/* --- Alarm-Selbstende nach 99 Uplinks ------------------------------------ */
#define ALARM_MAX_UPLINKS 99

/* Nur im Speicher: RTC_DATA_ATTR ueberlebt den Deep Sleep zwischen zwei
   Alarmrahmen -- jeder Alarmzyklus ist ein eigener Boot --, wird aber nie ins
   EEPROM geschrieben. sys.alarm_count bleibt deshalb unbenutzt: der ginge bei
   jedem config_Write() in den Flash. */
RTC_DATA_ATTR uint16_t alarm_uplinks = 0;

static void alarm_uplink_zaehlen(void)
{
  if(sys.alarm != 1)
  {
    alarm_uplinks = 0;
    return;
  }
  if(++alarm_uplinks < ALARM_MAX_UPLINKS)
    return;

  Serial.printf("Alarm beendet: %u Uplinks\\r\\n", alarm_uplinks);
  /* Derselbe Ausstieg wie der Zehnfach-Klick in attachMultiClick(). Das
     config_Write() gilt dem Alarmzustand, nicht dem Zaehler: sys.alarm liegt
     im EEPROM und wuerde sonst beim naechsten Aufwachen wieder auf 1 stehen. */
  sys.gps_alarm     = 0;
  sys.gps_start     = 2;
  sys.alarm         = 0;
  sys.keep_flag     = 0;
  sys.alarm_count   = 0;
  sys.exti_flag     = 4;
  sys.gps_work_flag = false;
  alarm_uplinks     = 0;
  sys.config_Write();
}

""" + anker)

# --- 2. Positionsrahmen (fPort 2/3), Nutzlast steht bereits -----------------
anker = "      LMIC_setTxData2(sys.port, mydata, i, sys.frame_flag);"
if s.count(anker) != 1:
    sys.exit("Sendeaufruf in do_send nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, "      alarm_uplink_zaehlen();\n" + anker)

# --- 3. Alarmrahmen (fPort 7), ebenfalls nach dem Fuellen -------------------
anker = "    mydata[i++] = ((sys.mod<<6) | (sys.lon<<5) | sys.frame) & 0xFF;   "
if s.count(anker) != 1:
    sys.exit("Nutzlastende in Alarm_send nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, anker + "\n    alarm_uplink_zaehlen();")

open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
print("gepatcht:", p)
