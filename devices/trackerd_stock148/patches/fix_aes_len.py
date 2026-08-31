#!/usr/bin/env python3
"""LMIC-AES: Laengenzaehler in 16 Bit pruefen, nicht in 8.

`os_aes()` in `src/aes/lmic.c` (der Zweig `USE_ORIGINAL_AES`, den Draginos
Bauwerk einschaltet) laeuft ueber die Bloecke so:

    while( (signed char)len > 0 ) {   <-- len ist u2_t, der Cast ist 8 Bit
        ...
        buf += 16;
        len -= 16;                    <-- laeuft unter 0 unter und wird riesig
    }

Der Unterlauf ist Absicht: `len -= 16` auf einem vorzeichenlosen Wert wird bei
len < 16 sehr gross, und die Schleife erkennt das am Vorzeichen. Nur wird das
Vorzeichen in **acht** Bit gelesen. Damit gilt die Abbruchbedingung nicht fuer
die Restlaenge, sondern fuer deren niederwertiges Byte:

* len 1..127    -> laeuft
* len 128..255  -> `(signed char)` ist negativ -> **die Schleife laeuft nie**

Und "laeuft nie" heisst hier nicht "Fehler", sondern: `os_aes` kehrt zurueck,
ohne etwas zu tun. Der Aufrufer merkt nichts.

**Was das im Betrieb bedeutet.** Ein Uplink, dessen Rahmen 128 Byte oder mehr
misst, geht in **Klartext** und **ohne gueltigen MIC** ueber die Luft:

* `aes_cipher()` verschluesselt die Nutzlast nicht -- sie ist mitlesbar.
* `aes_appendMic()` liefert statt der Signatur die ersten vier Bytes des
  unberuehrten B0-Blocks. Der beginnt laut `micB0()` mit 0x49, der MIC lautet
  also immer `49000000`.

Der Netzserver verwirft solche Rahmen wortlos (MIC passt nicht), und weil er
sie keinem Geraet zuordnen kann, taucht dazu nicht einmal ein verworfenes
Ereignis auf. Am Geraet sieht alles richtig aus: `EV_TXSTART`, `TXMODE`,
beide Empfangsfenster, `EV_TXCOMPLETE`.

Gemessen am TrackerD in Lenggries, 31.08.2026: Statusrahmen (22 Byte) kommt an,
Konfigrahmen (164 Byte) verschwindet. Der Roh-Abgriff des Gateways zeigt die
Nutzlast als lesbares JSON und `MIC 49000000`.

**Die Korrektur** ist ein Cast: `(s2_t)` statt `(signed char)`. Der Unterlauf
wird weiter am Vorzeichen erkannt, nur eben ueber alle 16 Bit -- len 65529
(also 9 - 16) ist als s2_t -7 und beendet die Schleife genauso zuverlaessig.
Damit stimmt die Rechnung fuer jede Laenge, die LoRaWAN kennt.

Der Zweig `!USE_ORIGINAL_AES` in `src/aes/other.c` hat den Fehler nicht: dort
sind die Schleifen `while (len > 0)` ueber `u2_t`.
"""
import os
import sys

lib = sys.argv[1] if len(sys.argv) > 1 else "lib/arduino-lmic"
p = os.path.join(lib, "src", "aes", "lmic.c")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

alt = "        while( (signed char)len > 0 ) {"
neu = ("        /* len ist u2_t und laeuft am Ende jeder Runde unter 0; erkannt\n"
       "           wird das am Vorzeichen. Der Cast muss deshalb so breit sein\n"
       "           wie len -- mit (signed char) galt die Bedingung nur fuer das\n"
       "           niederwertige Byte, und ein Rahmen ab 128 Byte lief ohne eine\n"
       "           einzige Runde durch: Klartext auf der Luft, MIC 49000000. */\n"
       "        while( (s2_t)len > 0 ) {")
if s.count(alt) != 1:
    sys.exit("Schleifenkopf nicht eindeutig (%d)" % s.count(alt))
open(p, "w", encoding="utf-8", errors="surrogateescape").write(s.replace(alt, neu))
print("gepatcht:", p)
