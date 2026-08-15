#!/usr/bin/env python3
"""Listet Anwendungen mit Geraetezahl und loescht auf Wunsch eine leere.

    cs_dupapp.py            # nur zeigen
    cs_dupapp.py <app_id>   # diese Anwendung loeschen, aber nur wenn leer
"""
import os
import sys
import grpc
from chirpstack_api import api

TENANT = "d2d00763-756f-4da6-91d4-57204a065051"

cfg = {}
with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            cfg[k] = v

chan = grpc.insecure_channel("127.0.0.1:8090")
auth = [("authorization", "Bearer " + cfg["CHIRPSTACK_TOKEN"])]
app = api.ApplicationServiceStub(chan)
dev = api.DeviceServiceStub(chan)

apps = app.List(api.ListApplicationsRequest(limit=100, tenant_id=TENANT), metadata=auth)
counts = {}
for a in apps.result:
    n = dev.List(api.ListDevicesRequest(limit=100, application_id=a.id),
                 metadata=auth).total_count
    counts[a.id] = n
    print("%s  %-12s Geraete: %d" % (a.id, a.name, n))

if len(sys.argv) > 1:
    target = sys.argv[1]
    if target not in counts:
        sys.exit("Anwendung %s gibt es nicht" % target)
    if counts[target] != 0:
        sys.exit("Anwendung %s hat %d Geraete - nicht geloescht"
                 % (target, counts[target]))
    app.Delete(api.DeleteApplicationRequest(id=target), metadata=auth)
    print("geloescht:", target)
