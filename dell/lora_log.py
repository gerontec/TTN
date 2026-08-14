#!/usr/bin/env python3
"""Schreibt alles, was von LoRaWAN-Geraeten ueber den Broker kommt, nach wagodb.

Rohspeicher, kein Filter: jedes Ereignis auf `application/#` landet als Zeile
in `loradevice` — up, join, ack, txack, status, log. Was sich sinnvoll
herausziehen laesst, kommt in eigene Spalten, der vollstaendige Rahmen bleibt
zusaetzlich als JSON in `raw`.

Der Sinn der Trennung: der Rundruf entscheidet spaeter aus dieser Tabelle
heraus, was gesendet wird. Wer erst filtert und dann speichert, kann eine
Filterregel nie an vergangenen Daten pruefen.
"""
import base64
import json
import logging
import os
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt
import pymysql

# Vorgabe 127.0.0.1, weil der Dienst auf dem dell laeuft. Von woanders aus
# zeigt man mit LORA_BROKER/LORA_DB_HOST auf den dell (192.168.5.23).
BROKER = os.environ.get("LORA_BROKER", "127.0.0.1")
DB = dict(host=os.environ.get("LORA_DB_HOST", "127.0.0.1"),
          user="gh", password="a12345", database="wagodb",
          charset="utf8mb4", autocommit=True, connect_timeout=5)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("lora_log")

SQL = """INSERT INTO loradevice
 (ts, dev_time, event, topic, dev_eui, dev_name, application, f_port, f_cnt,
  confirmed, dr, frequency, rssi, snr, gateway_id, payload_hex, decoded, raw)
 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""

conn = None


def db():
    """Verbindung, die einen Neustart der Datenbank ueberlebt."""
    global conn
    if conn is not None:
        try:
            conn.ping(reconnect=True)
            return conn
        except pymysql.Error:
            conn = None
    conn = pymysql.connect(**DB)
    return conn


def zeit(s):
    """ChirpStack liefert ISO-8601 mit Zone; die Tabelle fuehrt Ortszeit."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def zerlege(topic, msg):
    """Die Felder, die ueber alle Ereignisarten hinweg gleich heissen."""
    teile = topic.split("/")
    event = teile[-1] if len(teile) >= 6 else "?"
    info = msg.get("deviceInfo") or {}
    rx = (msg.get("rxInfo") or [{}])[0]
    tx = msg.get("txInfo") or {}
    raw = base64.b64decode(msg.get("data", "") or "") if msg.get("data") else b""
    obj = msg.get("object")

    return (
        datetime.now(),
        zeit(msg.get("time")),
        event,
        topic,
        (info.get("devEui") or None),
        (info.get("deviceName") or None),
        (info.get("applicationName") or None),
        msg.get("fPort"),
        msg.get("fCnt"),
        1 if msg.get("confirmed") else (0 if "confirmed" in msg else None),
        msg.get("dr"),
        tx.get("frequency"),
        rx.get("rssi"),
        rx.get("snr"),
        (rx.get("gatewayId") or None),
        raw.hex() if raw else None,
        json.dumps(obj, ensure_ascii=False) if obj else None,
        json.dumps(msg, ensure_ascii=False),
    )


def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        log.error("Broker lehnt ab: %s", rc)
        return
    log.info("verbunden, schreibe alles von application/# nach wagodb.loradevice")
    client.subscribe("application/#", qos=1)


def on_message(client, userdata, m):
    try:
        msg = json.loads(m.payload)
    except ValueError:
        return
    if not isinstance(msg, dict):
        return

    werte = zerlege(m.topic, msg)
    for versuch in (1, 2):
        try:
            with db().cursor() as cur:
                cur.execute(SQL, werte)
            log.info("%s %s fPort %s fCnt %s", werte[2], werte[5] or werte[4],
                     werte[7], werte[8])
            return
        except pymysql.Error as e:
            global conn
            conn = None
            if versuch == 2:
                # Lieber laut scheitern als still verlieren: die Zeile steht
                # dann wenigstens im Journal.
                log.error("nicht gespeichert (%s): %s", e, werte[3])
            else:
                time.sleep(0.5)


def main():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="lora-log")
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(BROKER, 1883, keepalive=60)
    c.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
