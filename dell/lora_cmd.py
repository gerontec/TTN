#!/usr/bin/env python3
"""Fernwirkbefehl an die Relaisstelle Brauneck, von 192.168.5.23 aus.

Der Pico auf dem Berg hat kein WLAN -- der einzige Weg dorthin ist der Funk.
Dieses Werkzeug reicht den Befehl an den laufenden `lora-raw.service` weiter
(der haelt UDP 1702 und kann als einziger senden), das Gateway funkt ihn auf
868.125 SF7 hinaus, und die Antwort des Relais kommt denselben Weg zurueck.

  ./lora_cmd.py POWER 20        # Sendeleistung talwaerts -- der Kernbefehl
  ./lora_cmd.py STATUS
  ./lora_cmd.py SAVE            # damit es den Stromausfall ueberlebt
  ./lora_cmd.py SF 9
  ./lora_cmd.py REBOOT
"""
import json
import socket
import sys
import time

CTRL = ("127.0.0.1", 1703)
WARTEN_S = 25


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    befehl = " ".join(sys.argv[1:])
    rahmen = ("C>" + befehl).encode()

    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        mqtt = None

    antworten = []
    c = None
    if mqtt is not None:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="lora-cmd")
        c.on_message = lambda cl, u, m: antworten.append(json.loads(m.payload))
        c.connect("127.0.0.1", 1883, keepalive=30)
        c.subscribe("lora/raw", qos=0)
        c.loop_start()
        time.sleep(0.5)

    socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(rahmen, CTRL)
    print("gesendet: %s" % rahmen.decode())

    if c is None:
        print("(kein paho -- Antwort mit 'journalctl -u lora-raw -f' ansehen)")
        return 0

    ende = time.time() + WARTEN_S
    while time.time() < ende:
        for a in antworten:
            t = a.get("text") or ""
            if t.startswith("A>"):
                print("Antwort: %s   (RSSI %s, SNR %s)"
                      % (t[2:], a.get("rssi"), a.get("snr")))
                c.loop_stop()
                return 0
        antworten.clear()
        time.sleep(0.4)

    print("keine Antwort in %d s -- Relais aus? Sendezeitbudget gesperrt?"
          % WARTEN_S)
    c.loop_stop()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
