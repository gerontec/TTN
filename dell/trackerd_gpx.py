#!/usr/bin/env python3
"""Schiebt die Spuren des TrackerD als GPX in den Tourenreport auf web1.

Der Report (`https://web1.heissa.de/web1/gpx_report.php`) speiste sich bisher
nur aus GPX-Uploads der osmcycle-App. Die Fixes des TrackerD lagen daneben
ungenutzt in `wagodb.loradevice` — auf derselben Karte gehoeren sie
zusammen, gerade wenn das Handy nicht dabei war.

Drei Entscheidungen, die den Unterschied machen:

**Zeitstempel aus dem Datensatz, nicht aus der Ankunft.** Nachgelieferte Fixes
aus dem Geraetepuffer (`event='up-log'`) tragen ihre GPS-Zeit in `dev_time`.
Wer stattdessen `ts` nimmt, legt eine stundenlang gepufferte Fahrt auf den
Zeitpunkt des Wiedereinbuchens — also genau dorthin, wo sie nicht war.

**Nur echte Fahrten.** Ein Geraet, das den ganzen Tag auf dem Fensterbrett
liegt, erzeugt eine Punktwolke von rund 100 m Durchmesser — reine
GPS-Streuung. Ohne Mindestausdehnung stuende jeder Tag als "Tour" im Report.
Geprueft wird die groesste Entfernung zwischen zwei Punkten, nicht die Summe
der Teilstrecken: die waechst auch im Stillstand.

**Keine Hoehe noetig.** `gpx_report.py` schlaegt die Hoehe im
Copernicus-Modell nach (`ele_cop` vor `ele_gps`); der TrackerD sendet keine,
das ist also kein Mangel.

**Zusammenfuehren statt zerschneiden.** Die Lueckenregel zerteilt eine Tour
bei jeder Pause ueber `--luecke` — das ist bei zwei Kriterien zu grob:

1. *Alarmfenster:* Waehrend des Alarms (`ALARM_status` im Payload) sendet das
   Geraet im Minutentakt. Faellt die Spur dort trotzdem auseinander, ist es ein
   Empfangsloch, nicht das Ende der Fahrt. Alles innerhalb eines Alarmfensters
   ist ein einziger Track; die Fenster selbst werden ueber `--alarm-luecke`
   zusammengehalten, damit auch ein langes Loch kein zweites Fenster oeffnet.
2. *Oertliche Naehe:* Im Sport-Mode meldet sich das Geraet nur bei Bewegung;
   wer laenger steht, erzeugt eine Luecke. Endet eine Tour nah am Anfang der
   naechsten (Zeit *und* Ort), ist es dieselbe Tour — siehe `--join-luecke`
   und `--join-dist`.

Der Dateiname folgt der Konvention, die `gpx_report.py` parst
(`YYYY-MM-DD_HH-MM_Wochentag.gpx`), erweitert um die Geraetekennung. Er ist je
Tour gleichbleibend — ein zweiter Lauf ueberschreibt dieselbe Datei, statt
Doubletten anzulegen.

    trackerd_gpx.py [--tage 7] [--min-strecke 300] [--luecke 45] [--dry]
"""
import argparse
import json
import sys
import urllib.request
import uuid
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

import pymysql

# Wo die Empfangsstellen stehen. Das eigene Gateway kommt aus local_conf.json
# des DLOS8N (ref_latitude/ref_longitude), fremde liefert TTS in rx_metadata
# gleich mit -- deshalb wird die Liste nur ergaenzt, nicht gepflegt.
GATEWAYS = {
    "a84041ffff27e318": ("DLOS8N Lenggries", 47.679, 11.579),
    "b827ebfffe3cec15": ("Gymnasium Lenggries", 47.672236, 11.58718),
}

UPLOAD = "https://web1.heissa.de/web1/gpx_upload.php"
DB = dict(host="192.168.5.23", user="gh", password="a12345", database="wagodb",
          charset="utf8mb4", connect_timeout=5)
WOCHENTAG = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

ap = argparse.ArgumentParser()
ap.add_argument("--geraet", default="trackerd-lenggries")
ap.add_argument("--tage", type=int, default=7)
ap.add_argument("--min-strecke", type=int, default=300,
                help="Mindestausdehnung in Metern, sonst keine Tour")
ap.add_argument("--min-punkte", type=int, default=8)
ap.add_argument("--luecke", type=int, default=45,
                help="Pause in Minuten, die zwei Touren trennt")
ap.add_argument("--alarm-luecke", type=int, default=120,
                help="Max. Minuten zwischen zwei Alarm-Punkten, die noch zum "
                     "selben Alarmfenster zaehlen (Empfangsloch im Alarm)")
ap.add_argument("--join-luecke", type=int, default=60,
                help="Zwei Touren werden verbunden, wenn ihre Pause hoechstens "
                     "so lang ist und die Endpunkte nah beieinander liegen")
