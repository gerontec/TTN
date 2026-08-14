#!/usr/bin/env python3
"""Bruecke TTN -> wagodb + Traccar.

Haengt sich per MQTT an die TTN-Anwendung `lenggries-sensors`, schreibt jeden
Uplink nach wagodb.lora_uplinks und meldet Positionen an Traccar weiter.

Dekodiert wird lokal, obwohl TTN das auch koennte: so landen die Werte auch
dann in der Datenbank, wenn am Formatter in der Konsole jemand schraubt, und
die Zeile bleibt vollstaendig, wenn TTN `decoded_payload` mal nicht mitschickt.
Die Logik ist 1:1 aus dem offiziellen Decoder des TTN-Device-Repository
(vendor/dragino/trackerd.js) uebernommen — inklusive der Eigenheit, dass MD in
Port 2/3 unverschoben (& 0xc0), in Port 8 dagegen verschoben (>> 6) ist.
"""
import base64
import json
import logging
import os
import ssl
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import pymysql
import requests

TTN_HOST = "eu1.cloud.thethings.network"
TTN_PORT = 8883
TRACCAR_OSMAND = "http://127.0.0.1:5055"
SOCKET = "/run/mysqld/mysqld.sock"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("lora_bridge")


def load_env(path):
    cfg = {}
    with open(os.path.expanduser(path)) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


TTN = load_env("~/.config/ttn/app-lenggries-sensors.key")
DB = load_env("~/.config/lora/db.env")
APP_ID = TTN["TTN_APP_ID"]


# --- Decoder (Portierung von trackerd.js) -----------------------------------
def _u32(b, i):
    return (b[i] << 24) | (b[i + 1] << 16) | (b[i + 2] << 8) | b[i + 3]


def _coord(b, i):
    """Latitude/Longitude sind vorzeichenbehaftet — in JS erledigt das der
    32-Bit-Shift von selbst, in Python muss man nachhelfen."""
    v = _u32(b, i)
    if v >= 0x80000000:
        v -= 0x100000000
    return v / 1000000


def _loc(lat, lon):
    if -190 < lat < 190 and -190 < lon < 190:
        if lat != 0 and lon != 0:
            return f"{lat},{lon}"
        return None
    return "invalid value"


def _gps_common(b):
    """Der in Port 2/3 identische Block."""
    lat, lon = _coord(b, 0), _coord(b, 4)
    return {
        "Location": _loc(lat, lon),
        "Latitude": lat,
        "Longitude": lon,
        "BatV": (((b[8] & 0x3F) << 8) | b[9]) / 1000,
        "ALARM_status": "TRUE" if b[8] & 0x40 else "FALSE",
        "MD": b[10] & 0xC0,
        "LON": "ON" if b[10] & 0x20 else "OFF",
        "Transport": "MOVE" if b[10] & 0x10 else "STILL",
    }


FREQ_BANDS = {
    0x01: "EU868", 0x02: "US915", 0x03: "IN865", 0x04: "AU915", 0x05: "KZ865",
    0x06: "RU864", 0x07: "AS923", 0x08: "AS923_1", 0x09: "AS923_2",
    0x0A: "AS923_3", 0x0B: "CN470", 0x0C: "EU433", 0x0D: "KR920", 0x0E: "MA869",
}


def decode_trackerd(port, b):
    try:
        if port in (2, 3):
            d = _gps_common(b)
            # Temperatur/Feuchte haengen hinten dran, aber nur in den laengeren
            # Rahmen — im reinen GPS-Modus ist nach Byte 10 Schluss.
            if len(b) >= 15:
                d["Hum"] = ((b[11] << 8) | b[12]) / 10
                d["Tem"] = ((b[13] << 8) | b[14]) / 10
            return d
        if port == 4:
            lat, lon = _coord(b, 0), _coord(b, 4)
            return {
                "Location": _loc(lat, lon), "Latitude": lat, "Longitude": lon,
                "Date": f"{(b[8] << 8) | b[9]}:{b[10]}:{b[11]}",
                "Time": f"{b[12]}:{b[13]}:{b[14]}",
            }
        if port == 5:
            return {
                "BatV": ((b[5] << 8) | b[6]) / 1000,
                "SENSOR_MODEL": "TrackerD" if b[0] == 0x13 else "NULL",
                "FIRMWARE_VERSION": f"{b[1] & 0x0F}.{(b[2] >> 4) & 0x0F}.{b[2] & 0x0F}",
                "FREQUENCY_BAND": FREQ_BANDS.get(b[3]),
                "SUB_BAND": "NULL" if b[4] == 0xFF else b[4],
                "SMODE": {1: "GPS", 2: "BLE", 3: "BLE+GPS Hybrid"}.get(
                    (b[7] >> 6) & 0x3F, "Spots" if b[8] & 0x01 else None),
                "GPS_M0D": (b[7] >> 4) & 0x03,
                "BLE_MD": b[7] & 0x0F,
                "LON": "ON" if (b[8] >> 1) & 0x01 else "OFF",
                "Intwk": b[8] & 0x01,
            }
        if port == 6:
            d = {
                "UUID": "".join(f"{x:x}" for x in b[0:16]),
                "POWER": b[15],
                "MAJOR": (b[16] << 8) | b[17],
                "MINOR": (b[18] << 8) | b[19],
                "RSSI": b[23] - 256 if b[23] > 127 else b[23],
                "ALARM_status": "TRUE" if b[24] & 0x40 else "FALSE",
                "BatV": (((b[24] & 0x3F) << 8) | b[25]) / 1000,
                "MD": (b[26] & 0xC0) >> 6,
                "LON": "ON" if b[26] & 0x20 else "OFF",
            }
            if len(b) >= 31:
                d["Hum"] = ((b[27] << 8) | b[28]) / 10
                d["Tem"] = ((b[29] << 8) | b[30]) / 10
            return d
        if port == 7:
            return {
                "BatV": (((b[0] & 0x3F) << 8) | b[1]) / 1000,
                "ALARM_status": "TRUE" if b[0] & 0x40 else "FALSE",
                "MD": b[2] & 0xC0,
                "LON": "ON" if b[2] & 0x20 else "OFF",
            }
        if port == 8:
            return {
                "WIFISSID": "".join(chr(x) for x in b[0:6]),
                "RSSI": b[6] - 256 if b[6] > 127 else b[6],
                "ALARM_status": "TRUE" if b[7] & 0x40 else "FALSE",
                "BatV": (((b[7] & 0x3F) << 8) | b[8]) / 1000,
                "MD": (b[9] & 0xC0) >> 6,
                "LON": "ON" if b[9] & 0x20 else "OFF",
            }
    except IndexError:
        log.warning("Payload zu kurz fuer Port %s: %s", port, bytes(b).hex())
    return None


