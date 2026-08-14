#!/usr/bin/env python3
"""Erzeugt den Krisen-Rundruf aus dem Rohspeicher — Alarm und Position, sonst nichts.

Die Trennung ist der Zweck: `lora_log.py` speichert alles ungefiltert nach
`wagodb.loradevice`, hier wird nur ausgewaehlt. Deshalb laesst sich eine
Filterregel gegen die Vergangenheit pruefen, bevor sie scharf geschaltet wird:

    ./lora_bcast.py --trocken --seit 0

zeigt, was fuer den gesamten bisherigen Bestand hinausgegangen waere, ohne ein
einziges Byte zu senden.

**Was hinausgeht:** der Alarmknopf und die GPS-Position. Temperatur, Feuchte,
Batterie und Bewegungszustand bleiben in der Datenbank — im Krisenfall zaehlt,
wo jemand ist und ob er den Knopf gedrueckt hat, und jedes weitere Byte kostet
Sendezeit bei jedem Empfaenger.

**Wann nichts hinausgeht:** kein Alarm und kein Satellitenfix. Eine Meldung
"TrackerD kein Fix" bindet Sendezeit, ohne irgendetwas mitzuteilen.
"""
import argparse
import json
import logging
import os
import sys
import time

import paho.mqtt.client as mqtt
import pymysql

# Vorgabe 127.0.0.1, weil der Dienst auf dem dell laeuft — dort stehen Broker
# und Datenbank lokal. Von woanders aus zeigt man mit --db-host/--broker
# (oder LORA_DB_HOST/LORA_BROKER) auf den dell.
DELL = "192.168.5.23"
BROKER = os.environ.get("LORA_BROKER", "127.0.0.1")
DB_HOST = os.environ.get("LORA_DB_HOST", "127.0.0.1")
TOPIC = "crisis"
DEV_EUI = "a840414f1188076c"
DB = dict(user="gh", password="a12345", database="wagodb",
          charset="utf8mb4", autocommit=True, cursorclass=pymysql.cursors.DictCursor)
STAND = os.path.expanduser("~/.local/state/lora_bcast.id")
TAKT = 5

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("lora_bcast")


def verbinde(host, aufgeben):
    """Wartet, bis die Datenbank da ist — statt mit einem Traceback abzubrechen.

    Ein Dienst startet mit der Maschine und darf nicht daran scheitern, dass
    MariaDB zwei Sekunden spaeter oben ist. Von Hand gestartet nuetzt eine
    Endlosschleife dagegen nichts, deshalb `aufgeben`."""
    versuch = 0
    while True:
        versuch += 1
        try:
            return pymysql.connect(host=host, connect_timeout=5, **DB)
        except pymysql.Error as e:
            if aufgeben and versuch >= 2:
                log.error("wagodb auf %s nicht erreichbar: %s", host, e.args[-1])
                if host in ("127.0.0.1", "localhost"):
                    log.error("laeuft das hier ueberhaupt? Von einem anderen "
                              "Rechner aus: --db-host %s", DELL)
                log.error("zum Mitlesen und Senden von Hand: crisis_client.py")
                sys.exit(1)
            log.warning("warte auf wagodb auf %s (%s)", host, e.args[-1])
            time.sleep(5)


def satz(decoded, rssi):
    """Alarm, Position und Empfangspegel — oder None, wenn Alarm und Fix fehlen.

    Der RSSI ist der des Uplinks am Gateway. Er steht mit im Rundruf, damit die
    Empfaenger einschaetzen koennen, wie belastbar die Meldung ist: −90 dBm ist
    solide, jenseits von −115 dBm reisst die Verbindung gleich ab, und dann ist
    das Ausbleiben der naechsten Meldung eine Funkluecke und kein Entwarnung."""
    if not decoded:
        return None
    try:
        o = json.loads(decoded)
    except ValueError:
        # Ein unlesbarer Datensatz darf den Rundruf nicht anhalten.
        return None
    if not isinstance(o, dict):
        return None
    alarm = str(o.get("ALARM_status", "")).upper() in ("TRUE", "1", "ALARM")
    lat, lon = o.get("Latitude"), o.get("Longitude")
    fix = (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
           and (lat or lon))

    if not alarm and not fix:
        return None
    teile = ["TrackerD"]
    if alarm:
        teile.append("ALARM")
    if fix:
        teile.append(f"{lat:.5f},{lon:.5f}")
    elif lat is not None:
        # "kein Fix" nur, wenn der Rahmen ueberhaupt eine Position fuehrt und
        # sie 0/0 ist. Auf fPort 7 (nur Alarm + Batterie) steht gar keine
        # drin — das ist kein fehlender Satellitenempfang und darf auch nicht
        # so aussehen.
        teile.append("kein Fix")
    if rssi is not None:
        teile.append(f"{int(rssi)}dBm")
    return " ".join(teile)


