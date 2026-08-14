#!/usr/bin/env python3
"""Nimmt die per LoRa gefunkten Nachrichten entgegen und legt sie auf MQTT.

Gegenstueck zu dragino.py auf dem Notebook. ChirpStack liefert die
entschluesselten Uplinks auf `application/+/device/+/event/up`; hier werden die
Teile eines Rahmens wieder zusammengesetzt und unter dem urspruenglich
gemeinten Topic veroeffentlicht.

Rahmenformat auf fPort 20:

    Byte 0   Nachrichtenkennung (zufaellig, haelt gleichzeitige Nachrichten auseinander)
    Byte 1   Bit 7 = letzter Teil, Bits 0-6 = laufende Nummer
    ab 2     Nutzdaten; zusammengesetzt ergibt sich "topic\\nnachricht"

Unvollstaendige Nachrichten werden nach einer Weile verworfen — bei SF12 und
1 % Duty Cycle koennen zwischen zwei Teilen Minuten liegen, deshalb ist die
Frist grosszuegig.
"""
import base64
import json
import logging
import sys
import time

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
FPORT = 20
TTL = 1800          # halbe Stunde, siehe Duty Cycle
STATUS_TOPIC = "dragino/status"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("dragino_rx")

pending = {}        # kennung -> {"parts": {nr: bytes}, "last": nr|None, "t": zeit}


def sweep():
    now = time.time()
    for mid in [m for m, v in pending.items() if now - v["t"] > TTL]:
        v = pending.pop(mid)
        log.warning("Nachricht %02X verworfen — nur %d Teile in %ds",
                    mid, len(v["parts"]), TTL)


def assemble(mid):
    """Gibt den Text zurueck, sobald alle Teile da sind, sonst None."""
    v = pending[mid]
    if v["last"] is None:
        return None
    if set(v["parts"]) != set(range(v["last"] + 1)):
        return None
    data = b"".join(v["parts"][i] for i in range(v["last"] + 1))
    del pending[mid]
    return data.decode("utf-8", "replace")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        log.error("Verbindung zum Broker abgelehnt: %s", rc)
        return
    log.info("mit dem Broker verbunden, warte auf Uplinks")
    client.subscribe("application/+/device/+/event/up", qos=1)
    # retain wie beim Testament, sonst sieht ein spaeter hinzukommender
    # Abonnent den Dienst faelschlich als offline.
    client.publish(STATUS_TOPIC, json.dumps({"state": "online", "t": time.time()}),
                   retain=True)


def on_message(client, userdata, m):
    sweep()
    try:
        msg = json.loads(m.payload)
    except ValueError:
        return
    if msg.get("fPort") != FPORT:
        return
    raw = base64.b64decode(msg.get("data", ""))
    if len(raw) < 3:
        log.warning("Rahmen zu kurz: %s", raw.hex())
        return

    mid, hdr = raw[0], raw[1]
    seq, is_last = hdr & 0x7F, bool(hdr & 0x80)
    dev = (msg.get("deviceInfo") or {}).get("devEui", "?")
    rx = (msg.get("rxInfo") or [{}])[0]

    slot = pending.setdefault(mid, {"parts": {}, "last": None, "t": time.time()})
    slot["parts"][seq] = raw[2:]
    slot["t"] = time.time()
    if is_last:
        slot["last"] = seq
    log.info("Teil %d von %02X (%d Byte) — %s, RSSI %s, SNR %s",
             seq, mid, len(raw) - 2, dev, rx.get("rssi"), rx.get("snr"))

    text = assemble(mid)
    if text is None:
        return
    topic, _, body = text.partition("\n")
    topic = topic.strip()
    if not topic:
        log.error("Nachricht %02X ohne Topic verworfen", mid)
        return
    client.publish(topic, body, qos=1, retain=True)
    log.info("veroeffentlicht auf '%s': %s", topic, body[:120])
    client.publish(STATUS_TOPIC, json.dumps({
        "state": "message", "topic": topic, "bytes": len(body),
        "dev_eui": dev, "rssi": rx.get("rssi"), "snr": rx.get("snr"),
        "t": time.time()}))


def main():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dragino-rx")
    c.on_connect = on_connect
    c.on_message = on_message
    c.will_set(STATUS_TOPIC, json.dumps({"state": "offline"}), retain=True)
    c.connect(BROKER, 1883, keepalive=60)
    c.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
