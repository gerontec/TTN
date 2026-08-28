#!/usr/bin/env python3
"""Zieht die bei TTN entstandenen Sitzungen in den lokalen ChirpStack nach.

Der lokale Join ist gesperrt: die Geraete joinen bei TTN -- nur DevAddr aus
`260B0000/16` werden dort verarbeitet -- und `cs_abp_from_ttn.py` traegt die
entstandene Sitzung als ABP lokal ein. Solange das von Hand geschieht, faellt
jedes Geraet nach seinem naechsten Join lautlos aus dem lokalen Netz.

Gemessen am 28.08.2026: alle drei Geraete waren heraus, das aelteste seit vier
Tagen. Aufgefallen ist es nur, weil `lora_log.py` seit dem 26.08. keine Zeile
mehr geschrieben hatte -- der lokale ChirpStack sagt zu einem Rahmen, dessen
Sitzung er nicht kennt, nichts weiter als `No device-session exists for
dev_addr`, und ein Uplink, den er nicht aufmacht, erzeugt kein
`application/...`-Ereignis. Der zweite Weg war also weg, ohne dass irgendwo
etwas rot geworden waere. Genau das soll dieses Skript verhindern.

Geschrieben wird **nur, wenn sich die DevAddr geaendert hat**. Das ist keine
Sparsamkeit, sondern noetig: jedes `Activate` setzt die Downlink-Zaehler auf 0
zurueck, und ein Geraet verwirft einen Downlink, dessen FCntDown kleiner ist
als der zuletzt gesehene. Taeglich neu einzutragen, was ohnehin stimmt, wuerde
die Downlink-Strecke unbrauchbar machen, die `cs_pico_mode.py` braucht.

Die Zuordnung TTN-Geraet <-> lokales Geraet laeuft ueber die DevEUI, nicht
ueber den Namen: die Namen duerfen in beiden Netzen verschieden sein, die
DevEUI ist dieselbe Zahl.

    /home/gh/.venv-chirpstack/bin/python cs_abp_sync.py [--trocken]

Taeglich per crontab; die eigentliche Arbeit macht weiterhin
cs_abp_from_ttn.py, das hier nur aufgerufen wird.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime

import grpc
from chirpstack_api import api

HIER = os.path.dirname(os.path.abspath(__file__))
UEBERTRAGER = os.path.join(HIER, "cs_abp_from_ttn.py")
HOST = "https://eu1.cloud.thethings.network"
TROCKEN = "--trocken" in sys.argv


def sag(text):
    print("%s %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text),
          flush=True)


# --- TTN -------------------------------------------------------------------

with open(os.path.expanduser("~/.config/ttn/lenggries.key")) as f:
    TKEY = re.search(r"NNSXS\.[A-Z0-9]+\.[A-Z0-9]+", f.read()).group(0)


def tts(pfad):
    req = urllib.request.Request(HOST + pfad,
                                 headers={"Authorization": "Bearer " + TKEY})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("TTS HTTP %d: %s" % (e.code, e.read().decode()[:200]))


APP = (tts("/api/v3/auth_info")["api_key"]["entity_ids"]
       ["application_ids"]["application_id"])

# DevEUI -> TTN-Geraetekennung. Ohne field_mask liefert TTS nur die ids, und
# mehr wird hier auch nicht gebraucht.
ttn_geraete = {}
for d in tts("/api/v3/applications/%s/devices?field_mask=ids" % APP).get(
        "end_devices", []):
    eui = (d.get("ids") or {}).get("dev_eui")
    if eui:
        ttn_geraete[eui.lower()] = d["ids"]["device_id"]

# --- lokaler ChirpStack ----------------------------------------------------

cfg = {}
with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
    for zeile in f:
        if "=" in zeile and not zeile.startswith("#"):
            k, v = zeile.strip().split("=", 1)
            cfg[k] = v
kanal = grpc.insecure_channel("127.0.0.1:8090")
auth = [("authorization", "Bearer " + cfg["CHIRPSTACK_TOKEN"])]
appsvc = api.ApplicationServiceStub(kanal)
devsvc = api.DeviceServiceStub(kanal)
TENANT = cfg.get("CHIRPSTACK_TENANT", "d2d00763-756f-4da6-91d4-57204a065051")

lokale = []
for anwendung in appsvc.List(api.ListApplicationsRequest(limit=100,
                                                         tenant_id=TENANT),
                             metadata=auth).result:
    for g in devsvc.List(api.ListDevicesRequest(limit=100,
                                                application_id=anwendung.id),
                         metadata=auth).result:
        lokale.append(g.dev_eui.lower())


def lokale_devaddr(eui):
    """Die eingetragene DevAddr, oder None wenn es keine Aktivierung gibt."""
    try:
        a = devsvc.GetActivation(api.GetDeviceActivationRequest(dev_eui=eui),
                                 metadata=auth).device_activation
        return (a.dev_addr or "").lower() or None
    except grpc.RpcError:
        return None


# --- Abgleich --------------------------------------------------------------

geaendert = fehler = 0
for eui in sorted(lokale):
    ttn_id = ttn_geraete.get(eui)
    if not ttn_id:
        sag("%s: bei TTN nicht eingetragen, uebergangen" % eui)
        continue

    ns = tts("/api/v3/ns/applications/%s/devices/%s"
             "?field_mask=session.dev_addr,session.last_f_cnt_up"
             % (APP, ttn_id))
    sitzung = ns.get("session") or {}
    ttn_addr = (sitzung.get("dev_addr") or "").lower()
    if not ttn_addr:
        sag("%s (%s): TTN hat noch keine Sitzung" % (eui, ttn_id))
        continue

    hier = lokale_devaddr(eui)
    if hier == ttn_addr:
        sag("%s (%s): DevAddr %s stimmt ueberein" % (eui, ttn_id, ttn_addr))
        continue

    sag("%s (%s): lokal %s, bei TTN %s -- wird nachgezogen%s"
        % (eui, ttn_id, hier or "keine Sitzung", ttn_addr,
           " (trocken)" if TROCKEN else ""))
    if TROCKEN:
        geaendert += 1
        continue

    lauf = subprocess.run([sys.executable, UEBERTRAGER, eui, ttn_id],
                          capture_output=True, text=True, timeout=120)
    for zeile in (lauf.stdout + lauf.stderr).splitlines():
        if zeile.strip():
            sag("  " + zeile.strip())
    if lauf.returncode == 0:
        geaendert += 1
    else:
        fehler += 1

sag("fertig: %d nachgezogen, %d Fehler, %d Geraete geprueft"
    % (geaendert, fehler, len(lokale)))
sys.exit(1 if fehler else 0)