def stand_lesen(vorgabe):
    if vorgabe is not None:
        return vorgabe
    try:
        with open(STAND) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def stand_schreiben(i):
    os.makedirs(os.path.dirname(STAND), exist_ok=True)
    with open(STAND, "w") as f:
        f.write(str(i))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--trocken", action="store_true",
                   help="nur zeigen, was hinausginge — nichts senden, nichts merken")
    p.add_argument("--seit", type=int, help="ab dieser loradevice.id beginnen")
    p.add_argument("--db-host", default=DB_HOST,
                   help=f"MariaDB (Vorgabe {DB_HOST}, auf dem dell {DELL})")
    p.add_argument("--broker", default=BROKER, help=f"MQTT (Vorgabe {BROKER})")
    p.add_argument("--warten", action="store_true",
                   help="auf die Datenbank warten statt abzubrechen (fuer den Dienst)")
    a = p.parse_args()

    # Von Hand aufgerufen will man einen Fehler sehen, als Dienst warten.
    # Ausdruecklich per Schalter statt ueber isatty(): in einer Pipe oder unter
    # nohup ist das Terminal weg, und dann haengt der Aufruf still.
    db = verbinde(a.db_host, aufgeben=not a.warten)
    letzte = stand_lesen(a.seit)
    if letzte is None:
        with db.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM loradevice")
            letzte = cur.fetchone()["m"]
        log.info("kein Stand gemerkt, beginne bei id %d", letzte)

    c = None
    if not a.trocken:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="lora-bcast")
        try:
            c.connect(a.broker, 1883, keepalive=60)
        except OSError as e:
            log.error("Broker auf %s nicht erreichbar: %s", a.broker, e)
            sys.exit(1)
        # Der Client verbindet sich nach einem Abriss selbst wieder; die
        # Veroeffentlichungen dazwischen puffert paho.
        c.loop_start()
        log.info("Rundruf aus loradevice ab id %d", letzte)

    while True:
        try:
            db.ping(reconnect=True)
        except pymysql.Error as e:
            log.warning("Datenbank weg (%s), verbinde neu", e.args[-1])
            db = verbinde(a.db_host, aufgeben=False)
        try:
            with db.cursor() as cur:
                cur.execute(
                    "SELECT id, ts, decoded, rssi FROM loradevice "
                    "WHERE id > %s AND event = 'up' AND dev_eui = %s "
                    "ORDER BY id", (letzte, DEV_EUI))
                zeilen = cur.fetchall()
        except pymysql.Error as e:
            # `letzte` bleibt stehen, der naechste Durchlauf holt dieselben
            # Zeilen — nichts geht verloren, nichts geht doppelt raus.
            log.warning("Abfrage fehlgeschlagen (%s), neuer Versuch", e.args[-1])
            db = verbinde(a.db_host, aufgeben=False)
            time.sleep(TAKT)
            continue

        for z in zeilen:
            letzte = z["id"]
            text = satz(z["decoded"], z["rssi"])
            if text is None:
                continue
            if a.trocken:
                print(f"{z['ts']}  id {z['id']:<6} -> {text}")
            else:
                c.publish(TOPIC, text, qos=1)
                log.info("-> crisis: %s (id %d)", text, z["id"])

        if a.trocken:
            return          # ein Durchlauf reicht, es wird ja nichts gesendet
        stand_schreiben(letzte)
        time.sleep(TAKT)


if __name__ == "__main__":
    main()