ap.add_argument("--join-dist", type=int, default=300,
                help="Max. Abstand in Metern zwischen Ende und Anfang zweier "
                     "Touren, damit der Naehe-Join sie verbindet")
ap.add_argument("--quelle", choices=("TTN", "lokal", "beide"), default="TTN",
                help="welcher Netzwerkserver die Spur liefert (Spalte source)")
ap.add_argument("--dry", action="store_true")
args = ap.parse_args()


def dist(a, b):
    R = 6371000.0
    p1, p2 = radians(a[0]), radians(b[0])
    x = (sin(radians(b[0] - a[0]) / 2) ** 2
         + cos(p1) * cos(p2) * sin(radians(b[1] - a[1]) / 2) ** 2)
    return 2 * R * asin(sqrt(x))


seit = datetime.now() - timedelta(days=args.tage)
print(f"Quelle: {args.quelle}")
conn = pymysql.connect(**DB)
with conn.cursor() as cur:
    # Beide Netze protokollieren denselben Uplink; ohne Einschraenkung stuende
    # jeder Punkt doppelt in der Spur. Vorgabe ist TTN, weil nur dieser Weg
    # die Empfangsstellen mitfuehrt -- auch fremde Gateways.
    quelle_sql = "" if args.quelle == "beide" else " AND source=%s"
    werte = [args.geraet, seit] if args.quelle == "beide" else [args.geraet, seit, args.quelle]
    cur.execute(
        """SELECT COALESCE(dev_time, ts), decoded, rssi
             FROM loradevice
            WHERE dev_name=%s AND event IN ('up','up-log')
              AND decoded IS NOT NULL AND ts >= %s""" + quelle_sql + """
            ORDER BY COALESCE(dev_time, ts)""",
        werte)
    zeilen = cur.fetchall()
    # Empfangsstellen: nur der TTN-Weg fuehrt sie mit, und dort steht **jede**
    # Station, die den Rahmen gehoert hat -- auch fremde. Der lokale Weg kennt
    # immer nur das eigene Gateway.
    cur.execute(
        """SELECT ts, raw FROM loradevice
            WHERE dev_name=%s AND source='TTN' AND event='up' AND ts >= %s
            ORDER BY ts""", (args.geraet, seit))
    ttn_zeilen = cur.fetchall()
conn.close()

punkte = []
for zeit, dec, rssi in zeilen:
    try:
        d = json.loads(dec)
    except (TypeError, ValueError):
        continue
    la, lo = d.get("Latitude"), d.get("Longitude")
    if not la or not lo:          # 0.0 heisst: kein Fix in diesem Zyklus
        continue
    alarm = str(d.get("ALARM_status", "")).upper() == "TRUE"
    punkte.append((zeit, float(la), float(lo), rssi, alarm))

empfang = []          # (Zeit, {eui: staerkster Pegel})
station = {}          # eui -> (lat, lon), aus rx_metadata.location
for zeit, roh in ttn_zeilen:
    try:
        m = json.loads(roh)
    except (TypeError, ValueError):
        continue
    je_gw = {}
    for g in (m.get("uplink_message") or {}).get("rx_metadata") or []:
        eui = ((g.get("gateway_ids") or {}).get("eui") or "").lower()
        if eui:
            je_gw[eui] = max(je_gw.get(eui, -999), g.get("rssi") or -999)
            # TTS liefert die Gateway-Position gleich mit (SOURCE_REGISTRY oder
            # SOURCE_GPS). Nur fremde Gateways ohne freigegebene Position
            # fallen spaeter aufs Namens-Dictionary zurueck.
            if eui not in station:
                ort = g.get("location") or {}
                if ort.get("latitude") is not None and ort.get("longitude") is not None:
                    station[eui] = (float(ort["latitude"]), float(ort["longitude"]))
    if je_gw:
        empfang.append((zeit, je_gw))

if not punkte:
    print(f"keine Fixes im Zeitraum (Quelle {args.quelle})")
    sys.exit(0)

touren, aktuell = [], [punkte[0]]
for vorher, jetzt in zip(punkte, punkte[1:]):
    if (jetzt[0] - vorher[0]) > timedelta(minutes=args.luecke):
        touren.append(aktuell)
        aktuell = []
    aktuell.append(jetzt)
touren.append(aktuell)

# ── Join ─────────────────────────────────────────────────────────────────────
# Alarmfenster: zusammenhaengende Alarm-Punkte bilden ein Fenster, auch wenn
# dazwischen ein Empfangsloch klafft. Ein Punkt im Fenster -- und alles bis zum
# naechsten Punkt derselben Tour liegt "drin": was zerfiel, war ein Track.
fenster = []
for p in punkte:
    if not p[4]:
        continue
    if fenster and (p[0] - fenster[-1][1]) <= timedelta(minutes=args.alarm_luecke):
        fenster[-1][1] = p[0]
    else:
        fenster.append([p[0], p[0]])

