#!/usr/bin/env python3
"""Vergleicht die Sitzungsschluessel eines Geraets zwischen ChirpStack und TTS.

Nur Fingerabdruecke (SHA-256, gekuerzt), nie die Schluessel selbst. Gross- und
Kleinschreibung wird vorher vereinheitlicht — sonst meldet der Vergleich einen
Unterschied, wo keiner ist.

    /home/gh/.venv-chirpstack/bin/python ttn_keycheck.py <dev_eui> <ttn_dev_id>
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

import grpc
from chirpstack_api import api

DEV_EUI = sys.argv[1].lower()
TTN_ID = sys.argv[2]
HOST = "https://eu1.cloud.thethings.network"


def fp(v):
    if not v:
        return "(leer)"
    return hashlib.sha256(v.upper().encode()).hexdigest()[:12]


cfg = {}
with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            cfg[k] = v
chan = grpc.insecure_channel("127.0.0.1:8090")
auth = [("authorization", "Bearer " + cfg["CHIRPSTACK_TOKEN"])]
act = api.DeviceServiceStub(chan).GetActivation(
    api.GetDeviceActivationRequest(dev_eui=DEV_EUI), metadata=auth).device_activation

print("ChirpStack")
print("  dev_addr        ", act.dev_addr)
print("  f_nwk_s_int_key ", fp(act.f_nwk_s_int_key))
print("  nwk_s_enc_key   ", fp(act.nwk_s_enc_key))
print("  s_nwk_s_int_key ", fp(act.s_nwk_s_int_key))
print("  app_s_key       ", fp(act.app_s_key))
print("  f_cnt_up        ", act.f_cnt_up)

with open(os.path.expanduser("~/.config/ttn/lenggries.key")) as f:
    tkey = re.search(r"NNSXS\.[A-Z0-9]+\.[A-Z0-9]+", f.read()).group(0)
app = json.load(urllib.request.urlopen(urllib.request.Request(
    HOST + "/api/v3/auth_info",
    headers={"Authorization": "Bearer " + tkey}), timeout=10))
app = (((app.get("api_key") or {}).get("entity_ids") or {})
       .get("application_ids") or {}).get("application_id")


def tts(server, mask):
    url = f"{HOST}/api/v3/{server}/applications/{app}/devices/{TTN_ID}?field_mask={mask}"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tkey})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, "msg": e.read().decode()[:200]}


ns = tts("ns", "session.dev_addr,session.keys.f_nwk_s_int_key.key,session.last_f_cnt_up")
a_s = tts("as", "session.keys.app_s_key.key")
print(f"\nTTS ({app})")
sess = ns.get("session") or {}
print("  dev_addr        ", sess.get("dev_addr"))
print("  f_nwk_s_int_key ", fp(((sess.get("keys") or {}).get("f_nwk_s_int_key") or {}).get("key")))
print("  app_s_key       ", fp((((a_s.get("session") or {}).get("keys") or {}).get("app_s_key") or {}).get("key")))
print("  last_f_cnt_up   ", sess.get("last_f_cnt_up", "(noch keiner)"))
