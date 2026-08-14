#!/usr/bin/env python3
"""Alles, was der TrackerD sendet, geht in den Krisen-Rundruf.

Der Weg ist bewusst kurz gehalten: ChirpStack dekodiert den Uplink bereits mit
dem Codec aus dem Geraeteprofil, hier wird daraus nur ein knapper Satz und auf
`crisis` gelegt. Von dort uebernimmt crisis_bcast.py und stellt ihn jedem
LoRaWAN-Geraet in die Downlink-Warteschlange.

**Warum es kurz sein muss:** crisis_bcast stueckelt bei 49 Byte, und jedes
Stueck kostet bei SF12 gut eine Sekunde Sendezeit — pro Empfaenger. Der Text
bleibt deshalb unter einem Stueck. Bei 1 % Duty Cycle ist das die Grenze
zwischen "geht raus" und "Gateway sendet stundenlang nach".
"""
import json
import logging
import sys
import time

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
DEV_EUI = "a840414f1188076c"
TOPIC = "crisis"
STATUS = "trackerd/status"
GRENZE = 49                 # ein Stueck bei crisis_bcast

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("trackerd_bcast")


def satz(obj, port):
    """Knapper Text aus dem, was der Codec hergibt — leer, wenn nichts taugt."""
    teile = ["TrackerD"]
    lat, lon = obj.get("Latitude"), obj.get("Longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        # Ohne Fix meldet der TrackerD 0/0 — das als Position weiterzugeben
        # waere schlimmer als gar keine, deshalb ausdruecklich benannt.
        teile.append(f"{lat:.4f},{lon:.4f}" if (lat or lon) else "kein Fix")
    if str(obj.get("ALARM_status", "")).upper() in ("TRUE", "1", "ALARM"):
        teile.append("ALARM")
    bat = obj.get("BatV")
    if isinstance(bat, (int, float)):
        teile.append(f"{bat:.2f}V")
    tem = obj.get("Tem")
    if isinstance(tem, (int, float)):
        teile.append(f"{tem:.0f}C")
    if len(teile) == 1:
        # Kein verwertbares Feld — dann wenigstens melden, dass er sich
        # geruehrt hat; der fPort sagt, was es war.
        teile.append(f"fPort{port}")
    return " ".join(teile)[:GRENZE]


def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        log.error("Broker lehnt ab: %s", rc)
        return
    log.info("verbunden, warte auf Uplinks von %s", DEV_EUI)
    client.subscribe("application/+/device/+/event/up", qos=1)
    client.publish(STATUS, json.dumps({"state": "online", "t": time.time()}),
                   retain=True)


def on_message(client, userdata, m):
    try:
        msg = json.loads(m.payload)
    except ValueError:
        return
    if (msg.get("deviceInfo") or {}).get("devEui", "").lower() != DEV_EUI:
        return

    obj = msg.get("object") or {}
    port = msg.get("fPort")
    rx = (msg.get("rxInfo") or [{}])[0]
    text = satz(obj, port)

    client.publish(TOPIC, text, qos=1)
    log.info("-> crisis: %s (fPort %s, RSSI %s, SNR %s)",
             text, port, rx.get("rssi"), rx.get("snr"))
    client.publish(STATUS, json.dumps({
        "state": "forwarded", "text": text, "fPort": port,
        "rssi": rx.get("rssi"), "snr": rx.get("snr"), "t": time.time()}))


def main():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="trackerd-bcast")
    c.on_connect = on_connect
    c.on_message = on_message
    c.will_set(STATUS, json.dumps({"state": "offline"}), retain=True)
    c.connect(BROKER, 1883, keepalive=60)
    c.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
