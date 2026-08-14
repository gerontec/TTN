#!/usr/bin/env python3
"""Raeumt doppelte Anwendungen und Geraeteprofile weg.

ChirpStack laesst gleiche Namen zu und meldet keine Doublette — mehrfache
Laeufe eines Anlege-Skripts hinterlassen deshalb leere Karteileichen.
Geloescht wird nur, was nachweislich kein Geraet enthaelt bzw. benutzt.
"""
import os

import grpc
from chirpstack_api import api

TENANT = "d2d00763-756f-4da6-91d4-57204a065051"


def token():
    with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
        for line in f:
            if line.startswith("CHIRPSTACK_TOKEN="):
                return line.strip().split("=", 1)[1]


chan = grpc.insecure_channel("127.0.0.1:8090")
AUTH = [("authorization", f"Bearer {token()}")]
aps = api.ApplicationServiceStub(chan)
ds = api.DeviceServiceStub(chan)
dp = api.DeviceProfileServiceStub(chan)

benutzte_profile = set()
for a in aps.List(api.ListApplicationsRequest(limit=100, tenant_id=TENANT), metadata=AUTH).result:
    devs = ds.List(api.ListDevicesRequest(limit=100, application_id=a.id), metadata=AUTH).result
    for d in devs:
        benutzte_profile.add(d.device_profile_id)
    if devs:
        print(f"[behalten] Anwendung {a.name} {a.id} ({len(devs)} Geraete)")
    else:
        aps.Delete(api.DeleteApplicationRequest(id=a.id), metadata=AUTH)
        print(f"[geloescht] leere Anwendung {a.name} {a.id}")

for p in dp.List(api.ListDeviceProfilesRequest(limit=100, tenant_id=TENANT), metadata=AUTH).result:
    if p.id in benutzte_profile:
        print(f"[behalten] Profil {p.name} {p.id}")
    else:
        dp.Delete(api.DeleteDeviceProfileRequest(id=p.id), metadata=AUTH)
        print(f"[geloescht] unbenutztes Profil {p.name} {p.id}")
