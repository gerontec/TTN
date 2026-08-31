#!/usr/bin/env python3
"""Bewegungstakt ab Werk auf 120 s statt 180 s.

`sys.mtdc` ist der Sendetakt, solange sich das Geraet bewegt (`AT+MTDC`, gilt
nur bei `AT+INTWK=1`). Draginos Vorgabe und unsere bisherige war 180 s.

Zwei Ueberlegungen dahinter:

* **Die Spur wird dichter.** Bei 4 km/h liegen zwischen zwei Rahmen 200 m
  statt 300 m. Zusammen mit `fix_gps_after_motion.py` -- ohne den suchte nur
  jeder zweite Zyklus -- ist das der Unterschied zwischen einer Position alle
  sechs Minuten und einer alle zwei.
* **Die Sendezeit bleibt tragbar.** Ein Positionsrahmen ist bei SF7 rund 60 ms
  in der Luft. 120 s Takt sind 30 Rahmen je Stunde, also 1,8 s -- gegenueber
  1,2 s bei 180 s Takt. TTNs Tagesbudget von 30 s traegt damit gut acht
  Stunden Gehen; bei 60 s Takt waere es nach derselben Zeit aufgebraucht.

Wirksam wird die Vorgabe erst nach einem `DATA_CLEAR` (Werksreset oder Wechsel
des Versionsstrings). Am laufenden Geraet zusaetzlich einmal

    AT+MTDC=120000

setzen, oder ueber Funk mit dem Downlink `03 000078` (der Wert dort zaehlt in
Sekunden, nicht in Millisekunden).
"""
import os
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

alt = "        sys.mtdc = 180000;"
neu = "        sys.mtdc = 120000;"
if s.count(alt) != 1:
    if s.count(neu) == 1:
        sys.exit("schon gepatcht")
    sys.exit("MTDC-Vorgabe nicht eindeutig (%d)" % s.count(alt))
s = s.replace(alt, neu)

# Der Kommentar darueber nennt die alte Zahl -- sonst widerspricht er dem Code.
s = s.replace("Positionstakt in Bewegung 180 s (AT+INTWK=1, AT+MTDC=180000). */",
              "Positionstakt in Bewegung 120 s (AT+INTWK=1, AT+MTDC=120000). */")

open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
print("gepatcht:", p)
