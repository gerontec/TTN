#!/usr/bin/env python3
"""Sport-Mode und Datalog ab Werk an.

Draginos Vorgaben sind `Intwk = 0` (Bewegungsmodus aus) und `PNACKmd = 0`
(Datalog aus). Beides gehoert hier eingeschaltet:

* **`AT+INTWK=1`** -- der Beschleunigungssensor weckt das Geraet, danach gilt
  `AT+MTDC` statt `AT+TDC`.
* **`AT+PNACKMD=1`** -- Uplinks gehen bestaetigt hinaus; bleibt das ACK aus,
  legt `EV_TXCOMPLETE` den Fix ueber `gps_data_Weite()` im NVS ab und liefert
  ihn spaeter ueber fPort 4 nach. Ohne das ist die Datalog-Kette tot, und jeder
  ungehoerte Fix ist verloren.

`frame_flag` wird mitgesetzt. Das ist kein dritter Punkt, sondern der Schalter,
der `PNACKmd` ueberhaupt wirksam macht: ohne ihn bleiben die Uplinks
unbestaetigt, es fehlt das ausbleibende ACK als Ausloeser, und die Kette laeuft
nie an.

Der Block laeuft nur bei `FDR_flag == 0`, also nach einem `DATA_CLEAR`:
Werksreset oder Wechsel des Versionsstrings. Genau dort stehen auch Draginos
eigene Vorgaben, die hier ueberschrieben werden.

**Was dieser Patch bewusst NICHT tut:** die drei Ringzeiger des Spurpuffers
nullen. Gemessen am 31.08.2026: nach dem Einschalten des Datalogs spulte das
Geraet 22 Rahmen mit Unsinn aus -- Breitengrad -1360, Monat 215, Jahr 55177 --,
weil im Ring Reste eines anderen Firmwarestandes lagen und die Zeiger nicht
dazu passten. Dieselben Rahmen stehen in `wagodb.loradevice` vom 31.08.
zwischen 11:56 und 12:03 auf fPort 4 und haben den Tagestrack im GPX-Report
auf eine Ausdehnung von 19.601 km gebracht. Wer den Datalog ab Werk
einschaltet, faengt sinnvollerweise mit leerem Ring an; die drei Zeilen dafuer
waeren

    sys.addr_gps_write = 0;
    sys.addr_gps_read  = 0;
    sys.gps_write      = 0;

Sie sind hier nicht drin, weil nur die zwei Vorgaben bestellt waren.
"""
import os
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

if "Sport-Mode und Datalog ab Werk an" in s:
    sys.exit("schon gepatcht")

alt = "        sys.TF[0] ={0x14};"
if s.count(alt) != 1:
    sys.exit("Vorgabenblock nicht eindeutig (%d)" % s.count(alt))
neu = alt + """
        /* Sport-Mode und Datalog ab Werk an. frame_flag gehoert zu PNACKmd:
           ohne bestaetigte Uplinks gibt es kein ausbleibendes ACK, und der
           Spurpuffer wird nie gefuellt. */
        sys.Intwk      = 1;
        sys.PNACKmd    = 1;
        sys.frame_flag = 1;"""
open(p, "w", encoding="utf-8", errors="surrogateescape").write(s.replace(alt, neu))
print("gepatcht:", p)
