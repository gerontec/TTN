#!/usr/bin/env python3
"""Sport-Mode und Datalog ab Werk an.

Draginos Vorgaben sind `Intwk = 0` (Bewegungsmodus aus) und `PNACKmd = 0`
(Datalog aus). Beides gehoert hier eingeschaltet:

* **`AT+INTWK=1`** -- der Beschleunigungssensor weckt das Geraet, danach gilt
  `AT+MTDC` statt `AT+TDC`.
* **`AT+PNACKMD=1`** -- Uplinks gehen bestaetigt hinaus; bleibt das ACK aus,
  legt `EV_TXCOMPLETE` den Fix ueber `gps_data_Weite()` im NVS ab und liefert
  ihn spaeter ueber fPort 4 nach. Ohne das ist die Datalog-Kette tot, und jeder
  ungehoerte Fix ist verloren. `frame_flag` muss mitgesetzt werden, sonst
  bleiben die Uplinks unbestaetigt und die Kette laeuft nie an.

Dazu werden die drei Ringzeiger genullt. Der Grund ist gemessen: am 31.08.2026
spulte das Geraet nach dem Einschalten des Datalogs 22 Rahmen mit Unsinn aus
(Breitengrad -1360, Monat 215, Jahr 55177). Im Ring lagen Reste aus einem
anderen Firmwarestand, und die Zeiger passten nicht dazu. Wer den Datalog ab
Werk einschaltet, faengt mit leerem Ring an -- sonst liefert er beim ersten
Funkloch Zufallszahlen, und zwar bestaetigt, also mit bis zu acht Versuchen je
Rahmen.

Der Block laeuft nur bei `FDR_flag == 0`, also nach einem `DATA_CLEAR`:
Werksreset oder Wechsel des Versionsstrings.
"""
import os
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

alt = "        sys.TF[0] ={0x14};"
if s.count(alt) != 1:
    sys.exit("Vorgabenblock nicht eindeutig (%d)" % s.count(alt))
neu = alt + """
        /* Sport-Mode und Datalog ab Werk an. */
        sys.Intwk      = 1;
        sys.PNACKmd    = 1;
        sys.frame_flag = 1;
        /* Mit leerem Spurpuffer anfangen: Reste eines anderen Standes wuerden
           sonst als Nachlieferung hinausgehen -- bestaetigt und unlesbar. */
        sys.addr_gps_write = 0;
        sys.addr_gps_read  = 0;
        sys.gps_write      = 0;"""
open(p, "w", encoding="utf-8", errors="surrogateescape").write(s.replace(alt, neu))
print("gepatcht:", p)
