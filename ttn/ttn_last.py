#!/usr/bin/env python3
"""Letzte Uplinks aus der TTS-Storage-Integration."""
import json, os, re, urllib.error, urllib.request
HOST = "https://eu1.cloud.thethings.network"
APP = "lenggries-sensors"
K = re.search(r"NNSXS\.[A-Z0-9]+\.[A-Z0-9]+",
              open(os.path.expanduser("~/.config/ttn/lenggries.key")).read()).group(0)
url = (HOST + "/api/v3/as/applications/" + APP +
       "/packages/storage/uplink_message?limit=6&order=-received_at")
req = urllib.request.Request(url)
req.add_header("Authorization", "Bearer " + K)
try:
    body = urllib.request.urlopen(req, timeout=30).read().decode()
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:250])
    raise SystemExit
n = 0
for line in body.strip().splitlines():
    try:
        d = json.loads(line)["result"]
    except Exception:
        continue
    u = d.get("uplink_message", {})
    print("%-20s %s  fport=%s payload=%s" % (
        d["end_device_ids"]["device_id"], d.get("received_at", "")[:19],
        u.get("f_port"), u.get("frm_payload")))
    n += 1
if not n:
    print("keine Uplinks in der Storage-Integration")