# Der Decoder gehoert zum Geraetetyp, nicht zum fPort — sonst wuerde die
# TrackerD-Logik auch ueber Payloads anderer Knoten laufen und Unsinn liefern.
# Der LA66 steht bewusst nicht hier: sein Payload bestimmt der Host, der ihn
# per AT+SENDB fuettert, es gibt also keine feste Struktur zu dekodieren.
DECODERS = {
    "A840414F1188076C": decode_trackerd,   # Dragino TrackerD
}


def decode(dev_eui, port, b):
    fn = DECODERS.get((dev_eui or "").upper())
    return fn(port, b) if fn else None


# --- Datenbank ---------------------------------------------------------------
def db_connect():
    return pymysql.connect(
        unix_socket=SOCKET, user=DB["DB_USER"], password=DB["DB_PASSWORD"],
        db=DB["DB_NAME"], charset="utf8mb4", autocommit=True)


def best_gateway(uplink):
    """Ein Uplink kommt ueber mehrere Gateways; fuer die Funkspalten nehmen wir
    das mit dem staerksten Signal."""
    gws = uplink.get("rx_metadata") or []
    if not gws:
        return {}
    return max(gws, key=lambda g: g.get("rssi", -999))


def parse_ts(s):
    if not s:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    s = s.replace("Z", "+00:00")
    # TTN liefert Nanosekunden, fromisoformat vertraegt hoechstens Mikrosekunden.
    if "." in s:
        head, rest = s.split(".", 1)
        frac, _, tail = rest.partition("+")
        s = f"{head}.{frac[:6]}+{tail}" if tail else f"{head}.{frac[:6]}"
    return datetime.fromisoformat(s).astimezone(timezone.utc).replace(tzinfo=None)


