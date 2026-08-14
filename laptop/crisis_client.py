#!/usr/bin/env python3
"""Krisenkanal-Terminal fuer den Arbeitsplatz.

Ein einziges Skript, weil auf dem dell alles ueber den lokalen MQTT-Broker
laeuft: `dragino_rx.py` legt eingehende LoRa-Nachrichten dort ab, und
`crisis_bcast.py` haengt am Topic `crisis` und schiebt alles, was dort steht,
in die Downlink-Warteschlange jedes LoRaWAN-Geraets.

Mitlesen:

    ./crisis_client.py

Etwas rundfunken (geht an alle Geraete):

    ./crisis_client.py -m "Abstieg abgebrochen, bleibt oben"

Ohne -m laeuft es interaktiv: mitlesen und tippen. Eine Zeile ohne Doppelpunkt
geht auf `crisis`, mit `topic: text` landet sie auf einem beliebigen Topic.

**Wann es ankommt:** LoRaWAN Class A kennt keinen echten Rundruf. Ein Geraet
hoert nur kurz nach einem eigenen Uplink; die Nachricht liegt also in der
Warteschlange, bis das Geraet das naechste Mal sendet. Der Fortschritt kommt
als `crisis/status` zurueck und wird hier angezeigt.
"""
import argparse
import base64
import json
import os
import sys
import threading
import time

import paho.mqtt.client as mqtt

HOST = os.environ.get("CRISIS_HOST", "192.168.5.23")
PORT = int(os.environ.get("CRISIS_PORT", "1883"))
TOPIC = "crisis"

lock = threading.Lock()

# paho 2.x will die Callback-Version wissen, 1.x kennt den Parameter nicht
# (dell hat 2.x, dieser Rechner 1.x) — beides soll laufen.
PAHO2 = hasattr(mqtt, "CallbackAPIVersion")


def client(userdata):
    if PAHO2:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata=userdata)
    return mqtt.Client(userdata=userdata)


def show(line):
    """Ausgabe, ohne dass eine halb getippte Eingabezeile zerhackt wird."""
    with lock:
        sys.stdout.write("\r\033[K" + time.strftime("%H:%M:%S ") + line + "\n")
        sys.stdout.flush()


def uplink(msg):
    """ChirpStack-Uplink lesbar machen; None, wenn es keiner ist."""
    dev = (msg.get("deviceInfo") or {}).get("deviceName") \
        or (msg.get("deviceInfo") or {}).get("devEui", "?")
    rx = (msg.get("rxInfo") or [{}])[0]
    raw = base64.b64decode(msg.get("data", "") or "")
    port = msg.get("fPort")
    # fPort 20 ist der stueckweise gesendete Text — den setzt dragino_rx.py
    # zusammen und veroeffentlicht ihn spaeter auf dem gemeinten Topic.
    if port == 20 and len(raw) >= 3:
        seq, last = raw[1] & 0x7F, bool(raw[1] & 0x80)
        koerper = f"Teil {seq}{' (letzter)' if last else ''} von {raw[0]:02X}: " \
                  f"{raw[2:].decode('utf-8', 'replace')}"
    else:
        koerper = f"fPort {port}: {raw.decode('utf-8', 'replace') if raw else '-'}"
    return f"\033[2m<{dev} RSSI {rx.get('rssi')} SNR {rx.get('snr')}>\033[0m {koerper}"


def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        show(f"\033[31mBroker lehnt ab: {rc}\033[0m")
        return
    show(f"\033[32mverbunden mit {userdata['host']}\033[0m — "
         f"Text tippen sendet auf '{TOPIC}', Strg-D beendet")
    client.subscribe("#", qos=1)


def on_message(client, userdata, m):
    t = m.topic
    text = m.payload.decode("utf-8", "replace")

    # Gateway-Statistik ist Rauschen, solange nichts kaputt ist.
    if t.startswith("eu868/gateway/") and not userdata["raw"]:
        if t.endswith("/state/conn"):
            show(f"\033[2mGateway {json.loads(text).get('state', '?')}\033[0m")
        return

    if "/event/" in t:
        if not t.endswith("/event/up"):
            if userdata["raw"]:
                show(f"\033[2m{t}\033[0m {text[:200]}")
            return
        try:
            show(uplink(json.loads(text)))
        except (ValueError, KeyError):
            show(f"\033[2m{t}\033[0m {text[:200]}")
        return

    if t == "crisis/status":
        s = json.loads(text)
        if s.get("state") == "queued":
            show(f"\033[36meingereiht fuer {', '.join(s.get('devices') or ['niemanden'])} "
                 f"({s.get('parts')} Teile)\033[0m")
        else:
            show(f"\033[2mcrisis-bcast: {s.get('state')}\033[0m")
        return

    if t == "dragino/status":
        s = json.loads(text)
        if s.get("state") != "message":          # 'message' kommt gleich als Text
            show(f"\033[2mdragino-rx: {s.get('state')}\033[0m")
        return

    show(f"\033[1m{t}\033[0m  {text}")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default=HOST, help=f"Broker (Vorgabe {HOST})")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("-m", "--message", help="einmalig senden und beenden")
    p.add_argument("-t", "--topic", default=TOPIC, help=f"Ziel-Topic (Vorgabe {TOPIC})")
    p.add_argument("--raw", action="store_true", help="auch Gateway- und Nebenereignisse zeigen")
    a = p.parse_args()

    c = client({"host": a.host, "raw": a.raw})

    if a.message:
        c.connect(a.host, a.port, keepalive=30)
        c.loop_start()
        c.publish(a.topic, a.message, qos=1).wait_for_publish(10)
        c.loop_stop()
        c.disconnect()
        print(f"auf '{a.topic}' gesendet: {a.message}")
        return

    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(a.host, a.port, keepalive=60)
    c.loop_start()
    try:
        if not sys.stdin.isatty():      # nur mitschreiben, z.B. in eine Datei
            while True:
                time.sleep(3600)
        for zeile in sys.stdin:
            zeile = zeile.strip()
            if not zeile:
                continue
            # 'topic: text' geht wohin man will, alles andere in den Rundruf.
            if ": " in zeile and " " not in zeile.split(": ", 1)[0]:
                ziel, _, zeile = zeile.partition(": ")
            else:
                ziel = a.topic
            c.publish(ziel, zeile, qos=1)
            show(f"\033[33m-> {ziel}\033[0m {zeile}")
    except KeyboardInterrupt:
        pass
    finally:
        c.loop_stop()
        c.disconnect()


if __name__ == "__main__":
    main()
