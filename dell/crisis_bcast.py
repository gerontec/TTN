#!/usr/bin/env python3
"""Broadcast-Kanal: was auf MQTT `crisis` steht, geht an alle LoRaWAN-Geraete.

    mosquitto_pub -h dell -t crisis -m "Abstieg abgebrochen, bleibt oben"

Der Dienst haengt am lokalen Broker, holt sich bei jeder Nachricht die
vollstaendige Geraeteliste aus ChirpStack und stellt den Text jedem Geraet in
die Downlink-Warteschlange.

**Wann es ankommt:** LoRaWAN Class A kennt keinen echten Rundruf. Ein Geraet
hoert nur in den beiden kurzen Fenstern direkt nach einem eigenen Uplink.
Die Nachricht liegt also in der Warteschlange und wird ausgeliefert, sobald
das jeweilige Geraet das naechste Mal sendet — beim LA66 heisst das: nach dem
naechsten AT+SENDB. Sofortige Zustellung gaebe es nur mit Class C, was am
Batteriebetrieb scheitert.

Der Fortschritt ist auf `crisis/status` nachlesbar.
"""
import json
import logging
import os
import sys
import time

import grpc
import paho.mqtt.client as mqtt
from chirpstack_api import api

BROKER = "127.0.0.1"
TOPIC = "crisis"
STATUS = "crisis/status"
FPORT = 21
# 51 Byte ist die kleinste Nutzlast in EU868 (DR0/SF12). Wer weiss, mit welcher
# Datenrate ein Geraet gerade unterwegs ist — also immer auf das Minimum stueckeln.
CHUNK = 49

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("crisis")


def token():
    with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
        for line in f:
            if line.startswith("CHIRPSTACK_TOKEN="):
                return line.strip().split("=", 1)[1]
    sys.exit("kein ChirpStack-Token gefunden")


chan = grpc.insecure_channel("127.0.0.1:8090")
AUTH = [("authorization", f"Bearer {token()}")]


def all_devices():
    """Jedes Geraet aus jeder Anwendung jedes Mandanten."""
    out = []
    ts = api.TenantServiceStub(chan)
    aps = api.ApplicationServiceStub(chan)
    ds = api.DeviceServiceStub(chan)
    for t in ts.List(api.ListTenantsRequest(limit=100), metadata=AUTH).result:
        for a in aps.List(api.ListApplicationsRequest(limit=100, tenant_id=t.id),
                          metadata=AUTH).result:
            for d in ds.List(api.ListDevicesRequest(limit=100, application_id=a.id),
                             metadata=AUTH).result:
                out.append((d.dev_eui, d.name))
    return out


def enqueue(dev_eui, payload):
    ds = api.DeviceServiceStub(chan)
    req = api.EnqueueDeviceQueueItemRequest()
    req.queue_item.dev_eui = dev_eui
    req.queue_item.f_port = FPORT
    req.queue_item.data = payload
    req.queue_item.confirmed = False
    return ds.Enqueue(req, metadata=AUTH).id


def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        log.error("Broker lehnt ab: %s", rc)
        return
    log.info("verbunden, lausche auf '%s'", TOPIC)
    client.subscribe(TOPIC, qos=1)
    client.publish(STATUS, json.dumps({"state": "online", "t": time.time()}),
                   retain=True)


def on_message(client, userdata, m):
    text = m.payload.decode("utf-8", "replace").strip()
    if not text:
        return
    data = text.encode("utf-8")
    parts = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)]

    try:
        devices = all_devices()
    except grpc.RpcError as e:
        log.error("Geraeteliste nicht abrufbar: %s", e.details())
        client.publish(STATUS, json.dumps({"state": "error", "error": str(e.details())}))
        return

    zugestellt = []
    for eui, name in devices:
        try:
            for i, part in enumerate(parts):
                # Gleicher Kopf wie beim Uplink: Teilnummer mit Endemarke.
                head = bytes([0x80 | i if i == len(parts) - 1 else i])
                enqueue(eui, head + part)
            zugestellt.append(name or eui)
        except grpc.RpcError as e:
            log.error("%s (%s): %s", name, eui, e.details())

    log.info("'%s' (%d Byte, %d Teile) eingereiht fuer: %s",
             text[:60], len(data), len(parts), ", ".join(zugestellt) or "niemanden")
    client.publish(STATUS, json.dumps({
        "state": "queued", "text": text, "parts": len(parts),
        "devices": zugestellt, "t": time.time(),
        "hinweis": "Zustellung beim naechsten Uplink des jeweiligen Geraets"}))


def main():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="crisis-bcast")
    c.on_connect = on_connect
    c.on_message = on_message
    c.will_set(STATUS, json.dumps({"state": "offline"}), retain=True)
    c.connect(BROKER, 1883, keepalive=60)
    c.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
