#!/usr/bin/env python3
"""Traegt die Geraete des lokalen ChirpStack als OTAA bei TTN ein.

Warum OTAA und nicht ABP: **TTN verarbeitet nur DevAddr aus `260B0000/16`**
(`GET /api/v3/ns/dev_addr_prefixes`). Die Adressen, die der lokale ChirpStack
vergibt, liegen ausserhalb — ein ABP-Spiegel mit lokaler Adresse wird vom
Netzwerkserver verworfen, egal wie genau die Schluessel stimmen. Nachgemessen
am 24.08.2026: Schluessel auf beiden Seiten identisch, Rahmen kam an,
`session.last_f_cnt_up` bei TTS nie gesetzt.

Der einzige Weg zu einer gueltigen Adresse fuehrt also ueber einen Join bei
TTN. Der AppKey dafuer liegt bereits im ChirpStack und wird hier im Prozess
weitergereicht, nie ausgegeben.

Danach ist die Reihenfolge wichtig:

  1. dieses Skript          Geraet bei TTN anlegen (OTAA, gleicher AppKey)
  2. cs_keys_off.py         Schluessel im ChirpStack entfernen, damit er den
                            JoinRequest nicht mehr beantwortet
  3. Geraet neu joinen      TTN antwortet, DevAddr kommt aus 260B…
  4. cs_abp_from_ttn.py     die TTN-Sitzung als ABP in den ChirpStack zurueck,
                            damit auch lokal weiter entschluesselt wird

    /home/gh/.venv-chirpstack/bin/python ttn_otaa.py [dev_eui ...]
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

import grpc
from chirpstack_api import api

HOST = "https://eu1.cloud.thethings.network"
FREQ_PLAN = "EU_863_870_TTN"
TENANT = "d2d00763-756f-4da6-91d4-57204a065051"
NUR = {a.lower() for a in sys.argv[1:]}


def ttn_key():
    with open(os.path.expanduser("~/.config/ttn/lenggries.key")) as f:
        m = re.search(r"NNSXS\.[A-Z0-9]+\.[A-Z0-9]+", f.read())
    if not m:
        sys.exit("kein TTN-Anwendungsschluessel gefunden")
    return m.group(0)


KEY = ttn_key()


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(HOST + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + KEY,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


st, info = call("GET", "/api/v3/auth_info")
APP = (((info.get("api_key") or {}).get("entity_ids") or {})
       .get("application_ids") or {}).get("application_id")
if not APP:
    sys.exit(f"Anwendung nicht aus dem Schluessel ableitbar (HTTP {st})")
print(f"TTN-Anwendung: {APP}")

cfg = {}
with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            cfg[k] = v
chan = grpc.insecure_channel("127.0.0.1:8090")
auth = [("authorization", "Bearer " + cfg["CHIRPSTACK_TOKEN"])]
devsvc = api.DeviceServiceStub(chan)


def step(label, method, path, payload):
    st, bd = call(method, path, payload)
    if st < 300:
        print(f"[ok]     {label}")
        return True
    msg = bd.get("message", bd)
    if st == 409 or "already exists" in str(msg):
        print(f"[da]     {label}: existiert bereits")
        return True
    print(f"[FEHLER] {label}: HTTP {st} — {msg}")
    return False


gesamt = 0
for a in api.ApplicationServiceStub(chan).List(
        api.ListApplicationsRequest(limit=100, tenant_id=TENANT),
        metadata=auth).result:
    for d in devsvc.List(api.ListDevicesRequest(limit=100, application_id=a.id),
                         metadata=auth).result:
        if NUR and d.dev_eui.lower() not in NUR:
            continue
        try:
            keys = devsvc.GetKeys(api.GetDeviceKeysRequest(dev_eui=d.dev_eui),
                                  metadata=auth).device_keys
        except grpc.RpcError:
            print(f"-- {d.name}: kein AppKey im ChirpStack, uebersprungen")
            continue
        # LoRaWAN 1.0.x: der Schluessel vom Aufkleber liegt in nwk_key.
        app_key = (keys.nwk_key or keys.app_key or "").upper()
        if len(app_key) != 32:
            print(f"-- {d.name}: AppKey unbrauchbar, uebersprungen")
            continue

        voll = devsvc.Get(api.GetDeviceRequest(dev_eui=d.dev_eui),
                          metadata=auth).device
        dev_id = d.name.lower().replace("_", "-")
        dev_eui = d.dev_eui.upper()
        join_eui = (voll.join_eui or "0000000000000000").upper()
        print(f"\n== {dev_id}  DevEUI {dev_eui}  JoinEUI {join_eui}")

        ids = {"device_id": dev_id, "dev_eui": dev_eui, "join_eui": join_eui,
               "application_ids": {"application_id": APP}}

        ok = step("Identity Server", "POST",
                  f"/api/v3/applications/{APP}/devices", {
            "end_device": {
                "ids": ids,
                "name": dev_id,
                "description": "OTAA bei TTN, Sitzung wird lokal gespiegelt",
                "join_server_address": "eu1.cloud.thethings.network",
                "network_server_address": "eu1.cloud.thethings.network",
                "application_server_address": "eu1.cloud.thethings.network",
            },
            "field_mask": {"paths": [
                "ids.dev_eui", "ids.join_eui", "name", "description",
                "join_server_address", "network_server_address",
                "application_server_address"]},
        })

        ok = step("Join Server", "PUT",
                  f"/api/v3/js/applications/{APP}/devices/{dev_id}", {
            "end_device": {
                "ids": ids,
                "network_server_address": "eu1.cloud.thethings.network",
                "application_server_address": "eu1.cloud.thethings.network",
                "root_keys": {"nwk_key": {"key": app_key},
                              "app_key": {"key": app_key}},
            },
            "field_mask": {"paths": [
                "ids.dev_eui", "ids.join_eui", "network_server_address",
                "application_server_address",
                "root_keys.nwk_key.key", "root_keys.app_key.key"]},
        }) and ok

        ok = step("Network Server", "PUT",
                  f"/api/v3/ns/applications/{APP}/devices/{dev_id}", {
            "end_device": {
                "ids": ids,
                "frequency_plan_id": FREQ_PLAN,
                "lorawan_version": "MAC_V1_0_3",
                "lorawan_phy_version": "PHY_V1_0_3_REV_A",
                "supports_join": True,
                "supports_class_b": False,
                "supports_class_c": False,
                "multicast": False,
            },
            "field_mask": {"paths": [
                "ids.dev_eui", "ids.join_eui", "frequency_plan_id",
                "lorawan_version", "lorawan_phy_version", "supports_join",
                "supports_class_b", "supports_class_c", "multicast"]},
        }) and ok

        ok = step("Application Server", "PUT",
                  f"/api/v3/as/applications/{APP}/devices/{dev_id}", {
            "end_device": {"ids": ids},
            "field_mask": {"paths": ["ids.dev_eui", "ids.join_eui"]},
        }) and ok
        gesamt += 1 if ok else 0

print(f"\n{gesamt} Geraet(e) bei TTN als OTAA eingetragen.")
