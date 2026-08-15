#!/usr/bin/env python3
"""Zeigt fuer den Notfallkanal, welche Geraete der lokale ChirpStack kennt
und wann er sie zuletzt gehoert hat."""
import os
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

apps = api.ApplicationServiceStub(chan).List(
    api.ListApplicationsRequest(limit=100, tenant_id=TENANT), metadata=auth)
dev = api.DeviceServiceStub(chan)
for a in apps.result:
    print("Anwendung: %s" % a.name)
    ds = dev.List(api.ListDevicesRequest(limit=100, application_id=a.id), metadata=auth)
    for d in ds.result:
        seen = d.last_seen_at.ToDatetime().isoformat() if d.HasField("last_seen_at") else "nie"
        print("  %-18s %-22s zuletzt: %s" % (d.dev_eui, d.name, seen))

gws = api.GatewayServiceStub(chan).List(
    api.ListGatewaysRequest(limit=20, tenant_id=TENANT), metadata=auth)
for g in gws.result:
    seen = g.last_seen_at.ToDatetime().isoformat() if g.HasField("last_seen_at") else "nie"
    print("Gateway %s %s zuletzt: %s" % (g.gateway_id, g.name, seen))
