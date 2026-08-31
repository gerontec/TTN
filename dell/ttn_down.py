#!/usr/bin/env python3
"""Einen Downlink an ein TTN-Geraet stellen, als Hex auf der Kommandozeile.

Die Befehlstabelle des TrackerD steht in devices/trackerd_stock148/ATcmdTrackerD.md;
sie gilt auf jedem Port ausser 0. Haeufig gebraucht:

    ./ttn_down.py 2301        # Geraetestatus anfordern (Rahmen auf fPort 5)
    ./ttn_down.py 01000258    # AT+TDC = 600 s
    ./ttn_down.py AF01        # AT+INTWK = 1

Der Downlink wird nur eingereiht. Ein Class-A-Geraet holt ihn im
Empfangsfenster nach seinem naechsten Uplink ab -- beim TrackerD also nach bis
zu einem vollen TDC-Takt.
"""
import base64, json, os, sys, urllib.error, urllib.request

HOST = os.environ.get("TTN_HOST", "eu1.cloud.thethings.network")
SCHLUESSEL = os.path.expanduser("~/.config/ttn/lenggries.key")


def schluessel():
    for zeile in open(SCHLUESSEL):
        if zeile.startswith("TTN_KEY="):
            return zeile.split("=", 1)[1].strip()
    sys.exit("kein TTN_KEY in " + SCHLUESSEL)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    roh = sys.argv[1].replace(" ", "")
    geraet = sys.argv[2] if len(sys.argv) > 2 else "trackerd-lenggries"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    if port == 0:
        sys.exit("Port 0 ist fuer MAC-Kommandos reserviert")
    try:
        nutz = bytes.fromhex(roh)
    except ValueError:
        sys.exit("kein gueltiges Hex: " + roh)

    key = schluessel()
    kopf = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    req = urllib.request.Request(f"https://{HOST}/api/v3/auth_info", headers=kopf)
    app = json.load(urllib.request.urlopen(req, timeout=15))
    app = app["api_key"]["entity_ids"]["application_ids"]["application_id"]

    koerper = {"downlinks": [{"f_port": port,
                              "frm_payload": base64.b64encode(nutz).decode(),
                              "priority": "NORMAL"}]}
    req = urllib.request.Request(
        f"https://{HOST}/api/v3/as/applications/{app}/devices/{geraet}/down/push",
        data=json.dumps(koerper).encode(), headers=kopf, method="POST")
    try:
        urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as e:
        sys.exit("abgelehnt: %s %s" % (e.code, e.read()[:300].decode("utf-8", "replace")))
    print("eingereiht: %s -> %s/%s, fPort %d (%d Byte)"
          % (nutz.hex(), app, geraet, port, len(nutz)))


if __name__ == "__main__":
    main()
