#!/usr/bin/env python3
"""Aktiviert den LA66 erneut, damit die Geraeteklasse aus dem Profil neu greift.

ChirpStack leitet `enabled_class` bei der Aktivierung aus dem Geraeteprofil ab.
Wird das Profil spaeter auf Class C umgestellt, bleibt ein bereits aktiviertes
Geraet auf A stehen — es hilft nur, die Aktivierung zu wiederholen.
"""
import os

import grpc
from chirpstack_api import api

DEV_EUI = "a8404117f18962e0"
DEV_ADDR = "018962e0"


def token():
    with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
        for line in f:
            if line.startswith("CHIRPSTACK_TOKEN="):
                return line.strip().split("=", 1)[1]


chan = grpc.insecure_channel("127.0.0.1:8090")
AUTH = [("authorization", f"Bearer {token()}")]
dev = api.DeviceServiceStub(chan)

nwk = os.environ["NWKSKEY"].lower()
app = os.environ["APPSKEY"].lower()

req = api.ActivateDeviceRequest()
a = req.device_activation
a.dev_eui = DEV_EUI
a.dev_addr = DEV_ADDR
a.app_s_key = app
a.nwk_s_enc_key = nwk
a.s_nwk_s_int_key = nwk
a.f_nwk_s_int_key = nwk
a.f_cnt_up = 0
a.n_f_cnt_down = 0
dev.Activate(req, metadata=AUTH)
print("neu aktiviert:", DEV_EUI, "DevAddr", DEV_ADDR)
