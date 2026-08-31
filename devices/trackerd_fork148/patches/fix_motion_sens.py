#!/usr/bin/env python3
"""Beschleunigungssensor empfindlicher: Gehen mit 4 km/h soll aufwecken.

Geaendert wird **nur die Schwelle**, nicht die Achsen.

`LIS3DH_INT1_THS` (`AT+PT`, `sys.TF[0]`) ist die Ansprechschwelle. Bei
Vollausschlag +/-2 g -- `accelRange = 2` -- zaehlt ein LSB 16 mg, Draginos
Vorgabe `0x14` = 20 LSB sind also **320 mg**. Beim Gehen mit 4 km/h liegen die
dynamischen Spitzen je nach Trageort bei etwa 150 bis 400 mg; 320 mg faengt
davon nur die kraeftigsten. Neu `0x0A` = 10 LSB = **160 mg**.

Die Schwelle gilt fuer alle Achsen gleich und haengt nicht davon ab, wie das
Geraet liegt. `INT1_DURATION` bleibt bei 3 Abtastungen, damit ein einzelner
Stoss nicht schon reicht.

## Was hier absichtlich NICHT steht

Ein frueherer Stand setzte zusaetzlich `INT1_CFG` von Draginos `0x0A` (XHIE,
YHIE) auf `0x2A` (ZHIE dazu) -- mit der Ueberlegung, der Takt beim Gehen liege
auf der Hochachse. Das ist **zurueckgenommen**, und zwar aus einem am Geraet
beobachteten Grund: hochkant loeste es sofort aus, flach liegend gar nicht.

Flach liegend traegt Z dauerhaft 1 g. Der Hochpass im Interruptzweig
(`CTRL_REG2 = 0x01`, HP_IA1) soll diesen Gleichanteil entfernen, aber
`LIS3DH_configIntterupts()` stoesst das `REFERENCE`-Register (0x26) nie an, mit
dem der Filter beim Scharfschalten zurueckgesetzt wird. Ohne diesen Anstoss
verhaelt sich der Z-Zweig lageabhaengig -- und Lageabhaengigkeit ist genau das,
was ein Bewegungsmelder nicht haben darf.

Draginos `0x0A` ist an dieser Stelle richtig: X und Y sehen nur dynamische
Beschleunigung, gleich wie das Geraet liegt. Die `0x2A` gehoert in den
Sturzerkennungs-Zweig, wo sie im Original auch steht -- der laeuft nur bei
`AT+FD=1` und ist bei uns aus.

Wirksam wird die neue Schwelle erst nach einem Werksreset -- `sys.TF[0]` steht
im EEPROM und ueberlebt das Flashen. Am laufenden Geraet deshalb einmal

    AT+PT=0A

setzen, oder ueber Funk mit dem Downlink `B4 0A`.
"""
import os
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

alt = "        sys.TF[0] ={0x14};"
neu = ("        /* 0x0A = 10 LSB x 16 mg = 160 mg: Gehen mit 4 km/h weckt,\n"
       "           Draginos 0x14 (320 mg) tat das nur beim Laufen. */\n"
       "        sys.TF[0] ={0x0A};")
if s.count(alt) != 1:
    if "sys.TF[0] ={0x0A};" in s:
        sys.exit("schon gepatcht")
    sys.exit("TF-Vorgabe nicht eindeutig (%d)" % s.count(alt))
open(p, "w", encoding="utf-8", errors="surrogateescape").write(s.replace(alt, neu))
print("gepatcht:", p)
