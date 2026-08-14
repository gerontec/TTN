#!/usr/bin/env python3
"""Schaltet das LA66-Profil auf Class C.

Class A hoert nur zwei kurze Fenster nach einem eigenen Uplink — als
Notfall-Empfaenger waere das Geraet damit fast nur Sender. Class C laesst den
Empfaenger dauerhaft offen (auf RX2, 869.525 MHz, DR0), sodass ein Broadcast
sofort ankommt statt erst beim naechsten Uplink. Das kostet Strom, was am USB
aber egal ist.
"""
import os

import grpc
from chirpstack_api import api

PROFILE_NAME = "la66-abp-eu868"
TENANT = "d2d00763-756f-4da6-91d4-57204a065051"


def token():
    with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
        for line in f:
            if line.startswith("CHIRPSTACK_TOKEN="):
                return line.strip().split("=", 1)[1]


chan = grpc.insecure_channel("127.0.0.1:8090")
AUTH = [("authorization", f"Bearer {token()}")]
dp = api.DeviceProfileServiceStub(chan)

lst = dp.List(api.ListDeviceProfilesRequest(limit=100, tenant_id=TENANT), metadata=AUTH)
pid = next(p.id for p in lst.result if p.name == PROFILE_NAME)
cur = dp.Get(api.GetDeviceProfileRequest(id=pid), metadata=AUTH).device_profile

print(f"vorher : class_b={cur.supports_class_b} class_c={cur.supports_class_c}")
cur.supports_class_c = True
cur.class_c_timeout = 30
dp.Update(api.UpdateDeviceProfileRequest(device_profile=cur), metadata=AUTH)

neu = dp.Get(api.GetDeviceProfileRequest(id=pid), metadata=AUTH).device_profile
print(f"nachher: class_c={neu.supports_class_c} timeout={neu.class_c_timeout}s")
