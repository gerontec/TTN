#!/usr/bin/env python3
"""Loescht ein Geraet vollstaendig aus The Things Stack.

Noetig, weil TTS ein Geraet auf vier Dienste verteilt und ein halb angelegtes
Geraet nicht reparierbar ist: steht es im Identity Server, aber nicht in
Network- und Application Server, laufen alle weiteren PUTs in ein 409, und
GET auf NS/AS liefert `entity not found`. Genau dieser Zustand entsteht auch
beim Wechsel von OTAA auf ABP -- dafuer muss das Geraet weg und neu angelegt
werden.

Reihenfolge ist wichtig: erst die abhaengigen Dienste, zuletzt der Identity
Server. Ein 404 unterwegs ist kein Fehler, sondern heisst nur, dass dieser
Dienst das Geraet ohnehin nicht kannte.

    ./ttn_delete.py <device_id>
"""
import os
import re
import sys
import urllib.error
import urllib.request

HOST = "https://eu1.cloud.thethings.network"
APP = "lenggries-sensors"

with open(os.path.expanduser("~/.config/ttn/lenggries.key")) as f:
    K = re.search(r"NNSXS\.[A-Z0-9]+\.[A-Z0-9]+", f.read()).group(0)


def delete(label, path):
    req = urllib.request.Request(HOST + path, method="DELETE")
    req.add_header("Authorization", "Bearer " + K)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"[ok]   {label}: geloescht ({r.status})")
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[--]   {label}: kannte das Geraet nicht")
            return True
        print(f"[FEHL] {label}: HTTP {e.code} — {e.read().decode()[:200]}")
        return False


dev = sys.argv[1]
ok = delete("Join Server", f"/api/v3/js/applications/{APP}/devices/{dev}")
ok = delete("Network Server", f"/api/v3/ns/applications/{APP}/devices/{dev}") and ok
ok = delete("Application Server", f"/api/v3/as/applications/{APP}/devices/{dev}") and ok
ok = delete("Identity Server", f"/api/v3/applications/{APP}/devices/{dev}") and ok
sys.exit(0 if ok else 1)
