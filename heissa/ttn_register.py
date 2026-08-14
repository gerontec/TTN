#!/usr/bin/env python3
"""Registriert ein OTAA-Geraet bei The Things Stack.

TTS verteilt ein Geraet auf vier Dienste, die nacheinander bedient werden
muessen — Identity Server, Join Server, Network Server, Application Server.
Ein einziger POST reicht nicht, und die Reihenfolge ist nicht beliebig.

Aufruf (auf heissa.de, der API-Key liegt dort):
    APPKEY=<hex> ./ttn_register.py <device_id> <dev_eui> <join_eui> [modell]

Der AppKey kommt bewusst aus der Umgebung und nicht aus argv, damit er nicht
in der Prozessliste steht.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

HOST = "https://eu1.cloud.thethings.network"
APP = "lenggries-sensors"
FREQ_PLAN = "EU_863_870_TTN"


def key():
    """Der Key steht als `TTN_KEY=NNSXS....` in der Datei, also nicht am
    Wortanfang suchen."""
    with open(os.path.expanduser("~/.config/ttn/lenggries.key")) as f:
        m = re.search(r"NNSXS\.[A-Z0-9]+\.[A-Z0-9]+", f.read())
    if not m:
        sys.exit("kein API-Key gefunden")
    return m.group(0)


K = key()


def call(method, path, payload):
    req = urllib.request.Request(
        HOST + path, data=json.dumps(payload).encode(), method=method)
    req.add_header("Authorization", f"Bearer {K}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            body = json.loads(body)
        except ValueError:
            pass
        return e.code, body


def step(label, method, path, payload):
    st, bd = call(method, path, payload)
    if st < 300:
        print(f"[ok]     {label}")
        return True
    msg = bd.get("message", bd) if isinstance(bd, dict) else bd
    # Ein schon vorhandenes Geraet ist kein Fehlschlag, sondern ein Neulauf.
    if st == 409 or "already exists" in str(msg):
        print(f"[da]     {label}: existiert bereits")
        return True
    print(f"[FEHLER] {label}: HTTP {st} — {msg}")
    return False


dev_id, dev_eui, join_eui = sys.argv[1], sys.argv[2].upper(), sys.argv[3].upper()
model = sys.argv[4] if len(sys.argv) > 4 else ""
app_key = os.environ["APPKEY"].upper().replace(" ", "")
ids = {"device_id": dev_id, "dev_eui": dev_eui, "join_eui": join_eui,
       "application_ids": {"application_id": APP}}

ok = step("Identity Server", "POST", f"/api/v3/applications/{APP}/devices", {
    "end_device": {
        "ids": ids,
        "name": model or dev_id,
        "description": f"{model} am Gateway lenggries-dlos8n".strip(),
        "join_server_address": "eu1.cloud.thethings.network",
        "network_server_address": "eu1.cloud.thethings.network",
        "application_server_address": "eu1.cloud.thethings.network",
    },
    "field_mask": {"paths": [
        "ids.dev_eui", "ids.join_eui", "name", "description",
        "join_server_address", "network_server_address",
        "application_server_address"]},
})

# Join Server: hier liegt der AppKey, mit dem der Join-Request geprueft wird.
ok = step("Join Server", "PUT", f"/api/v3/js/applications/{APP}/devices/{dev_id}", {
    "end_device": {
        "ids": ids,
        "network_server_address": "eu1.cloud.thethings.network",
        "application_server_address": "eu1.cloud.thethings.network",
        "root_keys": {"app_key": {"key": app_key}},
    },
    "field_mask": {"paths": [
        "ids.dev_eui", "ids.join_eui", "network_server_address",
        "application_server_address", "root_keys.app_key.key"]},
}) and ok

ok = step("Network Server", "PUT", f"/api/v3/ns/applications/{APP}/devices/{dev_id}", {
    "end_device": {
        "ids": ids,
        "frequency_plan_id": FREQ_PLAN,
        "lorawan_version": "MAC_V1_0_3",
        "lorawan_phy_version": "PHY_V1_0_3_REV_A",
        "supports_join": True,
        "supports_class_b": False,
        "supports_class_c": False,
        "multicast": False,
    },
    "field_mask": {"paths": [
        "ids.dev_eui", "ids.join_eui", "frequency_plan_id", "lorawan_version",
        "lorawan_phy_version", "supports_join", "supports_class_b",
        "supports_class_c", "multicast"]},
}) and ok

ok = step("Application Server", "PUT", f"/api/v3/as/applications/{APP}/devices/{dev_id}", {
    "end_device": {"ids": ids},
    "field_mask": {"paths": ["ids.dev_eui", "ids.join_eui"]},
}) and ok

sys.exit(0 if ok else 1)
