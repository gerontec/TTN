#!/usr/bin/env python3
"""Schreibt, was ueber TTN hereinkommt, in dieselbe Tabelle wie der lokale Weg.

Seit der Paket-Multiplexer auf dem dell den Gateway-Strom auch an
`eu1.cloud.thethings.network` weiterreicht, hoert TTN dieselben Uplinks wie der
lokale ChirpStack. Was TTN daraus macht, blieb bisher unsichtbar: TTS hat eine
eigene Anwendung, einen eigenen Broker und eine eigene Sicht darauf, welches
Gateway einen Rahmen aufgenommen hat.

Genau das ist der Grund fuer dieses Skript. Der zweite Weg ist nicht nur
Redundanz, er beantwortet eine Frage, die der lokale Weg nicht beantworten
kann: **welches Gateway hat den Uplink gehoert?** TTS liefert in `rx_metadata`
jede Empfangsstelle mit RSSI und SNR — auch fremde, etwa das Gateway am
Lenggrieser Gymnasium (`B827EBFFFE3CEC15`). Damit laesst sich die Abdeckung
messen, statt sie zu schaetzen.

Geschrieben wird in `loradevice`, dieselben Spalten wie bei `lora_log.py`.
Auseinanderhalten lassen sich die beiden Wege an zwei Stellen: `topic` beginnt
bei TTS mit `v3/`, und `application` traegt das Praefix `ttn:`. Ein Geraet, das
in beiden Netzen eingetragen ist, erzeugt je Uplink also **zwei** Zeilen — eine
je Netz. Das ist Absicht: nur so ist vergleichbar, was wer gehoert hat.

    ~/.config/ttn/lenggries.key   TTN_KEY=NNSXS....
"""
import base64
import json
import logging
import os
import re
import ssl
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt
import pymysql

HOST = os.environ.get("TTN_HOST", "eu1.cloud.thethings.network")
APP = os.environ.get("TTN_APP", "lenggries-sensors")
TENANT = os.environ.get("TTN_TENANT", "ttn")
KEYFILE = os.path.expanduser("~/.config/ttn/lenggries.key")

DB = dict(host=os.environ.get("LORA_DB_HOST", "127.0.0.1"),
          user="gh", password="<ENTFERNT>", database="wagodb",
          charset="utf8mb4", autocommit=True, connect_timeout=5)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("ttn_log")

SQL = """INSERT INTO loradevice
 (ts, dev_time, event, topic, dev_eui, dev_name, application, f_port, f_cnt,
  confirmed, dr, frequency, rssi, snr, gateway_id, payload_hex, decoded, raw)
 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""

conn = None


def key():
    """Wie in ttn/ttn_register.py: der Key steht als TTN_KEY=NNSXS... in der
    Datei, also nicht am Wortanfang suchen."""
    try:
        with open(KEYFILE) as f:
            m = re.search(r"NNSXS\.[A-Z0-9]+\.[A-Z0-9]+", f.read())
    except OSError as e:
        sys.exit(f"kein API-Key lesbar ({KEYFILE}): {e}")
    if not m:
        sys.exit(f"kein API-Key in {KEYFILE} gefunden")
    return m.group(0)


def db():
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
    """TTS liefert ISO-8601 mit Zone; die Tabelle fuehrt Ortszeit."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(
            s.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


# EU868: TTS nennt Spreizfaktor und Bandbreite, ChirpStack den DR-Index.
# Damit beide Wege in derselben Spalte vergleichbar sind, wird umgerechnet.
def datenrate(lora):
    if not lora:
        return None
    sf = lora.get("spreading_factor")
    bw = lora.get("bandwidth")
    if sf is None:
        return None
    if bw == 250000:
        return 6 if sf == 7 else None
    return {12: 0, 11: 1, 10: 2, 9: 3, 8: 4, 7: 5}.get(sf)


def beste(rx):
    """Die Empfangsstelle mit dem staerksten Pegel bestimmt die Spalten; alle
    uebrigen bleiben im JSON der raw-Spalte erhalten."""
    if not rx:
        return {}
    return max(rx, key=lambda m: m.get("rssi", -999))


def zerlege(topic, msg):
    teile = topic.split("/")
    event = teile[-1] if len(teile) >= 4 else "?"
    ids = msg.get("end_device_ids") or {}
    up = msg.get("uplink_message") or {}
    settings = up.get("settings") or {}
    rx = beste(up.get("rx_metadata") or [])
    gw = (rx.get("gateway_ids") or {})
    roh = base64.b64decode(up.get("frm_payload", "") or "") if up.get("frm_payload") else b""
    obj = up.get("decoded_payload")
    freq = settings.get("frequency")

    return (
        datetime.now(),
        zeit(msg.get("received_at") or up.get("received_at")),
        event,
        topic,
        (ids.get("dev_eui") or "").lower() or None,
        ids.get("device_id") or None,
        "ttn:" + ((ids.get("application_ids") or {}).get("application_id") or APP),
        up.get("f_port"),
        up.get("f_cnt"),
        1 if up.get("confirmed") else (0 if up else None),
        datenrate((settings.get("data_rate") or {}).get("lora")),
        int(freq) if freq else None,
        rx.get("rssi"),
        rx.get("snr"),
        # Die Gateway-EUI, nicht die TTS-Kennung: nur so ist ein fremdes
        # Gateway mit dem zu vergleichen, was der lokale Weg meldet.
        (gw.get("eui") or gw.get("gateway_id") or None),
        roh.hex() if roh else None,
        json.dumps(obj, ensure_ascii=False) if obj else None,
        json.dumps(msg, ensure_ascii=False),
    )


def schreibe(werte, was):
    for versuch in (1, 2):
        try:
            with db().cursor() as cur:
                cur.execute(SQL, werte)
            log.info("%s", was)
            return
        except pymysql.Error as e:
            global conn
            conn = None
            if versuch == 2:
                log.error("nicht gespeichert (%s): %s", e, was)
            else:
                time.sleep(0.5)


def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        log.error("TTS lehnt ab: %s (Key falsch oder Rechte fehlen?)", rc)
        return
    log.info("verbunden mit %s, Anwendung %s", HOST, APP)
    client.subscribe("v3/+/devices/+/#", qos=0)


def on_message(client, userdata, m):
    try:
        msg = json.loads(m.payload)
    except ValueError:
        return
    if not isinstance(msg, dict):
        return
    werte = zerlege(m.topic, msg)
    schreibe(werte, f"ttn {werte[2]} {werte[5] or werte[4]} "
                    f"fPort {werte[7]} fCnt {werte[8]} via {werte[14]}")


def main():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ttn-log")
    c.username_pw_set(f"{APP}@{TENANT}", key())
    c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(HOST, 8883, keepalive=60)
    c.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
