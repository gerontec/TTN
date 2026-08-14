#!/usr/bin/env python3
"""Korrigiert das Geraeteprofil des LA66 auf EU868 / LoRaWAN 1.0.3 Rev. A.

Die Enum-Werte sind nicht der Reihe nach vergeben — `region=3` ist CN779, nicht
EU868, und MacVersion 1.0.3 ist 3, nicht 2. Deshalb hier ausschliesslich die
benannten Konstanten aus common_pb2 statt roher Zahlen.
"""
import os

import grpc
from chirpstack_api import api
from chirpstack_api import common

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

print("vorher :", f"region={cur.region} mac_version={cur.mac_version} "
                  f"reg_params_revision={cur.reg_params_revision}")

cur.region = common.EU868
cur.mac_version = common.LORAWAN_1_0_3
cur.reg_params_revision = common.A
dp.Update(api.UpdateDeviceProfileRequest(device_profile=cur), metadata=AUTH)

neu = dp.Get(api.GetDeviceProfileRequest(id=pid), metadata=AUTH).device_profile
print("nachher:", f"region={neu.region} ({common.Region.Name(neu.region)}) "
                  f"mac_version={neu.mac_version} ({common.MacVersion.Name(neu.mac_version)}) "
                  f"reg_params_revision={neu.reg_params_revision} "
                  f"({common.RegParamsRevision.Name(neu.reg_params_revision)})")
