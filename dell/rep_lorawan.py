#!/usr/bin/env python3
"""Zeigt die zuletzt eingegangenen LoRaWAN-Pakete aus `wagodb.loradevice`.

Vorgabe sind die **letzten 11 TTN-Uplinks** — genau der Blick, den man nach
einem Funktest braucht: kam etwas an, ueber welches Gateway, wie stark, und was
stand drin. Die Tabelle ist der Rohspeicher von `lora_log.py`; hier wird nur
gelesen, nie geschrieben.

    ./rep_lorawan.py                  # letzte 11 TTN-Uplinks
    ./rep_lorawan.py -n 30            # mehr davon
    ./rep_lorawan.py --quelle alle    # TTN und lokaler ChirpStack gemischt
    ./rep_lorawan.py --ereignis alle  # auch join/txack/solved statt nur 'up'
    ./rep_lorawan.py --status         # Geraeteeinstellungen aus fPort 5

Ueber der Tabelle stehen die beiden Schalter, die sich staendig von selbst
zurueckstellen: **Datalog** (`PNACKMD`) und **Sport** (`INTWK`). Beide kommen
aus dem letzten Statusrahmen auf fPort 5; beim Datalog kommt der laufende
Beleg dazu, weil `PNACKMD=1` zugleich auf bestaetigte Uplinks umschaltet und
die bei jedem Rahmen sichtbar sind.
    ./rep_lorawan.py --roh            # ganze Zeile als JSON, zum Weiterreichen

`source` trennt die beiden Wege: 'TTN' kommt ueber The Things Network herein,
'lokal' ueber den ChirpStack auf dem dell. Dasselbe Geraet kann auf beiden
Wegen auftauchen, deshalb ist die Quelle Teil jeder Zeile.
"""
import argparse
import json
import os
import sys
from datetime import datetime

import pymysql

# Die Datenbank steht auf dem dell; von dort aus genuegt 127.0.0.1.
DB_HOST = os.environ.get("LORA_DB_HOST", "192.168.5.23")
DB = dict(user="gh", password="a12345", database="wagodb",
          charset="utf8mb4", connect_timeout=5,
          cursorclass=pymysql.cursors.DictCursor)

SPALTEN = ("id, ts, source, event, dev_name, dev_eui, application, f_port, "
           "f_cnt, dr, frequency, rssi, snr, gateway_id, payload_hex, decoded")

# fPort 5 ist der Statusrahmen des TrackerD. Er kommt rund 9 s nach jedem Join
# und sonst nur auf Anforderung: Downlink `23 01` auf einem beliebigen Port
# ausser 0. Das Handbuch verspricht ihn zusaetzlich alle 12 Stunden — diese
# Firmware kann das nicht: `device_send()` haengt allein an `sys.gps_start == 1`,
# und das wird nur im Kaltstartzweig und im Downlink-Handler 0x23 gesetzt. In
# 16 Tagen kam kein einziger der 98 Statusrahmen ohne vorangehenden Join,
# darunter eine Laufzeit von 168 Stunden am Stueck.
STATUS_PORT = 5

BAENDER = {1: "EU868", 2: "US915", 3: "IN865", 4: "AU915", 5: "KZ865",
           6: "RU864", 7: "AS923", 8: "AS923_1", 9: "AS923_2", 10: "AS923_3",
           11: "CN470", 12: "EU433", 13: "KR920", 14: "MA869"}
ARBEITSMODI = {1: "GPS", 2: "BLE", 3: "BLE+GPS"}


def hole(host, anzahl, quelle, ereignis, geraet, f_port=None):
    """Die juengsten Zeilen zuerst — sortiert wird ueber die id, nicht ueber ts.

    `ts` ist die Empfangszeit des Loggers; bei nachgelieferten Fixes (Port 4)
    liegen mehrere Pakete in derselben Millisekunde. Die id bleibt eindeutig.
    """
    wo, werte = [], []
    if quelle != "alle":
        wo.append("source = %s")
        werte.append(quelle)
    if ereignis != "alle":
        wo.append("event = %s")
        werte.append(ereignis)
    if f_port is not None:
        wo.append("f_port = %s")
        werte.append(f_port)
    if geraet:
        wo.append("(dev_name LIKE %s OR dev_eui LIKE %s)")
        werte += ["%" + geraet + "%", "%" + geraet + "%"]
    sql = "SELECT %s FROM loradevice" % SPALTEN
    if wo:
        sql += " WHERE " + " AND ".join(wo)
    sql += " ORDER BY id DESC LIMIT %s"
    werte.append(anzahl)
    with pymysql.connect(host=host, **DB) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, werte)
            return cur.fetchall()


