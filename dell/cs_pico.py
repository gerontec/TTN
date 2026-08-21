#!/usr/bin/env python3
"""Legt den Pico-LoRa-Knoten (e22pico) im lokalen ChirpStack auf dem dell an.

Baugleich zu cs_trackerd.py, nur fuer den Pico: OTAA, EU868, Class A. Der
AppKey kommt aus der Umgebung; ohne ihn laeuft alles andere trotzdem durch,
damit nur noch der Schluessel nachzutragen ist:

    APPKEY=<32 Hex> /home/gh/.venv-chirpstack/bin/python cs_pico.py

Die DevEUI ist frei gewaehlt ("PICO" + 0E22); der Pico hat keine
herstellerseitige. Ihre letzten vier Hexstellen sind zugleich die
Stationskennung des Knotens auf dem rohen Kanal (A>0E22>...).

Enum-Falle wie in cs_fix_profile.py: die Werte sind nicht der Reihe nach
vergeben, deshalb ausschliesslich die benannten Konstanten aus common.
"""
import os
import sys

import grpc
from chirpstack_api import api
from chirpstack_api import common

TENANT = "d2d00763-756f-4da6-91d4-57204a065051"
DEV_EUI = "5049434f00000e22"
JOIN_EUI = "0000000000000000"
APP_NAME = "pico"
PROFILE_NAME = "pico-otaa-eu868"

# Nutzlast des Knotens, FPort 1, 8 Byte gross-endian (lorawanNutzlast()).
CODEC = """
function decodeUplink(input) {
  var b = input.bytes;
  if (input.fPort !== 1 || b.length < 8) {
    return { data: { roh: b } };
  }
  var s8 = function (v) { return v > 127 ? v - 256 : v; };
  return { data: {
    laufzeit_min: (b[0] << 8) | b[1],
    roh_empfangen: (b[2] << 8) | b[3],
    roh_beantwortet: (b[4] << 8) | b[5],
    roh_rssi_dbm: s8(b[6]),
    roh_snr_db: s8(b[7])
  } };
}
"""


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
areq.application.description = "Pico-LoRa SX1262, zweite Betriebsart neben dem rohen Kanal"
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
p.description = "Pico-LoRa SX1262, RadioLib-LoRaWAN, OTAA, Class A"
p.tenant_id = TENANT
p.region = common.EU868
# 1.0.3, nicht 1.1: die Firmware uebergibt RadioLib nur den AppKey (nwkKey =
# NULL). Mit einem zweiten Schluessel wuerde RadioLib auf 1.1 umstellen und der
# Join gegen dieses Profil scheitern.
p.mac_version = common.LORAWAN_1_0_3
p.reg_params_revision = common.A
p.adr_algorithm_id = "default"
p.supports_otaa = True
# Class A: der Knoten haengt am Netzteil, koennte also Class C — aber im
# Krisenfall ist er der Sender, nicht der Empfaenger. Downlinks warten auf den
# naechsten Uplink; genau das reicht fuer den Steuerbefehl auf FPort 10.
p.supports_class_b = False
p.supports_class_c = False
p.uplink_interval = 900          # LW_INTERVALL_MS = 15 min
p.device_status_req_interval = 1
p.flush_queue_on_activate = True
p.payload_codec_script = CODEC
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
dreq.device.name = "pico-0e22"
dreq.device.description = "Waveshare Pico-LoRa SX1262 — LoRa/LoRaWAN umschaltbar"
dreq.device.application_id = app_id
dreq.device.device_profile_id = dp_id
existing("Geraet", lambda: dev.Create(dreq, metadata=AUTH))
print("[ok]  Geraet", DEV_EUI, "JoinEUI", JOIN_EUI)

# --- Schluessel --------------------------------------------------------------
if len(APP_KEY) == 32:
    kreq = api.CreateDeviceKeysRequest()
    kreq.device_keys.dev_eui = DEV_EUI
    kreq.device_keys.nwk_key = APP_KEY     # 1.0.x: hier steht der AppKey
    _, schon = existing("Schluessel", lambda: dev.CreateKeys(kreq, metadata=AUTH))
    if schon:
        ureq = api.UpdateDeviceKeysRequest()
        ureq.device_keys.dev_eui = DEV_EUI
        ureq.device_keys.nwk_key = APP_KEY
        dev.UpdateKeys(ureq, metadata=AUTH)
        print("[ok]  Schluessel aktualisiert")
    else:
        print("[ok]  Schluessel gesetzt")
else:
    print("[--]  kein APPKEY in der Umgebung — Schluessel bitte nachtragen")
