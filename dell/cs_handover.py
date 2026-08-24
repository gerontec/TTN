#!/usr/bin/env python3
"""Uebergibt ein Geraet per Funk an TTN, ohne es anzufassen.

Das Problem: fuer eine DevAddr aus TTNs Bereich muss das Geraet dort joinen,
und dafuer muss es neu starten. Beim TrackerD geht das ueber Funk — Downlink
`04 FF` ist in der Werksfirmware ATZ und loest `ESP.restart()` aus.

Der Haken ist die Reihenfolge. Der lokale ChirpStack muss den Downlink noch
senden koennen, darf aber den anschliessenden JoinRequest nicht mehr
beantworten — sonst gewinnt er das Rennen (1,2 ms ueber LAN gegen rund 40 ms
nach eu1) und die Adresse faellt wieder aus dem TTN-Bereich. Zwischen
Downlink und Join liegen beim TrackerD rund drei bis fuenf Sekunden; genau in
dieses Fenster gehoert das Stummschalten.

    /home/gh/.venv-chirpstack/bin/python cs_handover.py <dev_eui> [--warte 1500]
"""
import os
import sys
import time

import grpc
from chirpstack_api import api

DEV_EUI = sys.argv[1].lower()
WARTE = int(sys.argv[sys.argv.index("--warte") + 1]) if "--warte" in sys.argv else 1500
ATZ = bytes([0x04, 0xFF])

cfg = {}
with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            cfg[k] = v
chan = grpc.insecure_channel("127.0.0.1:8090")
auth = [("authorization", "Bearer " + cfg["CHIRPSTACK_TOKEN"])]
devsvc = api.DeviceServiceStub(chan)

name = devsvc.Get(api.GetDeviceRequest(dev_eui=DEV_EUI), metadata=auth).device.name
print(f"Geraet: {name} ({DEV_EUI})")

# Die Warteschlange leeren: sonst geht beim naechsten Uplink der Krisenrundruf
# raus und der Neustartbefehl wartet eine Runde laenger.
devsvc.FlushQueue(api.FlushDeviceQueueRequest(dev_eui=DEV_EUI), metadata=auth)
item = api.DeviceQueueItem(dev_eui=DEV_EUI, f_port=1, confirmed=False, data=ATZ)
qid = devsvc.Enqueue(api.EnqueueDeviceQueueItemRequest(queue_item=item),
                     metadata=auth).id
print(f"ATZ eingereiht ({qid[:8]}…), warte auf Zustellung")

t0 = time.time()
zugestellt = False
while time.time() - t0 < WARTE:
    q = devsvc.GetQueue(api.GetDeviceQueueItemsRequest(dev_eui=DEV_EUI),
                        metadata=auth)
    if not any(i.id == qid for i in q.result):
        zugestellt = True
        break
    time.sleep(2)

if not zugestellt:
    print("nicht zugestellt — Geraet bleibt scharf, nichts veraendert")
    sys.exit(1)

# Ab hier zaehlt jede Sekunde: das Geraet startet gerade neu.
dev = devsvc.Get(api.GetDeviceRequest(dev_eui=DEV_EUI), metadata=auth).device
dev.is_disabled = True
devsvc.Update(api.UpdateDeviceRequest(device=dev), metadata=auth)
print(f"zugestellt nach {time.time() - t0:.0f} s — lokal stummgeschaltet, "
      "TTN darf den Join beantworten")
print("weiter mit: cs_abp_from_ttn.py <dev_eui> <ttn_dev_id>")
