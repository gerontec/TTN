#!/usr/bin/env python3
"""Datalog ab Werk an; Sport-Mode ueber eine Zeile umstellbar.

Draginos Vorgaben sind `Intwk = 0` (Bewegungsmodus aus) und `PNACKmd = 0`
(Datalog aus). Beides wird hier eingeschaltet:

* **`AT+INTWK`** -- der Beschleunigungssensor weckt das Geraet, danach gilt
  `AT+MTDC` statt `AT+TDC`. Der Wert steht als eine Zeile im eingefuegten
  Block und wird zum Vergleichen umgestellt; **derzeit 0 (aus)**.

  Zur Vorgeschichte: die Kombination stand im Verdacht, die GPS-Suche zu
  blockieren -- Sport allein lieferte 340 Rahmen mit 100 % Fixquote, Datalog
  allein 96 %, beides zusammen 2 %. In der Nacht auf den 01.09.2026 wurde der
  Verdacht **widerlegt**: mit `Intwk=0` und `PNACKmd=1` trat dasselbe Muster
  auf (Fix nur im zweiten Rahmen nach dem Neustart, danach keiner mehr).
  Ebenso ausgeschlossen: die Alarmzaehler, der Spurpuffer, GPIO 12 und die
  `LMIC.seqnoUp`-Blocke. Ungeklaert bleibt, warum Draginos Binary Fixes
  liefert und jeder Eigenbau nicht.
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

Die Ringzeiger des Spurpuffers werden hier **nicht** angefasst. Sie liegen im
DATA-Bereich (`common.cpp` 536/539/580), und `DATA_CLEAR()` schreibt 0 ueber
alle 256 Byte davon. Da dieser Block ausschliesslich im `FDR_flag == 0`-Zweig
laeuft, also nur nach einem `DATA_CLEAR`, stehen sie zu diesem Zeitpunkt schon
auf 0 -- sie hier nochmal zu setzen waere Zierde, kein Schutz.

Wichtig ist der Fall, in dem `DATA_CLEAR()` **nicht** laeuft: beim erneuten
Flashen desselben Versionsstrings erkennt die Firmware keinen Wechsel, und die
alten Zeiger bleiben stehen. Stammen sie aus einem Bau mit anderer Feldreihen-
folge, zeigen sie ins Leere. Am 31.08.2026 gingen daraufhin 22 Rahmen mit
Unsinn hinaus -- Breitengrad -1360, Monat 215, Jahr 55177 --, nachzulesen in
`wagodb.loradevice` zwischen 11:56 und 12:03 auf fPort 4; im GPX-Report ergab
der Tagestrack daraus eine Ausdehnung von 19.601 km.

Schlimmer als die unlesbaren Rahmen ist die Nebenwirkung: `loggpsdata_send`
wird auf 1 gesetzt, sobald der Ring 14 Eintraege traegt (`TrackerD.ino:288`),
und dieses Flag steht als Bedingung in der GPS-Suche (`TrackerD.ino:1286`).
Zurueck auf 0 geht es erst, wenn der Ring leergespult ist
(`gps_write == addr_gps_read`). Passen Zeiger und Inhalt nicht zusammen, wird
das nie wahr: das Geraet sucht dann **gar kein GPS mehr**, sondern liefert nur
noch Muell nach. Gemessen: 80 Rahmen mit `Latitude=0` in Folge, Fixquote 2 %,
waehrend derselbe Stand mit leerem Ring 340 Rahmen mit 100 % lieferte.

Der Schutz dagegen steht nicht hier, sondern im Flashweg: `flash_trackerD.py`
schickt nach jedem Flash ein `AT+FDR` und erzwingt damit das `DATA_CLEAR`,
unabhaengig vom Versionsstring.
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
        sys.Intwk      = 0;   /* Sport: 1 = an, 0 = aus */
        sys.PNACKmd    = 1;
        sys.frame_flag = 1;"""
open(p, "w", encoding="utf-8", errors="surrogateescape").write(s.replace(alt, neu))
print("gepatcht:", p)
