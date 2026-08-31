#!/usr/bin/env python3
"""Alarm endet von selbst, wenn er nichts Neues mehr zu melden hat.

Der Werksstand beendet einen Alarm **nie** von allein: `sys.alarm_count` wird
in `setup()` bei jedem Aufwachen genullt, erreicht also nie die 60, gegen die
`sys_sleep()` prueft. Der einzige Ausstieg sind zehn schnelle Klicks in
`attachMultiClick()`. Gemessen am 31.08.2026: ein versehentlich ausgeloester
Alarm lief ueber eine Stunde und erzeugte im ATDC-Takt 338 Uplinks.

Zwei Abbruchgruende, beide heissen "es gibt nichts Neues":

* **Mehr als drei Rahmen hintereinander ohne Fix.** Ohne Position ist ein
  Alarmrahmen im Minutentakt nur Sendezeit.
* **Dreimal hintereinander dieselbe Position.** Das Geraet steht; wo es steht,
  ist bereits uebermittelt. "Dieselbe" heisst **weniger als 40 m Abstand zum
  vorigen Fix**, nicht bitgleich: ein ruhig liegendes Geraet wandert zwischen
  zwei Fixes um mehrere Meter. Gemessen an den Alarmrahmen vom 31.08.2026, das
  Geraet lag dabei still: 200 Einheiten Streuung in der Breite (~22 m), 606 in
  der Laenge (~45 m). Auf Gleichheit zu pruefen hiesse, nie abzubrechen.

  Verglichen wird gegen den **letzten** Fix, nicht gegen den ersten -- so
  zaehlt langsames Driften nicht als Stillstand mit.

Ein Fix, der sich unterscheidet, setzt beide Zaehler zurueck -- die Bedingung
verlangt also ununterbrochene Folgen, nicht Summen.

Gezaehlt wird in `RTC_DATA_ATTR`, weil jeder Alarmzyklus ein eigener Boot ist:
zwischen zwei Rahmen liegt ein Deep Sleep, gewoehnliche Globale waeren jedes
Mal wieder null.

Beendet wird mit genau denselben Zuweisungen wie beim Zehnfach-Klick, damit es
nur einen Ausstiegsweg im Verhalten gibt. Der ausloesende Rahmen geht noch mit
gesetztem Alarmbit hinaus -- die Nutzlast steht zum Zeitpunkt des Aufrufs
bereits im Puffer -, erst danach faellt der Zustand.
"""
import os
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

if "alarm_selbstende" in s:
    sys.exit("schon gepatcht")

anker = "RTC_DATA_ATTR int bg_mode = 1;"
if s.count(anker) != 1:
    sys.exit("RTC-Block nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, anker + """

/* --- Alarm-Selbstende ---------------------------------------------------- */
#define ALARM_MAX_NULL     3   /* mehr als drei Rahmen ohne Fix  -> Schluss */
#define ALARM_MAX_GLEICH   3   /* dreimal derselbe Ort           -> Schluss */
#define ALARM_GLEICH_METER 40  /* naeher als das gilt als unveraendert */

RTC_DATA_ATTR int alarm_null_zahl   = 0;
RTC_DATA_ATTR int alarm_gleich_zahl = 0;
RTC_DATA_ATTR int alarm_letzte_lat  = 0;
RTC_DATA_ATTR int alarm_letzte_lon  = 0;""")

anker = "void do_send(osjob_t* j)"
if s.count(anker) != 1:
    sys.exit("do_send nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, """/* Aufgerufen, wenn ein Positionsrahmen waehrend eines Alarms hinausgeht. */
/* Abstand zweier Fixes in Metern. Aequirektangulaere Naeherung: auf wenigen
   hundert Metern genauer als noetig und ohne Haversine. Ein Einheitsschritt
   sind 1e-6 Grad = 0,11132 m in der Breite; in der Laenge kommt cos(Breite)
   dazu, weshalb hier gerechnet und nicht mit festen Gradschwellen gearbeitet
   wird -- die waeren nur fuer einen Breitengrad richtig. */
static uint32_t alarm_abstand_m(int lat1, int lon1, int lat2, int lon2)
{
  float dlat = (float)(lat1 - lat2) * 0.11132f;
  float dlon = (float)(lon1 - lon2) * 0.11132f
               * cosf((float)lat1 * 1e-6f * 0.01745329f);
  return (uint32_t)sqrtf(dlat * dlat + dlon * dlon);
}

static void alarm_selbstende(void)
{
  if(sys.alarm != 1)
  {
    alarm_null_zahl   = 0;
    alarm_gleich_zahl = 0;
    return;
  }
  if(sensor.latitude == 0 && sensor.longitude == 0)
  {
    alarm_null_zahl++;
    alarm_gleich_zahl = 0;
  }
  else
  {
    alarm_null_zahl = 0;
    if(alarm_gleich_zahl > 0 &&
       alarm_abstand_m(sensor.latitude, sensor.longitude,
                       alarm_letzte_lat, alarm_letzte_lon) < ALARM_GLEICH_METER)
      alarm_gleich_zahl++;
    else
      alarm_gleich_zahl = 1;
    alarm_letzte_lat = sensor.latitude;
    alarm_letzte_lon = sensor.longitude;
  }
  if(alarm_null_zahl <= ALARM_MAX_NULL && alarm_gleich_zahl < ALARM_MAX_GLEICH)
    return;

  Serial.printf("Alarm beendet: %d ohne Fix, %d am selben Ort\\r\\n",
                alarm_null_zahl, alarm_gleich_zahl);
  /* Derselbe Ausstieg wie der Zehnfach-Klick in attachMultiClick(). */
  sys.gps_alarm     = 0;
  sys.gps_start     = 2;
  sys.alarm         = 0;
  sys.keep_flag     = 0;
  sys.alarm_count   = 0;
  sys.exti_flag     = 4;
  sys.gps_work_flag = false;
  alarm_null_zahl   = 0;
  alarm_gleich_zahl = 0;
  sys.config_Write();
}

""" + anker)

anker = "      LMIC_setTxData2(sys.port, mydata, i, sys.frame_flag);"
if s.count(anker) != 1:
    sys.exit("Sendeaufruf in do_send nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, """      /* Nutzlast steht, Alarmbit ist gesetzt: jetzt pruefen, ob dies der
         letzte Alarmrahmen war. */
      if(sys.port == 2 || sys.port == 3)
        alarm_selbstende();
""" + anker)

open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
print("gepatcht:", p)
