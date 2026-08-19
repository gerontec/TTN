#!/usr/bin/env python3
"""Downlink-Test mit dem LA66-USB als Empfaenger.

Reiht N LoRaWAN-Downlinks bei ChirpStack ein und zaehlt mit, wie viele der
LA66 tatsaechlich ausgibt -- samt Empfangspegel. Das ist die Gegenprobe zu den
Rohkanal-Messungen: dieselbe Sendekette des Gateways, aber LoRaWAN statt
Ebyte-Profil, also BW125 statt BW500 und ohne den Syncword-Shim, dessen Gate
nur bei 868.125 MHz greift.

    ./la66_rx_test.py                  # 6 Downlinks im 7-s-Takt
    ./la66_rx_test.py -n 12 -i 5       # laenger und dichter
    ./la66_rx_test.py --port /dev/ttyUSB1

Das Geraet muss im LoRaWAN-Modus und gejoint sein (`AT+NJS=?` -> 1). Steht es
auf Class C (`AT+CLASS=?` -> C), geht jeder Downlink sofort raus; unter Class A
erst nach dem naechsten Uplink, dann ist --uplink noetig.

Gemessen am 18.08.2026: 6 von 6, RSSI -59 bis -65 dBm. Zum Vergleich am selben
Gateway auf dem Rohkanal: 1 von 8, Pegel zwischen -32 und -79 dBm. Die
Sendekette ist also gesund, der Fehler steckt im Rohkanal-Pfad.
"""
import argparse
import base64
import json
import re
import threading
import time

import paho.mqtt.client as mqtt
import serial

BROKER = "192.168.5.23"          # mosquitto neben ChirpStack auf dem dell
APP = "f6414e05-2ecc-4809-b966-d63a6728eee0"
EUI = "a8404117f18962e0"
RSSI = re.compile(rb"Rssi=\s*(-?\d+)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-n", "--anzahl", type=int, default=6)
    p.add_argument("-i", "--intervall", type=float, default=7.0)
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--broker", default=BROKER)
    p.add_argument("--app", default=APP)
    p.add_argument("--eui", default=EUI)
    p.add_argument("--fport", type=int, default=2)
    p.add_argument("--uplink", action="store_true",
                   help="vor jedem Downlink einen Uplink senden (Class A: "
                        "nur dann oeffnen sich RX1/RX2)")
    args = p.parse_args()

    thema = "application/%s/device/%s/command/down" % (args.app, args.eui)
    # paho 1.x und 2.x unterscheiden sich in der Konstruktorsignatur; auf dem
    # Notebook liegt 1.x, auf dem dell 2.x.
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        c = mqtt.Client()
    c.connect(args.broker, 1883, 30)
    c.loop_start()

    ser = serial.Serial(args.port, args.baud, timeout=0.5)
    gehoert, lauf = [], True

    def lauschen():
        # Der LA66 meldet einen Downlink als "rxDone ... Rssi= -64". Die
        # Nutzlast selbst holt man mit AT+RECVB=?; fuer die Zaehlung genuegt
        # die Meldung, und sie kommt ohne Nachfrage.
        while lauf:
            try:
                d = ser.read(256)
            except Exception:
                return
            if b"rxDone" in d:
                m = RSSI.search(d)
                gehoert.append(int(m.group(1)) if m else None)

    threading.Thread(target=lauschen, daemon=True).start()
    time.sleep(1)

    for i in range(1, args.anzahl + 1):
        if args.uplink:
            ser.write(b"AT+SENDB=00,02,02,00%02X\r\n" % i)
            ser.flush()
            time.sleep(2)
        nutz = base64.b64encode(bytes([0xD0, i])).decode()
        c.publish(thema, json.dumps({"devEui": args.eui, "confirmed": False,
                                     "fPort": args.fport, "data": nutz}))
        print("Downlink %d/%d eingereiht" % (i, args.anzahl), flush=True)
        time.sleep(args.intervall)

    lauf = False
    time.sleep(2)
    ser.close()
    c.loop_stop()

    pegel = [r for r in gehoert if r is not None]
    print("\n%d von %d angekommen" % (len(gehoert), args.anzahl))
    if pegel:
        print("RSSI %s dBm   (Mittel %.1f, Spanne %d)"
              % (", ".join(str(r) for r in pegel),
                 sum(pegel) / len(pegel), max(pegel) - min(pegel)))
    return 0 if len(gehoert) == args.anzahl else 1


if __name__ == "__main__":
    raise SystemExit(main())
