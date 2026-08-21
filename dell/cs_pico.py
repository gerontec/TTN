#!/usr/bin/env python3
"""Creates the Pico-LoRa node (e22pico) in the local ChirpStack on the dell.

Built like cs_trackerd.py, only for the Pico: OTAA, EU868, class A. The AppKey
comes from the environment; without it everything else still runs through, so
that only the key remains to be filled in:

    APPKEY=<32 hex> /home/gh/.venv-chirpstack/bin/python cs_pico.py

The DevEUI is freely chosen ("PICO" + 0E22); the Pico has no vendor one. Its
last four hex digits double as the node's station id on the raw channel
(A>0E22>...).

Enum trap as in cs_fix_profile.py: the values are not assigned in order, so use
the named constants from common exclusively.
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

# The node payload, FPort 1, 8 bytes big endian (lorawanNutzlast()).
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
    sys.exit("no ChirpStack token found")


chan = grpc.insecure_channel("127.0.0.1:8090")
AUTH = [("authorization", f"Bearer {token()}")]
APP_KEY = (os.environ.get("APPKEY") or "").lower().replace(" ", "")


def existing(label, fn):
    """Creating something twice is not an error on a second run.

    CreateDevice does not report that cleanly as ALREADY_EXISTS but passes the
    Postgres error through as INTERNAL -- hence both cases."""
    try:
        return fn(), False
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.ALREADY_EXISTS or (
                e.code() == grpc.StatusCode.INTERNAL and "duplicate key" in (e.details() or "")):
            print(f"[has] {label} already exists")
            return None, True
        raise


# --- application -------------------------------------------------------------
app = api.ApplicationServiceStub(chan)
areq = api.CreateApplicationRequest()
areq.application.name = APP_NAME
areq.application.description = "Pico-LoRa SX1262, second mode next to the raw channel"
areq.application.tenant_id = TENANT
# Search first, then create: ChirpStack allows identical names and reports no
# duplicate -- a second run would otherwise leave an empty shell behind instead
# of finding the existing application.
lst = app.List(api.ListApplicationsRequest(limit=100, tenant_id=TENANT), metadata=AUTH)
app_id = next((a.id for a in lst.result if a.name == APP_NAME), None)
if app_id:
    print("[has] application already exists")
else:
    app_id = app.Create(areq, metadata=AUTH).id
print("[ok]  application", app_id)

# --- device profile ----------------------------------------------------------
dp = api.DeviceProfileServiceStub(chan)
preq = api.CreateDeviceProfileRequest()
p = preq.device_profile
p.name = PROFILE_NAME
p.description = "Pico-LoRa SX1262, RadioLib LoRaWAN, OTAA, class A"
p.tenant_id = TENANT
p.region = common.EU868
# 1.0.3, not 1.1: the firmware hands RadioLib the AppKey only (nwkKey = NULL).
# With a second key RadioLib would switch to 1.1 and the join against this
# profile would fail.
p.mac_version = common.LORAWAN_1_0_3
p.reg_params_revision = common.A
p.adr_algorithm_id = "default"
p.supports_otaa = True
# Class A: the node runs off a power supply and could do class C -- but in a
# crisis it is the sender, not the receiver. Downlinks wait for the next
# uplink; that is exactly enough for the control command on FPort 10.
p.supports_class_b = False
p.supports_class_c = False
p.uplink_interval = 900          # LW_INTERVAL_MS = 15 min
p.device_status_req_interval = 1
p.flush_queue_on_activate = True
p.payload_codec_script = CODEC
p.payload_codec_runtime = api.CodecRuntime.JS
lst = dp.List(api.ListDeviceProfilesRequest(limit=100, tenant_id=TENANT), metadata=AUTH)
dp_id = next((x.id for x in lst.result if x.name == PROFILE_NAME), None)
if dp_id:
    print("[has] device profile already exists")
else:
    dp_id = dp.Create(preq, metadata=AUTH).id
print("[ok]  device profile", dp_id)

# --- device --------------------------------------------------------------------
dev = api.DeviceServiceStub(chan)
dreq = api.CreateDeviceRequest()
dreq.device.dev_eui = DEV_EUI
dreq.device.join_eui = JOIN_EUI
dreq.device.name = "pico-0e22"
dreq.device.description = "Waveshare Pico-LoRa SX1262 -- switchable LoRa/LoRaWAN"
dreq.device.application_id = app_id
dreq.device.device_profile_id = dp_id
existing("device", lambda: dev.Create(dreq, metadata=AUTH))
print("[ok]  device", DEV_EUI, "JoinEUI", JOIN_EUI)

# --- keys ----------------------------------------------------------------------
if len(APP_KEY) == 32:
    kreq = api.CreateDeviceKeysRequest()
    kreq.device_keys.dev_eui = DEV_EUI
    kreq.device_keys.nwk_key = APP_KEY     # 1.0.x: the AppKey goes here
    _, schon = existing("keys", lambda: dev.CreateKeys(kreq, metadata=AUTH))
    if schon:
        ureq = api.UpdateDeviceKeysRequest()
        ureq.device_keys.dev_eui = DEV_EUI
        ureq.device_keys.nwk_key = APP_KEY
        dev.UpdateKeys(ureq, metadata=AUTH)
        print("[ok]  keys updated")
    else:
        print("[ok]  keys set")
else:
    print("[--]  no APPKEY in the environment -- please fill the key in later")