def verbinden(a, b):
    """Warum zwei benachbarte Touren dieselbe Tour sind -- oder None."""
    von, bis = a[-1][0], b[0][0]
    if any(von >= s and bis <= e for s, e in fenster):
        return "Alarmfenster"
    if ((bis - von) <= timedelta(minutes=args.join_luecke)
            and dist((a[-1][1], a[-1][2]), (b[0][1], b[0][2])) <= args.join_dist):
        return "zeitlich/oertlich nah"
    return None

# Ein Durchlauf von links genuegt: ob (A+B) mit C darf, haengt nur von B-Ende
# und C-Anfang ab -- genau wie die Frage, ob B mit C duerfte.
neu = [touren[0]]
for t in touren[1:]:
    grund = verbinden(neu[-1], t)
    if grund:
        print(f"  Join ({grund}): ...{neu[-1][-1][0]:%d.%m. %H:%M} + "
              f"{t[0][0]:%d.%m. %H:%M}–{t[-1][0]:%H:%M}")
        neu[-1] = neu[-1] + t
    else:
        neu.append(t)
touren = neu

hochgeladen = 0
for t in touren:
    if len(t) < args.min_punkte:
        continue
    weit = max(dist((a[1], a[2]), (b[1], b[2])) for a in t for b in t)
    start = t[0][0]
    if weit < args.min_strecke:
        print(f"{start:%Y-%m-%d %H:%M}  {len(t):3d} Punkte, Ausdehnung "
              f"{weit:5.0f} m — Streuung im Stand, uebersprungen")
        continue

    ende = t[-1][0]
    # Welche Station hat waehrend dieser Tour gehoert, und wie oft?
    gezaehlt = {}
    for zeit, je_gw in empfang:
        if start <= zeit <= ende:
            for eui, rssi in je_gw.items():
                treffer, best = gezaehlt.get(eui, (0, -999))
                gezaehlt[eui] = (treffer + 1, max(best, rssi))

    name = (f"{start:%Y-%m-%d_%H-%M}_{WOCHENTAG[start.weekday()]}"
            f"_{args.geraet}.gpx")
    gpx = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="trackerd_gpx.py" '
           'xmlns="http://www.topografix.com/GPX/1/1">',
           ]
    for eui, (treffer, best) in sorted(gezaehlt.items(), key=lambda x: -x[1][0]):
        klar, la, lo = GATEWAYS.get(eui, (eui.upper(), None, None))
        if la is None:
            continue          # unbekannte Station: ohne Position nicht zeichenbar
        gpx.append(f'  <wpt lat="{la:.6f}" lon="{lo:.6f}">'
                   f"<name>{klar}</name>"
                   f"<desc>{treffer} x gehoert, bester Pegel {best} dBm</desc></wpt>")
    gpx.append(f"  <trk><name>{args.geraet} {start:%d.%m.%Y %H:%M}</name><trkseg>")
    # Die Feldstaerke gehoert an den Punkt, an dem gesendet wurde -- erst so
    # wird aus der Spur eine Abdeckungsmessung. GPX kennt dafuer kein Feld,
    # <desc> je trkpt ist der Weg, den auch andere Werkzeuge lesen koennen.
    for zeit, la, lo, rssi, _alarm in t:
        pegel = f"<desc>{rssi} dBm</desc>" if rssi is not None else ""
        gpx.append(f'    <trkpt lat="{la:.6f}" lon="{lo:.6f}">'
                   f"<time>{zeit.strftime('%Y-%m-%dT%H:%M:%SZ')}</time>"
                   f"{pegel}</trkpt>")
    gpx.append("  </trkseg></trk>\n</gpx>\n")
    rumpf = "\n".join(gpx).encode()

    gw_text = ", ".join(f"{GATEWAYS.get(e, (e[:8],))[0]} {v[0]}x" for e, v in gezaehlt.items())
    print(f"{start:%Y-%m-%d %H:%M}  {len(t):3d} Punkte, Ausdehnung {weit:5.0f} m "
          f"-> {name}\n    Empfangsstellen: {gw_text or 'keine (kein TTN-Weg)'}")
    if args.dry:
        continue

    grenze = uuid.uuid4().hex
    leib = (f"--{grenze}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{name}\"\r\nContent-Type: application/gpx+xml\r\n\r\n"
            ).encode() + rumpf + f"\r\n--{grenze}--\r\n".encode()
    req = urllib.request.Request(
        UPLOAD, data=leib,
        headers={"Content-Type": f"multipart/form-data; boundary={grenze}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            antwort = r.read().decode().strip()
        print(f"    hochgeladen: {antwort}")
        hochgeladen += 1
    except Exception as e:                      # noqa: BLE001
        print(f"    FEHLER beim Hochladen: {e}")

print(f"\n{hochgeladen} Tour(en) hochgeladen. "
      "Der Report baut sich stuendlich neu (Cron auf heissa.de).")