def store_uplink(conn, msg):
    up = msg.get("uplink_message", {})
    ids = msg.get("end_device_ids", {})
    gw = best_gateway(up)
    settings = up.get("settings", {})
    lora = (settings.get("data_rate") or {}).get("lora", {})

    raw = base64.b64decode(up["frm_payload"]) if up.get("frm_payload") else b""
    port = up.get("f_port")
    dev_eui = (ids.get("dev_eui") or "").upper()
    dec = decode(dev_eui, port, raw) if raw and port is not None else None
    # Falls TTN selbst dekodiert hat und wir nicht: dessen Ergebnis nehmen.
    if dec is None:
        dec = up.get("decoded_payload")

    d = dec or {}
    row = (
        parse_ts(msg.get("received_at")),
        ids.get("application_ids", {}).get("application_id", APP_ID),
        ids.get("device_id"), (ids.get("dev_eui") or "").upper(),
        # TTN laesst Nullwerte im JSON weg, f_cnt=0 kommt also gar nicht an.
        # Als NULL gespeichert wuerde der UNIQUE-Index nicht greifen (NULL ist
        # in MySQL nie gleich NULL), und jeder Neustart schriebe den ersten
        # Uplink nach einem Join erneut.
        port, up.get("f_cnt") or 0, raw.hex().upper() or None,
        d.get("Latitude"), d.get("Longitude"), d.get("BatV"),
        1 if d.get("ALARM_status") == "TRUE" else (0 if "ALARM_status" in d else None),
        d.get("MD"), 1 if d.get("LON") == "ON" else (0 if "LON" in d else None),
        d.get("Transport"), d.get("Tem"), d.get("Hum"),
        d.get("FIRMWARE_VERSION"), d.get("FREQUENCY_BAND"), d.get("SMODE"),
        d.get("WIFISSID"), d.get("UUID"),
        (gw.get("gateway_ids") or {}).get("eui"), gw.get("rssi"), gw.get("snr"),
        lora.get("spreading_factor"), lora.get("bandwidth"), settings.get("frequency"),
        (float(up["consumed_airtime"][:-1]) * 1000) if up.get("consumed_airtime") else None,
        json.dumps(dec) if dec else None, json.dumps(msg),
    )
    with conn.cursor() as cur:
        cur.execute("""
            INSERT IGNORE INTO lora_uplinks
              (received_at, app_id, device_id, dev_eui, f_port, f_cnt, payload_hex,
               latitude, longitude, battery_v, alarm, md, led_on, transport,
               temperature, humidity, firmware, freq_band, smode, wifi_ssid,
               beacon_uuid, gateway_eui, rssi, snr, spreading_factor, bandwidth,
               frequency, airtime_ms, decoded, raw)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", row)
    return d, ids, gw


def store_join(conn, msg):
    ja = msg.get("join_accept", {})
    ids = msg.get("end_device_ids", {})
    gw = best_gateway(ja)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO lora_joins
              (received_at, app_id, device_id, dev_eui, join_eui, dev_addr,
               gateway_eui, rssi, snr, raw)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
            parse_ts(msg.get("received_at")),
            ids.get("application_ids", {}).get("application_id", APP_ID),
            ids.get("device_id"), (ids.get("dev_eui") or "").upper(),
            (ids.get("join_eui") or "").upper(), (ids.get("dev_addr") or "").upper(),
            (gw.get("gateway_ids") or {}).get("eui"), gw.get("rssi"), gw.get("snr"),
            json.dumps(msg)))


# --- Traccar -----------------------------------------------------------------
def to_traccar(ids, d, gw, when):
    lat, lon = d.get("Latitude"), d.get("Longitude")
    if lat is None or lon is None or (lat == 0 and lon == 0):
        return  # kein Fix — nichts zu melden
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        log.warning("Position ausserhalb des Wertebereichs: %s/%s", lat, lon)
        return
    p = {
        "id": (ids.get("dev_eui") or "").lower(),
        "lat": lat, "lon": lon,
        "timestamp": int(when.replace(tzinfo=timezone.utc).timestamp()),
    }
    if d.get("BatV") is not None:
        # Traccar erwartet unter `batt` Prozent. Der TrackerD meldet Volt, also
        # linear ueber den nutzbaren Bereich einer 1S-Li-Ion-Zelle geschaetzt —
        # der genaue Wert steht als `voltage` daneben.
        p["batt"] = round(max(0, min(100, (d["BatV"] - 3.0) / 1.2 * 100)), 1)
        p["voltage"] = d["BatV"]
    if d.get("ALARM_status") == "TRUE":
        p["alarm"] = "sos"
    if d.get("Transport"):
        p["motion"] = "true" if d["Transport"] == "MOVE" else "false"
    if d.get("Tem") is not None:
        p["temp1"] = d["Tem"]
    if gw.get("rssi") is not None:
        p["rssi"] = gw["rssi"]
    r = requests.post(TRACCAR_OSMAND, params=p, timeout=10)
    if r.status_code >= 300:
        log.error("Traccar antwortet %s: %s", r.status_code, r.text[:200])
    else:
        log.info("Traccar: %s -> %.6f/%.6f", p["id"], lat, lon)


# --- MQTT --------------------------------------------------------------------
def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        log.error("MQTT-Verbindung abgelehnt: %s", rc)
        return
    log.info("mit TTN verbunden, abonniere Anwendung %s", APP_ID)
    client.subscribe(f"v3/{APP_ID}@ttn/devices/+/up", qos=1)
    client.subscribe(f"v3/{APP_ID}@ttn/devices/+/join", qos=1)


def on_message(client, userdata, m):
    try:
        msg = json.loads(m.payload)
    except ValueError:
        log.error("kein JSON auf %s", m.topic)
        return
    conn = userdata["db"]
    try:
        conn.ping(reconnect=True)
        if m.topic.endswith("/join"):
            store_join(conn, msg)
            log.info("Join: %s", msg.get("end_device_ids", {}).get("device_id"))
            return
        d, ids, gw = store_uplink(conn, msg)
        log.info("Uplink %s Port %s fcnt %s: %s",
                 ids.get("device_id"),
                 msg.get("uplink_message", {}).get("f_port"),
                 msg.get("uplink_message", {}).get("f_cnt"),
                 json.dumps(d, ensure_ascii=False)[:200])
        to_traccar(ids, d, gw, parse_ts(msg.get("received_at")))
    except Exception:
        log.exception("Nachricht auf %s nicht verarbeitet", m.topic)


def main():
    conn = db_connect()
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    userdata={"db": conn}, client_id="heissa-lora-bridge")
    c.username_pw_set(f"{APP_ID}@ttn", TTN["TTN_APP_KEY"])
    c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(TTN_HOST, TTN_PORT, keepalive=60)
    c.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
