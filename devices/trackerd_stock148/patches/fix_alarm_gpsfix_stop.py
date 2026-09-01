#!/usr/bin/env python3
"""Alarm endet nach 99 gueltigen GPS-Positionen -- gezaehlt nur im Speicher.

Der Werksstand beendet einen Alarm nie von allein: `sys.alarm_count` wird in
`setup()` bei jedem Aufwachen genullt und erreicht die 60 nie, gegen die
geprueft wird. Der einzige Ausstieg sind zehn schnelle Klicks.

Gezaehlt werden hier **nur Rahmen mit echter Position**, nicht Uplinks. Der
Unterschied ist gemessen: am 31.08.2026 gingen 26 Alarmrahmen hintereinander
mit `Latitude=0` hinaus, im Takt von 246 s (ATDC 60 s + FTIME 180 s -- die
Suche lief also jedes Mal in den Zeitablauf). Ein Uplink-Zaehler haette den
Alarm nach 99 solchen Fehlversuchen beendet, ohne dass je eine Position
uebermittelt wurde. Ein Positionszaehler beendet ihn erst, wenn 99 mal
wirklich etwas zu melden war.

**Der Preis, und der ist bewusst:** ohne Empfang endet der Alarm nie von
selbst. Bei schlechter Sicht laeuft er weiter, bis zehn Klicks kommen. Wer
das nicht will, zaehlt Uplinks statt Fixes.

Nicht gezaehlt werden zwei Faelle, die wie eine Position aussehen:

* `latitude == 0 && longitude == 0` -- keine Loesung, der Regelfall bei
  abgelaufener Suchzeit.
* `latitude == 0xFFFFFFFF` -- die Marke, die `setup()` bei Batterie unter
  2800 mV setzt (`TrackerD.ino` 1241/1242). `sensor.latitude` ist `int`,
  verglichen wird deshalb gegen -1.

Gezaehlt wird in `RTC_DATA_ATTR`: der Wert ueberlebt den Deep Sleep zwischen
zwei Alarmrahmen -- jeder Zyklus ist ein eigener Boot --, wird aber nie ins
NVRAM geschrieben. `sys.alarm_count` bleibt unbenutzt, der ginge ueber
`config_Write()` bei jeder Runde in den Flash.

Ein Schreibzugriff bleibt und ist unvermeidbar: `sys.alarm` selbst liegt im
EEPROM (`common.cpp` 505 schreibt, 765 liest) und stuende ohne
`config_Write()` beim naechsten Aufwachen wieder auf 1. Geschrieben wird der
Alarmzustand, genau einmal beim Beenden -- nicht der Zaehler.

Der ausloesende Rahmen geht noch mit gesetztem Alarmbit und mit seiner
Position hinaus: gezaehlt wird, nachdem die Nutzlast steht, aber vor
`LMIC_setTxData2()`. Beendet wird mit denselben Zuweisungen wie der
Zehnfach-Klick in `attachMultiClick()`.
"""
import os
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

if "alarm_fix_zaehlen" in s:
    sys.exit("schon gepatcht")

anker = "void do_send(osjob_t* j)"
if s.count(anker) != 1:
    sys.exit("do_send nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, """/* --- Alarm-Selbstende nach 99 gueltigen Positionen ----------------------- */
#define ALARM_MAX_FIXE 99

/* Nur im Speicher: RTC_DATA_ATTR ueberlebt den Deep Sleep zwischen zwei
   Alarmrahmen, wird aber nie ins EEPROM geschrieben. */
RTC_DATA_ATTR uint16_t alarm_fixe = 0;

static void alarm_fix_zaehlen(void)
{
  if(sys.alarm != 1)
  {
    alarm_fixe = 0;
    return;
  }
  /* Keine Loesung, oder die Unterspannungsmarke aus setup(): nicht zaehlen. */
  if(sensor.latitude == 0 && sensor.longitude == 0)
    return;
  if(sensor.latitude == -1 || sensor.longitude == -1)
    return;

  if(++alarm_fixe < ALARM_MAX_FIXE)
    return;

  Serial.printf("Alarm beendet: %u gueltige Positionen\\r\\n", alarm_fixe);
  /* Derselbe Ausstieg wie der Zehnfach-Klick in attachMultiClick(). Das
     config_Write() gilt dem Alarmzustand, nicht dem Zaehler: sys.alarm liegt
     im EEPROM und stuende sonst beim naechsten Aufwachen wieder auf 1. */
  sys.gps_alarm     = 0;
  sys.gps_start     = 2;
  sys.alarm         = 0;
  sys.keep_flag     = 0;
  sys.alarm_count   = 0;
  sys.exti_flag     = 4;
  sys.gps_work_flag = false;
  alarm_fixe        = 0;
  sys.config_Write();
}

""" + anker)

anker = "      LMIC_setTxData2(sys.port, mydata, i, sys.frame_flag);"
if s.count(anker) != 1:
    sys.exit("Sendeaufruf in do_send nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, "      alarm_fix_zaehlen();\n" + anker)

open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
print("gepatcht:", p)