def status_zerlegen(hexstr):
    """Den Statusrahmen (fPort 5) aus dem Rohpaket lesen, nicht aus `decoded`.

    Der Werks-Decoder taugt hier nicht: er weist `panackmd` zu und gibt
    `pnackmd` aus, weshalb `PNACKMD` in der Datenbank immer NULL ist. Und
    seine Modus-Kette prueft den Arbeitsmodus zuerst, so dass der Zweig fuer
    den Bewegungsmodus ("Spots") bei GPS-Betrieb nie erreicht wird. Beide
    Angaben stehen aber sauber im Rahmen — hier werden sie direkt gelesen.

    Byte 8 traegt die drei Schalter: Bit 0 = INTWK (Bewegungsmodus, von
    Dragino "Sports mode" genannt), Bit 1 = LON (Sende-LED), Bit 2 = PNACKMD
    (Werks-Datalog, schaltet zugleich auf bestaetigte Uplinks).
    """
    try:
        b = bytes.fromhex(hexstr or "")
    except ValueError:
        return None
    if len(b) < 9:
        return None
    return dict(
        modell="TrackerD" if b[0] == 0x13 else "?",
        firmware="%d.%d.%d" % (b[1] & 0x0f, (b[2] >> 4) & 0x0f, b[2] & 0x0f),
        band=BAENDER.get(b[3], "0x%02x" % b[3]),
        sub_band="-" if b[4] == 0xff else str(b[4]),
        batv=((b[5] << 8) | b[6]) / 1000.0,
        arbeitsmodus=ARBEITSMODI.get((b[7] >> 6) & 0x03, str((b[7] >> 6) & 0x03)),
        gps_modus=(b[7] >> 4) & 0x03,
        ble_modus=b[7] & 0x0f,
        intwk=b[8] & 0x01,
        lon=(b[8] >> 1) & 0x01,
        pnackmd=(b[8] >> 2) & 0x01,
    )


def nutzlast(zeile):
    """Der lesbare Teil: dekodierte Felder, sonst der Hex-Rumpf."""
    roh = zeile.get("decoded")
    if roh:
        try:
            d = json.loads(roh)
        except (TypeError, ValueError):
            return roh
        if isinstance(d, dict):
            # Location doppelt sich mit Latitude/Longitude — einmal genuegt.
            d.pop("Location", None)
            return " ".join("%s=%s" % (k, v) for k, v in sorted(d.items()))
        return str(d)
    return roh_lesbar(zeile.get("payload_hex"))


def roh_lesbar(hexstr):
    """Ohne Decoder bleibt der Hex-Rumpf — es sei denn, er ist Text.

    Der Konfigrahmen (fPort 9) traegt sein JSON als Klartext; als Hexwurst ist
    das unlesbar, obwohl die Antwort direkt dasteht. Nur druckbare Zeichen
    zaehlen als Text, sonst bleibt es beim Hex.
    """
    if not hexstr:
        return "-"
    try:
        b = bytes.fromhex(hexstr)
    except ValueError:
        return hexstr
    if b and all(32 <= c < 127 for c in b):
        return b.decode("ascii")
    return hexstr


def zeit(t):
    return t.strftime("%d.%m. %H:%M:%S") if isinstance(t, datetime) else str(t)


def tabelle(kopf, reihen):
    """Spalten so breit wie ihr breitester Eintrag, sonst nichts."""
    breit = [max([len(kopf[i])] + [len(r[i]) for r in reihen])
             for i in range(len(kopf))]
    muster = "  ".join("%%-%ds" % b for b in breit)
    print(muster % tuple(kopf))
    print("-" * (sum(breit) + 2 * (len(breit) - 1)))
    return muster


