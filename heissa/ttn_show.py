#!/usr/bin/env python3
"""Zeigt, was TTS zu einem Geraet wirklich gespeichert hat (IS/NS/AS)."""
import json, os, re, sys, urllib.error, urllib.request

HOST = "https://eu1.cloud.thethings.network"
APP = "lenggries-sensors"
with open(os.path.expanduser("~/.config/ttn/lenggries.key")) as f:
    K = re.search(r"NNSXS\.[A-Z0-9]+\.[A-Z0-9]+", f.read()).group(0)

def get(path):
    req = urllib.request.Request(HOST + path)
    req.add_header("Authorization", "Bearer " + K)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]

dev = sys.argv[1]
for label, path in (
    ("IS", f"/api/v3/applications/{APP}/devices/{dev}?field_mask=name,ids.dev_addr"),
    ("NS", f"/api/v3/ns/applications/{APP}/devices/{dev}"
           "?field_mask=supports_join,session.dev_addr,session.last_f_cnt_up,session.started_at"),
    ("AS", f"/api/v3/as/applications/{APP}/devices/{dev}"
           "?field_mask=session.dev_addr,session.keys.app_s_key.key"),
):
    st, bd = get(path)
    if isinstance(bd, dict) and "session" in bd:
        print(label, st, json.dumps(bd["session"])[:300])
    else:
        print(label, st, json.dumps(bd)[:200] if isinstance(bd, dict) else bd)
