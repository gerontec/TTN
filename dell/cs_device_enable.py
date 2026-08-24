#!/usr/bin/env python3
"""Schaltet ein Geraet im lokalen ChirpStack stumm oder wieder scharf.

Gebraucht wird das beim Umzug eines Geraets nach TTN: solange der lokale
ChirpStack die Schluessel hat, beantwortet er jeden JoinRequest — und er
gewinnt das Rennen immer (1,2 ms ueber LAN gegen rund 40 ms zu eu1). Damit
TTN antworten kann, muss der lokale Server fuer die Dauer des Joins schweigen.

`is_disabled` ist dafuer das richtige Mittel: die Schluessel bleiben liegen,
ein Aufruf macht es rueckgaengig. Die Alternative waere, die Schluessel zu
loeschen — unnoetig destruktiv.

    /home/gh/.venv-chirpstack/bin/python cs_device_enable.py <dev_eui> on|off
"""
import os
import sys

import grpc
from chirpstack_api import api

if len(sys.argv) != 3 or sys.argv[2] not in ("on", "off"):
    sys.exit(__doc__)
DEV_EUI = sys.argv[1].lower()
AUS = sys.argv[2] == "off"

cfg = {}
with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            cfg[k] = v
chan = grpc.insecure_channel("127.0.0.1:8090")
auth = [("authorization", "Bearer " + cfg["CHIRPSTACK_TOKEN"])]
devsvc = api.DeviceServiceStub(chan)

dev = devsvc.Get(api.GetDeviceRequest(dev_eui=DEV_EUI), metadata=auth).device
dev.is_disabled = AUS
devsvc.Update(api.UpdateDeviceRequest(device=dev), metadata=auth)

nach = devsvc.Get(api.GetDeviceRequest(dev_eui=DEV_EUI), metadata=auth).device
print(f"{nach.name} ({DEV_EUI}): is_disabled = {nach.is_disabled}")