def datalog_zustand(host, geraet):
    """Stand von Datalog und Sport, als Liste fertiger Zeilen.

    Ist der Datalog an? Zwei unabhaengige Quellen, beide ohne Geraetezugriff.

    `PNACKMD` steht als Bit 2 im Statusrahmen auf fPort 5 -- die verlaessliche
    Auskunft, aber nur so frisch wie der letzte Statusrahmen, und der kommt
    im Wesentlichen nach einem Join.

    Der laufende Beleg sind die Uplinks selbst: `PNACKMD=1` schaltet zugleich
    auf bestaetigte Uplinks um (`CFM=1`), in `loradevice` also `confirmed=1`.
    Steht das bei den juengsten Rahmen, ist der Datalog jetzt an -- unabhaengig
    davon, wie alt der letzte Statusrahmen ist.
    """
    with pymysql.connect(host=host, **DB) as conn:
        with conn.cursor() as cur:
            wo, werte = "", []
            if geraet:
                wo = " AND (dev_name LIKE %s OR dev_eui LIKE %s)"
                werte = ["%" + geraet + "%", "%" + geraet + "%"]
            cur.execute("SELECT ts, payload_hex FROM loradevice WHERE event='up'"
                        " AND f_port=%s" + wo + " ORDER BY id DESC LIMIT 1",
                        [STATUS_PORT] + werte)
            r = cur.fetchone()
            # DictCursor: Spalten benennen, sonst entpackt man die Schluessel.
            # DictCursor: Spalten benennen, sonst entpackt man die Schluessel.
            cur.execute("SELECT ts, confirmed FROM loradevice WHERE event='up'"
                        " AND f_port<>%s" + wo + " ORDER BY id DESC LIMIT 5",
                        [STATUS_PORT] + werte)
            uplinks = cur.fetchall()
            letzte = [int(x["confirmed"] or 0) for x in uplinks]

    st = status_zerlegen(r["payload_hex"]) if r else None
    if not st:
        return ["kein Statusrahmen (fPort %d) gefunden" % STATUS_PORT]

    stand = zeit(r["ts"])
    # Die Version verraet, welche Partition laeuft: app0 meldet 1.4.8
    # (Werksfirmware), der Eigenbau in app1 meldet 1.4.6, weil Dragino den
    # Versionsstring im Quelltext seit v1.4.6 nicht nachgezogen hat.
    slot = {"1.4.8": "app0, Werksfirmware",
            "1.4.6": "app1, Eigenbau"}.get(st["firmware"], "unbekannter Slot")
    zeilen = ["Firmware  %-8s  %s   Modell %s, Band %s, Batterie %.3f V"
              % (st["firmware"], slot, st["modell"], st["band"], st["batv"])]
    # Datalog: Statusrahmen sagt die Einstellung, die Uplinks sagen den
    # Ist-Zustand -- PNACKMD=1 schaltet zugleich auf bestaetigte Uplinks um,
    # und die kommen bei jedem Rahmen, nicht nur nach einem Join.
    # Massgeblich ist die juengere der beiden Quellen. Der Statusrahmen kommt
    # im Wesentlichen nur nach einem Join und ist deshalb oft veraltet -- ein
    # Downlink, der PNACKMD umschaltet, taucht dort erst beim naechsten Join
    # auf, in den bestaetigten Uplinks dagegen sofort.
    if uplinks and uplinks[0]["ts"] > r["ts"]:
        urteil = "AN" if letzte[0] else "AUS"
        quelle = ("Uplink %s %sbestaetigt (%d von %d)  |  Statusrahmen %s sagte %s"
                  % (zeit(uplinks[0]["ts"]), "" if letzte[0] else "NICHT ",
                     sum(letzte), len(letzte), stand,
                     "AN" if st["pnackmd"] else "AUS"))
    else:
        urteil = "AN" if st["pnackmd"] else "AUS"
        quelle = "Statusrahmen %s" % stand
        if letzte:
            quelle += ("  |  juengster Uplink %sbestaetigt (%d von %d)"
                       % ("" if letzte[0] else "NICHT ", sum(letzte), len(letzte)))
    zeilen.append("Datalog (PNACKMD)  %-4s  %s" % (urteil, quelle))
    # Sport: nur aus dem Statusrahmen. Das Feld `Transport` im Positionsrahmen
    # taugt nicht dafuer -- es meldet, ob der letzte Weckruf von der Bewegung
    # kam, nicht ob der Modus eingeschaltet ist.
    zeilen.append("Sport   (INTWK)    %-4s  Statusrahmen %s"
                  % ("AN" if st["intwk"] else "AUS", stand))
    return zeilen


