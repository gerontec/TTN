#!/usr/bin/env python3
"""Beschleunigungssensor empfindlicher: Gehen mit 4 km/h soll aufwecken.

Zwei Groessen entscheiden, ob der LIS3DH den Weckruf ausloest:

* **Die Schwelle** `LIS3DH_INT1_THS` (AT+PT, `sys.TF[0]`). Bei Vollausschlag
  +/-2 g -- `accelRange = 2` -- zaehlt ein LSB 16 mg. Draginos Vorgabe `0x14`
  = 20 LSB sind also **320 mg**. Beim Gehen mit 4 km/h liegen die dynamischen
  Spitzen je nach Trageort bei etwa 150 bis 400 mg; 320 mg faengt davon nur
  die kraeftigsten. Neu `0x0A` = 10 LSB = **160 mg**.
* **Die Achsen** `LIS3DH_INT1_CFG`. Dragino weckt mit `0x0A`, also nur auf
  XHIE und YHIE -- die Hochachse bleibt aussen vor. Genau dort liegt beim
  Gehen aber der Takt: das vertikale Auf und Ab jedes Schritts. Neu `0x2A`,
  ZHIE zusaetzlich; die Verknuepfung bleibt ODER (Bits 7:6 = 00).

Warum das nicht dauernd ausloest: `CTRL_REG2 = 0x01` schaltet den Hochpass in
den Interruptzweig (HP_IA1). Die Erdbeschleunigung ist Gleichanteil und faellt
damit heraus -- sonst wuerde ein flach liegendes Geraet mit aktivem ZHIE
staendig 1000 mg sehen und den Interrupt nie mehr loslassen. `INT1_DURATION`
bleibt bei 3 Abtastungen, damit ein einzelner Stoss nicht schon reicht.

Die Fallerkennung (`fall_detection == 1`) bleibt unberuehrt: sie hat ihren
eigenen Zweig mit eigener Dauer und weckt ohnehin schon auf allen drei Achsen.

Wirksam wird die neue Schwelle erst nach einem Werksreset -- `sys.TF[0]` steht
im EEPROM und ueberlebt das Flashen. Am laufenden Geraet deshalb einmal

    AT+PT=0A

setzen. Die Achsen dagegen stehen im Code und gelten sofort.
"""
import os
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

# --- Vorgabeschwelle beim Werksreset ----------------------------------------
alt = "        sys.TF[0] ={0x14};"
neu = ("        /* 0x0A = 10 LSB x 16 mg = 160 mg: Gehen mit 4 km/h weckt,\n"
       "           Draginos 0x14 (320 mg) tat das nur beim Laufen. */\n"
       "        sys.TF[0] ={0x0A};")
if s.count(alt) != 1:
    sys.exit("TF-Vorgabe nicht eindeutig (%d)" % s.count(alt))
s = s.replace(alt, neu)

# --- Weckachsen im Bewegungszweig -------------------------------------------
alt = "    myIMU.writeRegister(LIS3DH_INT1_CFG, 0x0A);"
neu = ("    /* 0x2A statt 0x0A: ZHIE dazu. Der Takt beim Gehen liegt auf der\n"
       "       Hochachse; die Schwerkraft filtert der Hochpass (CTRL_REG2 bit0)\n"
       "       heraus, sonst haenge der Interrupt bei flach liegendem Geraet. */\n"
       "    myIMU.writeRegister(LIS3DH_INT1_CFG, 0x2A);")
if s.count(alt) != 1:
    sys.exit("INT1_CFG im Bewegungszweig nicht eindeutig (%d)" % s.count(alt))
s = s.replace(alt, neu)

open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
print("gepatcht:", p)
