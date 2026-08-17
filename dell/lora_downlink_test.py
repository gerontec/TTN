#!/usr/bin/env python3
"""Reproduzierbarer Test der Strecke Gateway -> Knoten.

Laeuft auf dell-3660. Reiht N Sendungen mit unterscheidbarer Nutzlast in
lora_raw.py ein, hoert waehrenddessen auf MQTT mit und zaehlt aus, was das
Gateway selbst davon wieder sieht.

Was diese Seite NICHT sehen kann, ist der Empfang an den Knoten -- die haengen
am Notebook. Dafuer gibt das Skript die passenden Gegenbefehle aus; beides
zusammen ergibt die vollstaendige Bilanz.

    python3 lora_downlink_test.py                 # 5 Sendungen
    python3 lora_downlink_test.py -n 10 --pause 6

MESSWERTE VOM 17.08.2026, als Vergleichsmassstab
------------------------------------------------
Rohkanal 868.125 MHz, SF11/BW500, LDRO 1, Syncword 0x55, Broadcast FFFF.
Empfaenger auf demselben Tisch, je 5 Sendungen:

    Sendeleistung   E22            Pico
    14 dBm          0/5            3/5 bei -104..-105 dBm
    27 dBm          2/5 bei -77..-79 dBm   3/5 bei -99..-100 dBm

Zwei Dinge stehen damit fest und sind der eigentliche Wert dieser Datei:

* Die +13 dB auf dem Papier brachten am Empfangsort nur **+5 dB** -- die
  tx_gain_lut des Gateways liefert oben nicht, was sie verspricht. Wer die
  Leistung erhoeht, sollte das nachmessen statt es anzunehmen.
* Dieselbe Aussendung kam beim Pico mit -100 dBm und beim E22 mit -79 dBm an,
  **21 dB Unterschied am selben Tisch**. Das ist Antenne und Aufbau, nicht
  Physik -- und der groessere Hebel als jede Sendeleistung.

Das Gateway hoert seine eigene Aussendung mit rund -16 dBm bei nur -59 Hz
Versatz. Das ist Selbstempfang, keine Weitergabe: eine echte Relaisierung
traegt den Quarzversatz der Gegenstelle, bei einem Ebyte-Modul rund -28 kHz.
"""
import argparse
import json
import socket
import subprocess
import sys
import time

CTRL = ("127.0.0.1", 1703)
BROKER = "localhost"
TOPIC = "lora/raw"


def einreihen(text):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(text.encode(), CTRL)
    s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--anzahl", type=int, default=5)
    ap.add_argument("--pause", type=float, default=8.0,
                    help="Sekunden zwischen den Sendungen; bei SF11/BW500 "
                         "sperrt die 1-%%-Regel rund 14 s je Paket")
    ap.add_argument("--marke", default=None,
                    help="Praefix der Nutzlast, Vorgabe aus der Uhrzeit")
    ap.add_argument("--topic", default=TOPIC)
    args = ap.parse_args()

    marke = args.marke or "T%s" % time.strftime("%H%M%S")
    erwartet = ["%s-%d" % (marke, i) for i in range(1, args.anzahl + 1)]

    sub = subprocess.Popen(
        ["mosquitto_sub", "-h", BROKER, "-t", args.topic],
        stdout=subprocess.PIPE, text=True, bufsize=1)
    time.sleep(1.5)

    print("Marke %s, %d Sendungen im Abstand von %.0f s"
          % (marke, args.anzahl, args.pause))
    print()
    print("Am Notebook parallel mitschneiden:")
    print("  E22 : python3 - <<'X'\n"
          "import serial,time\n"
          "s=serial.Serial('/dev/ttyUSB0',9600,timeout=1)\n"
          "s.dtr=s.rts=False; time.sleep(1); s.reset_input_buffer()\n"
          "t=time.time()\n"
          "while time.time()-t < %d:\n"
          "    d=s.read(64)\n"
          "    if d: print(d)\nX" % (args.anzahl * args.pause + 15))
    print("  Pico: mpremote connect /dev/ttyACM0 exec \"...recv-Schleife...\"")
    print()

    for text in erwartet:
        einreihen(text)
        print("  eingereiht: %s" % text, flush=True)
        time.sleep(args.pause)
    time.sleep(3)

    sub.terminate()
    gesehen = []
    try:
        for zeile in sub.stdout:
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                d = json.loads(zeile)
            except ValueError:
                continue
            if d.get("text") in erwartet:
                gesehen.append(d)
    except ValueError:
        pass

    print()
    print("Am Gateway wieder gesehen (Selbstempfang oder Weitergabe):")
    if not gesehen:
        print("  nichts -- der Selbstfilter greift, das ist der Normalfall")
    for d in gesehen:
        art = "Selbstempfang" if abs(d.get("foff") or 0) < 300 else "WEITERGABE"
        print("  %-12s rssi %-5s foff %-8s %r"
              % (art, d["rssi"], d["foff"], d["text"]))
    print()
    print("Bilanz Gateway: %d von %d" % (len(gesehen), args.anzahl))
    print("Die Empfangsbilanz der Knoten steht im Mitschnitt am Notebook.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
