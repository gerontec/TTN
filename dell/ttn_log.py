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
Auseinandergehalten werden die beiden Wege ueber die Spalte `source`: `TTN`
hier, `lokal` in `lora_log.py`. Ein Geraet, das in beiden Netzen eingetragen
ist, erzeugt je Uplink **zwei** Zeilen — eine je Netz. Das ist Absicht: nur so
ist vergleichbar, was wer gehoert hat.

Zusaetzlich geht jede Zeile nach heissa.de (MariaDB im Wireguard-Netz),
solang der Weg traegt — der dortige Report soll nicht auf den naechsten
Sync-Lauf warten muessen.

    ~/.config/ttn/lenggries.key   TTN_KEY=NNSXS....
"""
import base64
import json
import logging
import os
import re
import ssl
import sys
import urllib.request
import time
from datetime import datetime

import paho.mqtt.client as mqtt
import pymysql

HOST = os.environ.get("TTN_HOST", "eu1.cloud.thethings.network")
TENANT = os.environ.get("TTN_TENANT", "ttn")
KEYFILE = os.path.expanduser("~/.config/ttn/lenggries.key")
# APP wird aus dem Schluessel selbst abgeleitet (siehe anwendung()), damit ein
# neuer Schluessel fuer eine andere Anwendung nicht stillschweigend am falschen
# Broker landet. TTN_APP in der Umgebung geht vor.

DB = dict(host=os.environ.get("LORA_DB_HOST", "127.0.0.1"),
          user="gh", password="a12345", database="wagodb",
          charset="utf8mb4", autocommit=True, connect_timeout=5)

# Zweitspeicher auf heissa.de, erreichbar ueber das Wireguard-Netz. Dieser Weg
# ist optional: Ohne VPN/Internet darf er den hiesigen Rohspeicher nie stoeren,
# deshalb gibt db_remote() None zurueck statt einer Exception, und Fehler
# kommen nur alle zehn Minuten ins Journal. LORA_DB_REMOTE="" schaltet ihn ab.
REMOTE_HOST = os.environ.get("LORA_DB_REMOTE", "10.9.0.10")
DB_REMOTE = dict(host=REMOTE_HOST, user="gh", password="a12345",
                 database="wagodb", charset="utf8mb4", autocommit=True,
                 connect_timeout=5)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("ttn_log")

SQL = """INSERT INTO loradevice
 (ts, dev_time, event, source, topic, dev_eui, dev_name, application, f_port,
  f_cnt, confirmed, dr, frequency, rssi, snr, gateway_id, gw_lat, gw_lon,
  payload_hex, decoded, raw)
 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""

SOURCE = "TTN"

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


def anwendung(api_key):
    """Zu welcher Anwendung der Schluessel gehoert, sagt TTS selbst. Ein
    fest eingetragener Name geht sonst genau dann daneben, wenn jemand einen
    Schluessel fuer eine andere Anwendung hinterlegt -- der Broker antwortet
    dann mit `Not authorized`, ohne zu verraten warum."""
    if os.environ.get("TTN_APP"):
        return os.environ["TTN_APP"]
    req = urllib.request.Request(f"https://{HOST}/api/v3/auth_info",
                                 headers={"Authorization": "Bearer " + api_key})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.load(r)
    app = (((d.get("api_key") or {}).get("entity_ids") or {})
           .get("application_ids") or {}).get("application_id")
    if not app:
        sys.exit("Der Schluessel gehoert zu keiner Anwendung "
                 "(Gateway-Schluessel? Der kann keine Anwendungsdaten lesen.)")
    return app


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


conn_remote = None
_remote_warnung = 0.0


def remote_warnen(text):
    """Ohne Internet scheitert der Zweitweg mit jeder Nachricht — das Journal
    liefe sofort voll. Deshalb hoechstens alle zehn Minuten eine Meldung."""
    global _remote_warnung
    jetzt = time.time()
    if jetzt >= _remote_warnung:
        log.warning("Zweitspeicher (heissa.de) nicht erreichbar: %s", text)
        _remote_warnung = jetzt + 600


def db_remote():
    global conn_remote
    if not REMOTE_HOST:
        return None
    if conn_remote is not None:
        try:
            conn_remote.ping(reconnect=True)
            return conn_remote
        except pymysql.Error:
            conn_remote = None
    try:
        conn_remote = pymysql.connect(**DB_REMOTE)
    except pymysql.Error as e:
        remote_warnen(str(e))
        return None
    return conn_remote


def schreibe_remote(werte):
    verbindung = db_remote()
    if verbindung is None:
        return
    try:
        with verbindung.cursor() as cur:
            cur.execute(SQL, werte)
    except pymysql.Error as e:
        global conn_remote
        conn_remote = None
        remote_warnen(str(e))


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
    ort = rx.get("location") or {}
    roh = base64.b64decode(up.get("frm_payload", "") or "") if up.get("frm_payload") else b""
    obj = up.get("decoded_payload")
    freq = settings.get("frequency")

    return (
        datetime.now(),
        zeit(msg.get("received_at") or up.get("received_at")),
        event,
        SOURCE,
        topic,
        (ids.get("dev_eui") or "").lower() or None,
        ids.get("device_id") or None,
        (ids.get("application_ids") or {}).get("application_id"),
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
        # Position desselben Gateways (SOURCE_REGISTRY oder SOURCE_GPS);
        # fremde Gateways ohne Freigabe bleiben NULL.
        ort.get("latitude"), ort.get("longitude"),
        roh.hex() if roh else None,
        json.dumps(obj, ensure_ascii=False) if obj else None,
        json.dumps(msg, ensure_ascii=False),
    )


def schreibe(werte, was):
    for versuch in (1, 2):
        try:
            with db().cursor() as cur:
                cur.execute(SQL, werte)
            break
        except pymysql.Error as e:
            global conn
            conn = None
            if versuch == 2:
                log.error("nicht gespeichert (%s): %s", e, was)
                return
            time.sleep(0.5)
    log.info("%s", was)
    schreibe_remote(werte)


def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        log.error("TTS lehnt ab: %s (Key falsch oder Rechte fehlen?)", rc)
        return
    log.info("verbunden mit %s, Anwendung %s", HOST, userdata["app"])
    client.subscribe("v3/+/devices/+/#", qos=0)


def on_message(client, userdata, m):
    try:
        msg = json.loads(m.payload)
    except ValueError:
        return
    if not isinstance(msg, dict):
        return
    werte = zerlege(m.topic, msg)
    schreibe(werte, f"ttn {werte[2]} {werte[6] or werte[5]} "
                    f"fPort {werte[8]} fCnt {werte[9]} via {werte[15]}")


def main():
    api_key = key()
    app = anwendung(api_key)
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ttn-log",
                    userdata={"app": app})
    c.username_pw_set(f"{app}@{TENANT}", api_key)
    c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(HOST, 8883, keepalive=60)
    c.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
