#!/usr/bin/env python3
"""Traegt die bei TTN entstandene Sitzung als ABP in den lokalen ChirpStack.

Die Richtung ist Absicht und ergibt sich aus einer Grenze des Netzes: TTN
verarbeitet nur DevAddr aus `260B0000/16`, ein lokal vergebener Adressbereich
wird dort verworfen. Die Adresse muss also von TTN kommen — und das heisst,
das Geraet joint bei TTN. Damit der lokale ChirpStack dieselben Rahmen
weiterhin entschluesselt, bekommt er die entstandene Sitzung hier als ABP
eingetragen.

Danach hoeren beide Netze mit; gesendet wird lokal weiter, ohne dass ein Join
noetig waere. Die Sitzungsschluessel wandern im Prozess und werden nie
ausgegeben.

    /home/gh/.venv-chirpstack/bin/python cs_abp_from_ttn.py <dev_eui> <ttn_dev_id>
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

import grpc
from chirpstack_api import api

if len(sys.argv) != 3:
    sys.exit(__doc__)
DEV_EUI = sys.argv[1].lower()
TTN_ID = sys.argv[2]
HOST = "https://eu1.cloud.thethings.network"

with open(os.path.expanduser("~/.config/ttn/lenggries.key")) as f:
    TKEY = re.search(r"NNSXS\.[A-Z0-9]+\.[A-Z0-9]+", f.read()).group(0)


def tts(path):
    req = urllib.request.Request(HOST + path,
                                 headers={"Authorization": "Bearer " + TKEY})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"TTS HTTP {e.code}: {e.read().decode()[:200]}")


app = tts("/api/v3/auth_info")
APP = (((app.get("api_key") or {}).get("entity_ids") or {})
       .get("application_ids") or {}).get("application_id")

ns = tts(f"/api/v3/ns/applications/{APP}/devices/{TTN_ID}"
         "?field_mask=session.dev_addr,session.keys.f_nwk_s_int_key.key,"
         "session.last_f_cnt_up")
a_s = tts(f"/api/v3/as/applications/{APP}/devices/{TTN_ID}"
          "?field_mask=session.keys.app_s_key.key")

sess = ns.get("session") or {}
dev_addr = sess.get("dev_addr")
nwk_s_key = (((sess.get("keys") or {}).get("f_nwk_s_int_key") or {}).get("key"))
app_s_key = ((((a_s.get("session") or {}).get("keys") or {})
              .get("app_s_key") or {}).get("key"))
f_cnt_up = int(sess.get("last_f_cnt_up") or 0)

if not (dev_addr and nwk_s_key and app_s_key):
    sys.exit("TTS hat (noch) keine vollstaendige Sitzung — erst joinen lassen.")
print(f"TTN-Sitzung: DevAddr {dev_addr}, FCntUp {f_cnt_up}")

cfg = {}
with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            cfg[k] = v
chan = grpc.insecure_channel("127.0.0.1:8090")
auth = [("authorization", "Bearer " + cfg["CHIRPSTACK_TOKEN"])]
devsvc = api.DeviceServiceStub(chan)

act = api.DeviceActivation()
act.dev_eui = DEV_EUI
act.dev_addr = dev_addr.lower()
# LoRaWAN 1.0.x: ein einziger NwkSKey, den ChirpStack in drei Feldern fuehrt.
act.f_nwk_s_int_key = nwk_s_key.lower()
act.s_nwk_s_int_key = nwk_s_key.lower()
act.nwk_s_enc_key = nwk_s_key.lower()
act.app_s_key = app_s_key.lower()
# Der Zaehler kommt von TTS, damit der lokale Server nicht bei der naechsten
# Sendung einen Ruecksprung sieht und den Rahmen verwirft.
act.f_cnt_up = f_cnt_up
act.n_f_cnt_down = 0
act.a_f_cnt_down = 0
devsvc.Activate(api.ActivateDeviceRequest(device_activation=act), metadata=auth)
print("ChirpStack: Sitzung eingetragen")

dev = devsvc.Get(api.GetDeviceRequest(dev_eui=DEV_EUI), metadata=auth).device
if dev.is_disabled:
    dev.is_disabled = False
    devsvc.Update(api.UpdateDeviceRequest(device=dev), metadata=auth)
    print("ChirpStack: Geraet wieder scharf")

nach = devsvc.GetActivation(api.GetDeviceActivationRequest(dev_eui=DEV_EUI),
                            metadata=auth).device_activation
print(f"Kontrolle: lokale DevAddr {nach.dev_addr}, FCntUp {nach.f_cnt_up}")
