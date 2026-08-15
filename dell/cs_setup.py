#!/usr/bin/env python3
"""Richtet den lokalen ChirpStack auf dem dell fuer den Notfallkanal ein.

Diese Installation hat keine REST-Transkodierung (alle /api/...-Pfade
antworten 404), deshalb gRPC.

Angelegt werden: Gateway, Anwendung, Geraeteprofil und der LA66 als
**ABP**-Geraet. ABP mit Absicht — im Krisenfall soll kein Join-Handshake
noetig sein, das Geraet muss ohne Gegenstelle sofort senden koennen. Die
Sitzungsschluessel sind die, die im LA66 ohnehin schon werkseitig stehen
(aus AT+CFG ausgelesen), es muss also nichts umgeschluesselt werden.
"""
import os
import sys

import grpc
from chirpstack_api import api

GW_EUI = "a84041ffff27e318"
DEV_EUI = "a8404117f18962e0"
DEV_ADDR = "018962e0"
APP_NAME = "notfall"
PROFILE_NAME = "la66-abp-eu868"


def cfg():
    out = {}
    with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                out[k] = v
    return out


C = cfg()
chan = grpc.insecure_channel("127.0.0.1:8090")   # ChirpStack v4 fuehrt gRPC und Web-UI auf demselben Port
AUTH = [("authorization", f"Bearer {C['CHIRPSTACK_TOKEN']}")]
TENANT = sys.argv[1]
NWK_S_KEY = os.environ["NWKSKEY"].lower()
APP_S_KEY = os.environ["APPSKEY"].lower()


def existing(label, fn):
    """ChirpStack wirft bei Doppelanlage AlreadyExists — das ist bei einem
    zweiten Lauf kein Fehler."""
    try:
        return fn(), False
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.ALREADY_EXISTS:
            print(f"[da]  {label} existiert bereits")
            return None, True
        # Beim Gateway meldet ChirpStack den Doppeleintrag nicht als
        # ALREADY_EXISTS, sondern reicht den Postgres-Fehler als INTERNAL
        # durch. Inhaltlich ist es derselbe Fall.
        if (e.code() == grpc.StatusCode.INTERNAL
                and "duplicate key value" in (e.details() or "")):
            print(f"[da]  {label} existiert bereits (duplicate key)")
            return None, True
        raise


# --- Gateway -----------------------------------------------------------------
gw = api.GatewayServiceStub(chan)
req = api.CreateGatewayRequest()
req.gateway.gateway_id = GW_EUI
req.gateway.name = "lenggries-dlos8n"
req.gateway.description = "Dragino DLOS8N, direkt im LAN (Krisenpfad)"
req.gateway.tenant_id = TENANT
req.gateway.stats_interval = 30
req.gateway.location.latitude = 47.679
req.gateway.location.longitude = 11.579
req.gateway.location.altitude = 680
existing("Gateway", lambda: gw.Create(req, metadata=AUTH))
print("[ok]  Gateway", GW_EUI)

# --- Anwendung ---------------------------------------------------------------
app = api.ApplicationServiceStub(chan)
areq = api.CreateApplicationRequest()
areq.application.name = APP_NAME
areq.application.description = "Notfallkanal ueber den LA66-USB-Adapter"
areq.application.tenant_id = TENANT
res, dup = existing("Anwendung", lambda: app.Create(areq, metadata=AUTH))
if dup:
    lst = app.List(api.ListApplicationsRequest(limit=100, tenant_id=TENANT), metadata=AUTH)
    app_id = next(a.id for a in lst.result if a.name == APP_NAME)
else:
    app_id = res.id
print("[ok]  Anwendung", app_id)

# --- Geraeteprofil -----------------------------------------------------------
dp = api.DeviceProfileServiceStub(chan)
preq = api.CreateDeviceProfileRequest()
preq.device_profile.name = PROFILE_NAME
preq.device_profile.tenant_id = TENANT
preq.device_profile.region = 3            # EU868
preq.device_profile.mac_version = 2       # LoRaWAN 1.0.3
preq.device_profile.reg_params_revision = 1
preq.device_profile.supports_otaa = False
preq.device_profile.uplink_interval = 3600
preq.device_profile.adr_algorithm_id = "default"
# Der LA66 zaehlt nach einem Neustart wieder bei 0 — ohne das verwirft
# ChirpStack die Uplinks als Replay.
preq.device_profile.flush_queue_on_activate = True
res, dup = existing("Geraeteprofil", lambda: dp.Create(preq, metadata=AUTH))
if dup:
    lst = dp.List(api.ListDeviceProfilesRequest(limit=100, tenant_id=TENANT), metadata=AUTH)
    dp_id = next(p.id for p in lst.result if p.name == PROFILE_NAME)
else:
    dp_id = res.id
print("[ok]  Geraeteprofil", dp_id)

# --- Geraet ------------------------------------------------------------------
dev = api.DeviceServiceStub(chan)
dreq = api.CreateDeviceRequest()
dreq.device.dev_eui = DEV_EUI
dreq.device.name = "la66-notfall"
dreq.device.description = "Dragino LA66 USB-Adapter — Notfallkanal vom Berg"
dreq.device.application_id = app_id
dreq.device.device_profile_id = dp_id
dreq.device.skip_fcnt_check = True
existing("Geraet", lambda: dev.Create(dreq, metadata=AUTH))
print("[ok]  Geraet", DEV_EUI)

# --- ABP-Aktivierung ---------------------------------------------------------
act = api.ActivateDeviceRequest()
act.device_activation.dev_eui = DEV_EUI
act.device_activation.dev_addr = DEV_ADDR
act.device_activation.app_s_key = APP_S_KEY
act.device_activation.nwk_s_enc_key = NWK_S_KEY
act.device_activation.s_nwk_s_int_key = NWK_S_KEY
act.device_activation.f_nwk_s_int_key = NWK_S_KEY
act.device_activation.f_cnt_up = 0
act.device_activation.n_f_cnt_down = 0
dev.Activate(act, metadata=AUTH)
print("[ok]  ABP aktiviert, DevAddr", DEV_ADDR)
