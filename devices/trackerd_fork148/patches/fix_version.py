#!/usr/bin/env python3
"""Die Version sagen, auf der der Fork wirklich steht: v1.4.8.

Geklont wird mit `--branch v1.4.8`. Draginos Quelltext meldet sich aber als
`v1.4.6`, und das ist kein Versehen des Fork-Bauers, sondern Draginos eigene
Unordnung: die Tags **v1.4.6, v1.4.7, v1.4.8 und V1.4.9 zeigen auf denselben
Commit** (a66935b), dessen `Pro_version` `v1.4.6` stehen geblieben ist. Wer den
Stand am Geraet ablas, bekam also eine Nummer, die zu keinem Klonbefehl passt.

Neu: `Pro_version "v1.4.8"` -- die Nummer, mit der die Basis geholt wird.

Zwei Folgen, beide gewollt:

* `string_touint()` liest die Ziffern des Strings, `fire_version` wird also 148
  statt 146. Im Statusrahmen (fPort 5) stehen dann `0x01 0x48`, der Decoder
  zeigt `1.4.8`.
* Weil `fire_version` sich vom Wert im EEPROM unterscheidet, laeuft beim ersten
  Start ein `DATA_CLEAR()` (Blau-Rot-Gruen). Die Einstellungen kommen damit auf
  die einkompilierten Vorgaben zurueck -- und genau die sind die gewollten:
  INTWK=1, MTDC 180 s, TDC 20 min, PT 0x0A. Was nicht angetastet wird, sind die
  Schluessel: DevEUI und AppKey liegen in `KEY` (eeprom0).

Wer danach auf app0 zurueckschaltet (dort liegt noch der Stand mit 146), zahlt
den DATA_CLEAR erneut -- in jede Richtung einmal.
"""
import os
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "common.h")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

alt = '#define Pro_version         "v1.4.6"'
neu = ('/* Basis des Forks ist Tag v1.4.8. Draginos Quelltext meldet dort v1.4.6,\n'
       '   weil v1.4.6/v1.4.7/v1.4.8/V1.4.9 auf denselben Commit zeigen und der\n'
       '   String nie nachgezogen wurde. Angezeigt gehoert die geklonte Basis. */\n'
       '#define Pro_version         "v1.4.8"')
if s.count(alt) != 1:
    sys.exit("Pro_version nicht eindeutig (%d)" % s.count(alt))
open(p, "w", encoding="utf-8", errors="surrogateescape").write(s.replace(alt, neu))
print("gepatcht:", p)
