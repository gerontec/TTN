#!/usr/bin/env python3
"""Legt den Dragino TrackerD im lokalen ChirpStack auf dem dell an.

Gegenstueck zu cs_setup.py, aber **OTAA** statt ABP: der TrackerD hat keine
werkseitig auslesbaren Sitzungsschluessel, er kennt nur DevEUI/JoinEUI und
einen geraetespezifischen AppKey vom Aufkleber. Kein Join, keine Uplinks.

Angelegt werden Anwendung, Geraeteprofil (mit dem Payload-Decoder aus dem
TTN-Device-Repository) und das Geraet selbst. Der AppKey kommt aus der
Umgebung; ohne ihn laeuft alles andere trotzdem durch, damit nur noch der
Schluessel nachzutragen ist:

    APPKEY=<32 Hex> /home/gh/.venv-chirpstack/bin/python cs_trackerd.py

Enum-Falle wie in cs_fix_profile.py: die Werte sind nicht der Reihe nach
vergeben, deshalb ausschliesslich die benannten Konstanten aus common.
"""
import os
import sys

import grpc
from chirpstack_api import api
from chirpstack_api import common

TENANT = "d2d00763-756f-4da6-91d4-57204a065051"
DEV_EUI = "a840414f1188076c"
JOIN_EUI = "a840410000000102"
APP_NAME = "tracker"
PROFILE_NAME = "trackerd-otaa-eu868"
CODEC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trackerd.js")


def token():
    with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
        for line in f:
            if line.startswith("CHIRPSTACK_TOKEN="):
                return line.strip().split("=", 1)[1]
    sys.exit("kein ChirpStack-Token gefunden")


chan = grpc.insecure_channel("127.0.0.1:8090")
AUTH = [("authorization", f"Bearer {token()}")]
APP_KEY = (os.environ.get("APPKEY") or "").lower().replace(" ", "")


def existing(label, fn):
    """Doppelanlage ist bei einem zweiten Lauf kein Fehler.

    CreateDevice meldet das nicht sauber als ALREADY_EXISTS, sondern reicht den
    Postgres-Fehler als INTERNAL durch — deshalb beide Faelle."""
    try:
        return fn(), False
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.ALREADY_EXISTS or (
                e.code() == grpc.StatusCode.INTERNAL and "duplicate key" in (e.details() or "")):
            print(f"[da]  {label} existiert bereits")
            return None, True
        raise


# --- Anwendung ---------------------------------------------------------------
app = api.ApplicationServiceStub(chan)
areq = api.CreateApplicationRequest()
areq.application.name = APP_NAME
areq.application.description = "GPS-Tracker am Gateway Lenggries"
areq.application.tenant_id = TENANT
# Erst suchen, dann anlegen: ChirpStack laesst gleiche Namen zu und meldet
# keine Doublette — ein zweiter Lauf wuerde sonst eine leere Karteileiche
# hinterlassen statt die vorhandene Anwendung zu finden.
lst = app.List(api.ListApplicationsRequest(limit=100, tenant_id=TENANT), metadata=AUTH)
app_id = next((a.id for a in lst.result if a.name == APP_NAME), None)
if app_id:
    print("[da]  Anwendung existiert bereits")
else:
    app_id = app.Create(areq, metadata=AUTH).id
print("[ok]  Anwendung", app_id)

# --- Geraeteprofil -----------------------------------------------------------
dp = api.DeviceProfileServiceStub(chan)
preq = api.CreateDeviceProfileRequest()
p = preq.device_profile
p.name = PROFILE_NAME
p.description = "Dragino TrackerD, OTAA, Class A (Batterie)"
p.tenant_id = TENANT
p.region = common.EU868
p.mac_version = common.LORAWAN_1_0_3
p.reg_params_revision = common.A
p.adr_algorithm_id = "default"
p.supports_otaa = True
# Class A mit Absicht: der TrackerD haengt am Akku, ein dauerhaft offener
# Empfaenger waere nach wenigen Stunden leer. Downlinks warten also auf den
# naechsten Uplink — beim Alarmknopf ist das ohnehin der Moment, der zaehlt.
p.supports_class_b = False
p.supports_class_c = False
p.uplink_interval = 3600
p.device_status_req_interval = 1
p.flush_queue_on_activate = True
with open(CODEC) as f:
    p.payload_codec_script = f.read()
p.payload_codec_runtime = api.CodecRuntime.JS
lst = dp.List(api.ListDeviceProfilesRequest(limit=100, tenant_id=TENANT), metadata=AUTH)
dp_id = next((x.id for x in lst.result if x.name == PROFILE_NAME), None)
if dp_id:
    print("[da]  Geraeteprofil existiert bereits")
else:
    dp_id = dp.Create(preq, metadata=AUTH).id
print("[ok]  Geraeteprofil", dp_id)

# --- Geraet ------------------------------------------------------------------
dev = api.DeviceServiceStub(chan)
dreq = api.CreateDeviceRequest()
dreq.device.dev_eui = DEV_EUI
dreq.device.join_eui = JOIN_EUI
dreq.device.name = "trackerd-lenggries"
dreq.device.description = "Dragino TrackerD — GPS, roter Alarmknopf"
dreq.device.application_id = app_id
dreq.device.device_profile_id = dp_id
existing("Geraet", lambda: dev.Create(dreq, metadata=AUTH))
print("[ok]  Geraet", DEV_EUI, "JoinEUI", JOIN_EUI)

# --- AppKey ------------------------------------------------------------------
if len(APP_KEY) != 32:
    print("[--]  kein APPKEY in der Umgebung (32 Hex erwartet) — Geraet steht,")
    print("      kann aber erst joinen, wenn der Schluessel nachgetragen ist.")
    sys.exit(0)

kreq = api.CreateDeviceKeysRequest()
kreq.device_keys.dev_eui = DEV_EUI
# Bei LoRaWAN 1.0.x ist der AppKey vom Aufkleber das Feld nwk_key — app_key
# wertet ChirpStack erst ab 1.1 aus.
kreq.device_keys.nwk_key = APP_KEY
kreq.device_keys.app_key = APP_KEY
_, dup = existing("Schluessel", lambda: dev.CreateKeys(kreq, metadata=AUTH))
if dup:
    ureq = api.UpdateDeviceKeysRequest()
    ureq.device_keys.CopyFrom(kreq.device_keys)
    dev.UpdateKeys(ureq, metadata=AUTH)
    print("[ok]  Schluessel ersetzt")
else:
    print("[ok]  Schluessel gesetzt")
print("      jetzt am TrackerD einen Join ausloesen")
