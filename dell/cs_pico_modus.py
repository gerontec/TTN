#!/usr/bin/env python3
"""Schaltet den Pico-Knoten per LoRaWAN-Downlink um (FPort 10).

Der Rueckweg zum rohen Kanal: in LoRaWAN hoert der Knoten nur in den beiden
Empfangsfenstern nach einem eigenen Uplink (Class A), der Befehl wartet also in
der Warteschlange des ChirpStack, bis der naechste Uplink kommt.

    ./cs_pico_modus.py lora [minuten]   zurueck auf den rohen Kanal; mit
                                        Minuten kommt der Knoten von selbst
                                        wieder ins LoRaWAN (Rueckfahrkarte)
    ./cs_pico_modus.py lorawan          bleibt im LoRaWAN, loescht eine
                                        vorgemerkte Rueckkehr
    ./cs_pico_modus.py relais on|off    Relais des rohen Kanals schalten

Gegenrichtung (roher Kanal -> LoRaWAN) geht nicht hierueber, sondern per
Funkbefehl: ./lora_cmd.py MODUS LORAWAN [minuten]
"""
import os
import sys

import grpc
from chirpstack_api import api

DEV_EUI = "5049434f00000e22"
FPORT = 10


def token():
    with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
        for line in f:
            if line.startswith("CHIRPSTACK_TOKEN="):
                return line.strip().split("=", 1)[1]
    sys.exit("kein ChirpStack-Token gefunden")


def nutzlast(argv):
    was = (argv[0] if argv else "").lower()
    if was == "lora":
        minuten = int(argv[1]) if len(argv) > 1 else 0
        return bytes([0x00, (minuten >> 8) & 0xFF, minuten & 0xFF])
    if was == "lorawan":
        return bytes([0x01])
    if was == "relais" and len(argv) > 1:
        return bytes([0x02, 1 if argv[1].lower() in ("on", "an", "1") else 0])
    sys.exit(__doc__)


def main():
    daten = nutzlast(sys.argv[1:])
    chan = grpc.insecure_channel("127.0.0.1:8090")
    auth = [("authorization", "Bearer " + token())]
    req = api.EnqueueDeviceQueueItemRequest()
    req.queue_item.dev_eui = DEV_EUI
    req.queue_item.f_port = FPORT
    req.queue_item.data = daten
    req.queue_item.confirmed = False
    kennung = api.DeviceServiceStub(chan).Enqueue(req, metadata=auth).id
    print("eingereiht:", daten.hex(), "FPort", FPORT, "id", kennung)
    print("wird beim naechsten Uplink des Knotens zugestellt")


if __name__ == "__main__":
    main()