def drucke(zeilen):
    """Aelteste oben, damit man den Verlauf von oben nach unten liest."""
    kopf = ("Zeit", "Q", "Ereig", "Geraet", "Po", "FCnt", "DR", "MHz",
            "RSSI", "SNR", "Gateway")
    reihen = []
    for z in reversed(zeilen):
        f = z["frequency"]
        reihen.append((
            zeit(z["ts"]),
            (z["source"] or "?")[:5],
            (z["event"] or "?")[:5],
            (z["dev_name"] or z["dev_eui"] or "?")[:20],
            "" if z["f_port"] is None else str(z["f_port"]),
            "" if z["f_cnt"] is None else str(z["f_cnt"]),
            "" if z["dr"] is None else str(z["dr"]),
            "" if f is None else "%.1f" % (f / 1e6),
            "" if z["rssi"] is None else str(z["rssi"]),
            "" if z["snr"] is None else "%.1f" % z["snr"],
            (z["gateway_id"] or "")[-6:],
        ))
    muster = tabelle(kopf, reihen)
    for r, z in zip(reihen, reversed(zeilen)):
        print(muster % r)
        print("      %s" % nutzlast(z))


def drucke_status(zeilen):
    """Die Einstellungen, die das Geraet selbst meldet — je Rahmen eine Zeile.

    Zwei gleiche Zeilen hintereinander heissen: nichts hat sich geaendert. Der
    Rahmen kommt nach jedem Join, also oft mehrmals kurz nacheinander.
    """
    kopf = ("Zeit", "Q", "Geraet", "FW", "Band", "BatV", "Modus",
            "INTWK", "LON", "PNACKMD", "Hex")
    reihen, unlesbar = [], 0
    for z in reversed(zeilen):
        s = status_zerlegen(z["payload_hex"])
        if s is None:
            unlesbar += 1
            continue
        reihen.append((
            zeit(z["ts"]),
            (z["source"] or "?")[:5],
            (z["dev_name"] or z["dev_eui"] or "?")[:20],
            s["firmware"],
            s["band"],
            "%.3f" % s["batv"],
            s["arbeitsmodus"],
            "an" if s["intwk"] else "aus",
            "an" if s["lon"] else "aus",
            "an" if s["pnackmd"] else "aus",
            (z["payload_hex"] or ""),
        ))
    if not reihen:
        print("keine lesbaren Statusrahmen (fPort %d)" % STATUS_PORT)
        return
    muster = tabelle(kopf, reihen)
    for r in reihen:
        print(muster % r)
    if unlesbar:
        print("(%d Rahmen zu kurz oder ohne Hex uebersprungen)" % unlesbar)
    letzte = reihen[-1]
    print()
    print("Stand %s: Bewegungsmodus (AT+INTWK, Draginos \"Sports mode\") ist %s."
          % (letzte[0], letzte[7].upper()))
    print("Frischer Stand: Downlink `23 01` anfordern (jeder Port ausser 0),")
    print("sonst kommt der Rahmen erst beim naechsten Join.")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-n", "--anzahl", type=int, default=11,
                   help="wie viele Pakete (Vorgabe 11)")
    p.add_argument("--quelle", default="TTN",
                   help="TTN, lokal oder alle (Vorgabe TTN)")
    p.add_argument("--ereignis", default="up",
                   help="up, join, txack, solved ... oder alle (Vorgabe up)")
    p.add_argument("--geraet", help="Filter auf dev_name oder dev_eui")
    p.add_argument("--port", type=int, help="Filter auf einen fPort")
    p.add_argument("--status", action="store_true",
                   help="Statusrahmen fPort %d: INTWK/LON/PNACKMD aus dem Hex"
                        % STATUS_PORT)
    p.add_argument("--db-host", default=DB_HOST, help="Vorgabe %s" % DB_HOST)
    p.add_argument("--roh", action="store_true",
                   help="Zeilen als JSON statt als Tabelle")
    a = p.parse_args()

    port = a.port
    if a.status:
        # Der Statusrahmen ist immer ein Uplink auf fPort 5 — beides setzen,
        # damit --status ohne weitere Schalter das Richtige zeigt.
        port = STATUS_PORT if port is None else port
        a.ereignis = "up"

    try:
        zeilen = hole(a.db_host, a.anzahl, a.quelle, a.ereignis, a.geraet, port)
    except pymysql.Error as e:
        print("Datenbank %s: %s" % (a.db_host, e), file=sys.stderr)
        return 1
    if not zeilen:
        print("keine Pakete (quelle=%s ereignis=%s%s)"
              % (a.quelle, a.ereignis, "" if port is None else " port=%d" % port))
        return 0
    if not a.roh:
        try:
            for z in datalog_zustand(a.db_host, a.geraet):
                print(z)
            print()
        except pymysql.Error:
            pass          # der Bericht selbst ist wichtiger als der Kopf
    if a.roh:
        print(json.dumps(list(reversed(zeilen)), default=str,
                         ensure_ascii=False, indent=2))
    elif a.status:
        drucke_status(zeilen)
    else:
        drucke(zeilen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
