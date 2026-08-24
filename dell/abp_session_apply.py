#!/usr/bin/env python3
"""Traegt eine vorgegebene ABP-Sitzung in TTN **und** den lokalen ChirpStack.

Fuer Geraete, die ohnehin ABP fahren (LA66), ist das der geradere Weg als der
Umweg ueber einen Join: die DevAddr wird aus TTNs Praefix `260B0000/16`
gewaehlt — nur solche verarbeitet der Netzwerkserver von TTN —, und dieselbe
Sitzung steht danach im Geraet, bei TTN und im ChirpStack. Kein Join, also
auch kein Rennen zwischen den beiden Servern.

Die Sitzung kommt als JSON-Datei herein und wird nie ausgegeben:

    {"dev_eui": "...", "dev_addr": "260B....",
     "nwk_s_key": "<32 hex>", "app_s_key": "<32 hex>"}

    /home/gh/.venv-chirpstack/bin/python abp_session_apply.py <datei.json>
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

import grpc
from chirpstack_api import api

if len(sys.argv) != 2:
    sys.exit(__doc__)
sess = json.load(open(sys.argv[1]))
DEV_EUI = sess["dev_eui"].lower()
DEV_ADDR = sess["dev_addr"].upper()
NWK = sess["nwk_s_key"].upper()
APPS = sess["app_s_key"].upper()
HOST = "https://eu1.cloud.thethings.network"
FREQ_PLAN = "EU_863_870_TTN"

with open(os.path.expanduser("~/.config/ttn/lenggries.key")) as f:
    TKEY = re.search(r"NNSXS\.[A-Z0-9]+\.[A-Z0-9]+", f.read()).group(0)


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(HOST + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + TKEY,
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

cfg = {}
with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            cfg[k] = v
chan = grpc.insecure_channel("127.0.0.1:8090")
auth = [("authorization", "Bearer " + cfg["CHIRPSTACK_TOKEN"])]
devsvc = api.DeviceServiceStub(chan)

d = devsvc.Get(api.GetDeviceRequest(dev_eui=DEV_EUI), metadata=auth).device
dev_id = d.name.lower().replace("_", "-")
join_eui = (d.join_eui or "0000000000000000").upper()
print(f"{dev_id}  DevEUI {DEV_EUI.upper()}  neue DevAddr {DEV_ADDR}")

# Alten Eintrag raeumen: die DevAddr laesst sich an einem bestehenden Geraet
# nicht ueber alle vier Dienste hinweg sauber umbiegen.
for srv in ("js", "ns", "as"):
    call("DELETE", f"/api/v3/{srv}/applications/{APP}/devices/{dev_id}")
call("DELETE", f"/api/v3/applications/{APP}/devices/{dev_id}")

ids = {"device_id": dev_id, "dev_eui": DEV_EUI.upper(), "join_eui": join_eui,
       "dev_addr": DEV_ADDR, "application_ids": {"application_id": APP}}


def step(label, method, path, payload):
    st, bd = call(method, path, payload)
    if st < 300:
        print(f"[ok]     {label}")
        return True
    print(f"[FEHLER] {label}: HTTP {st} — {bd.get('message', bd)}")
    return False


ok = step("TTN Identity Server", "POST", f"/api/v3/applications/{APP}/devices", {
    "end_device": {
        "ids": ids, "name": dev_id,
        "description": "ABP, Sitzung in TTN und ChirpStack identisch",
        "network_server_address": "eu1.cloud.thethings.network",
        "application_server_address": "eu1.cloud.thethings.network",
    },
    "field_mask": {"paths": [
        "ids.dev_eui", "ids.join_eui", "ids.dev_addr", "name", "description",
        "network_server_address", "application_server_address"]},
})

ok = step("TTN Network Server", "PUT",
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
        # Der lokale Server fuehrt die Sitzung; TTN hoert nur mit und darf an
        # einem Zaehlerruecksprung nach einem Geraeteneustart nicht haengen.
        "mac_settings": {"resets_f_cnt": True},
        "session": {"dev_addr": DEV_ADDR,
                    "keys": {"f_nwk_s_int_key": {"key": NWK}}},
    },
    "field_mask": {"paths": [
        "ids.dev_eui", "ids.join_eui", "frequency_plan_id", "lorawan_version",
        "lorawan_phy_version", "supports_join", "supports_class_b",
        "supports_class_c", "multicast", "mac_settings.resets_f_cnt",
        "session.dev_addr", "session.keys.f_nwk_s_int_key.key"]},
}) and ok

ok = step("TTN Application Server", "PUT",
          f"/api/v3/as/applications/{APP}/devices/{dev_id}", {
    "end_device": {"ids": ids,
                   "session": {"dev_addr": DEV_ADDR,
                               "keys": {"app_s_key": {"key": APPS}}}},
    "field_mask": {"paths": ["ids.dev_eui", "ids.join_eui",
                             "session.dev_addr", "session.keys.app_s_key.key"]},
}) and ok

act = api.DeviceActivation()
act.dev_eui = DEV_EUI
act.dev_addr = DEV_ADDR.lower()
act.f_nwk_s_int_key = NWK.lower()
act.s_nwk_s_int_key = NWK.lower()
act.nwk_s_enc_key = NWK.lower()
act.app_s_key = APPS.lower()
act.f_cnt_up = 0
act.n_f_cnt_down = 0
act.a_f_cnt_down = 0
devsvc.Activate(api.ActivateDeviceRequest(device_activation=act), metadata=auth)
print("[ok]     ChirpStack: Sitzung eingetragen")

if d.is_disabled:
    d.is_disabled = False
    devsvc.Update(api.UpdateDeviceRequest(device=d), metadata=auth)
    print("[ok]     ChirpStack: Geraet scharf")

nach = devsvc.GetActivation(api.GetDeviceActivationRequest(dev_eui=DEV_EUI),
                            metadata=auth).device_activation
print(f"Kontrolle: lokale DevAddr {nach.dev_addr}")
