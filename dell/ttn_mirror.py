#!/usr/bin/env python3
"""Spiegelt die Geraete des lokalen ChirpStack als ABP nach TTN.

Warum ABP und nicht OTAA: das Gateway schiebt jeden Uplink an beide
Netzwerkserver. Ein OTAA-Geraet bekaeme auf seinen JoinRequest zwei
JoinAccepts und naehme das zuerst eintreffende — der lokale Krisenserver
koennte das Geraet also jederzeit an TTN verlieren. Ohne Join gibt es nichts
zu kapern: beide Netze hoeren dieselbe Sitzung mit, lokal bleibt massgeblich.

Die Sitzungsschluessel werden im Prozess von ChirpStack nach TTS gereicht und
nie ausgegeben.

    /home/gh/.venv-chirpstack/bin/python ttn_mirror.py [--dry]
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
DRY = "--dry" in sys.argv


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


# Die Anwendung steht im Schluessel selbst — so kann sie nicht danebenliegen.
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
    if DRY:
        print(f"[dry]    {label}")
        return True
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
        try:
            act = devsvc.GetActivation(
                api.GetDeviceActivationRequest(dev_eui=d.dev_eui),
                metadata=auth).device_activation
        except grpc.RpcError:
            print(f"-- {d.name}: keine aktive Sitzung, uebersprungen")
            continue
        if not act.dev_addr:
            print(f"-- {d.name}: keine DevAddr, uebersprungen")
            continue

        dev_id = d.name.lower().replace("_", "-")
        dev_eui = d.dev_eui.upper()
        # Die Listenansicht fuehrt die JoinEUI nicht mit, erst der Einzelabruf.
        # Fuer ABP ist sie bedeutungslos, TTS will das Feld aber gesetzt haben.
        voll = devsvc.Get(api.GetDeviceRequest(dev_eui=d.dev_eui),
                          metadata=auth).device
        join_eui = (voll.join_eui or "0000000000000000").upper()
        dev_addr = act.dev_addr.upper()
        print(f"\n== {dev_id}  DevEUI {dev_eui}  DevAddr {dev_addr}")

        ids = {"device_id": dev_id, "dev_eui": dev_eui, "join_eui": join_eui,
               "dev_addr": dev_addr,
               "application_ids": {"application_id": APP}}

        ok = step("Identity Server", "POST",
                  f"/api/v3/applications/{APP}/devices", {
            "end_device": {
                "ids": ids,
                "name": dev_id,
                "description": "Spiegel des lokalen ChirpStack (ABP)",
                "network_server_address": "eu1.cloud.thethings.network",
                "application_server_address": "eu1.cloud.thethings.network",
            },
            "field_mask": {"paths": [
                "ids.dev_eui", "ids.join_eui", "ids.dev_addr", "name",
                "description", "network_server_address",
                "application_server_address"]},
        })

        ok = step("Network Server", "PUT",
                  f"/api/v3/ns/applications/{APP}/devices/{dev_id}", {
            "end_device": {
                "ids": ids,
                "frequency_plan_id": FREQ_PLAN,
                "lorawan_version": "MAC_V1_0_3",
                "lorawan_phy_version": "PHY_V1_0_3_REV_A",
                "supports_join": False,
                "supports_class_b": False,
                "supports_class_c": False,
                "multicast": False,
                # Der Spiegel hat keine Kontrolle ueber die Zaehler des
                # Geraets: der lokale Server fuehrt die Sitzung, hier wird nur
                # mitgehoert. Ohne diese Duldung verwirft TTS jeden Neustart
                # des Zaehlers als Replay — beim Pico faellt genau das an.
                "mac_settings": {"resets_f_cnt": True},
                "session": {
                    "dev_addr": dev_addr,
                    "keys": {"f_nwk_s_int_key": {"key": act.f_nwk_s_int_key.upper()}},
                },
            },
            "field_mask": {"paths": [
                "ids.dev_eui", "ids.join_eui", "frequency_plan_id",
                "lorawan_version", "lorawan_phy_version", "supports_join",
                "supports_class_b", "supports_class_c", "multicast",
                "mac_settings.resets_f_cnt",
                "session.dev_addr", "session.keys.f_nwk_s_int_key.key"]},
        }) and ok

        ok = step("Application Server", "PUT",
                  f"/api/v3/as/applications/{APP}/devices/{dev_id}", {
            "end_device": {
                "ids": ids,
                "session": {"dev_addr": dev_addr,
                            "keys": {"app_s_key": {"key": act.app_s_key.upper()}}},
            },
            "field_mask": {"paths": [
                "ids.dev_eui", "ids.join_eui",
                "session.dev_addr", "session.keys.app_s_key.key"]},
        }) and ok
        gesamt += 1 if ok else 0

print(f"\n{gesamt} Geraet(e) gespiegelt.")
