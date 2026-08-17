#!/usr/bin/env python3
"""Greift rohes LoRa neben der LoRaWAN-Kette ab, nicht dahinter.

Das DLOS8N schiebt jedes demodulierte Paket unveraendert als `rxpk.data` an alle
konfigurierten Server. ChirpStack auf :1700 verwirft alles, was kein gueltiges
LoRaWAN-Frame ist -- fuer den Krisenkanal ist das genau das Falsche. Deshalb
haengt am Gateway ein dritter Server (`raw-dell`, UDP 1702), der hier landet.

Gefiltert wird auf den Rohkanal `chan_Lora_std` (868.125 MHz, SF7, BW125): der
ist ausschliesslich fuer P2P reserviert, waehrend 868.1/868.3/868.5 den
LoRaWAN-Kanaelen gehoeren. Was auf 868.1 zusaetzlich mitgehoert wird -- die
Kanaele liegen nur 25 kHz auseinander -- zeigt `--all`.

Wichtig: das Syncword des SX1302 gilt chipweit (`lorawan_public: true` = 0x34).
Ein Node mit dem privaten 0x12 wird nicht gehoert, siehe README.

  ./lora_raw.py                      # nur der Rohkanal, Klartext + Hex
  ./lora_raw.py --all                # jedes Paket, auch LoRaWAN
  ./lora_raw.py --mqtt               # zusaetzlich nach mosquitto
  ./lora_raw.py --send "hallo"       # einmal senden, dann weiter lauschen
"""
import argparse
import base64
import binascii
import glob
import json
import logging
import select
import socket
import sys
import time

PORT = 1702
RAW_FREQ = 868.125          # chan_Lora_std, siehe /etc/lora/global_conf.json
FREQ_TOL = 0.02             # MHz; deckt den Quarzversatz des Nodes ab
MQTT_TOPIC = "lora/raw"

# Rahmenformat des Krisennetzes, siehe devices/pico_sx1262/repeater.py:
#   frisch          IIII>nutzlast
#   weitergegeben   RnIIII>nutzlast
#   Befehl/Antwort  C>... bzw. A>IIII>...
ID_LEN = 4
HEXZIFFERN = set("0123456789ABCDEF")

# Ebyte-Rahmen (E22/E90), siehe devices/pico_sx1262/EBYTE_E90.md:
#   2 Byte Kennung (0x2C, Kanal) | Pruefbyte xx, xx^0xA1 | NETID |
#   2 Byte Absenderadresse | Laenge | Nutzlast, XOR 0x12
# Das Modul traegt seine *eigene* Adresse ein -- genau das, was zum
# Selbsterkennen noetig ist. Das Pruefbytepaar ist eine XOR-Summe ueber die
# Nutzlast, kein Zaehler: gleiche Nutzlast ergibt Byte fuer Byte denselben
# Rahmen.
EBYTE_MAGIC = 0x2C
EBYTE_KOPF = 8


def eigene_kennung():
    """Letzte vier Hexstellen der MAC. Ohne Vergabeliste eindeutig und von
    Haus aus gueltiges Hex -- ein sprechendes Kuerzel waere es nicht."""
    for pfad in sorted(glob.glob("/sys/class/net/*/address")):
        if "/lo/" in pfad:
            continue
        try:
            mac = open(pfad).read().strip().replace(":", "").upper()
        except OSError:
            continue
        if len(mac) == 12 and mac != "0" * 12 and set(mac) <= HEXZIFFERN:
            return mac[-ID_LEN:]
    return "0000"


def ebyte_absender(roh):
    """Absenderadresse als vier Hexstellen, oder None wenn kein Ebyte-Rahmen.

    Kennung in Byte 0 und Laengenangabe in Byte 7 zusammen sind ein
    belastbares Merkmal, das Textpakete nicht zufaellig erfuellen.
    """
    if (len(roh) > EBYTE_KOPF and roh[0] == EBYTE_MAGIC
            and roh[EBYTE_KOPF - 1] == len(roh) - EBYTE_KOPF):
        return "%02X%02X" % (roh[5], roh[6])
    return None


def zerlege(roh):
    """(sprung, absender, nutzlast); absender None = ohne Kennung."""
    try:
        t = roh.decode("utf-8")
    except UnicodeDecodeError:
        return 0, None, roh
    if (len(t) > ID_LEN + 3 and t[0] == "R" and t[1].isdigit()
            and t[2 + ID_LEN] == ">" and set(t[2:2 + ID_LEN].upper()) <= HEXZIFFERN):
        return int(t[1]), t[2:2 + ID_LEN], roh[3 + ID_LEN:]
    if (len(t) > ID_LEN and t[ID_LEN] == ">"
            and set(t[0:ID_LEN].upper()) <= HEXZIFFERN):
        return 0, t[0:ID_LEN], roh[ID_LEN + 1:]
    return 0, None, roh

# Semtech UDP protocol v2, Byte 3 des Kopfes
PUSH_DATA, PUSH_ACK, PULL_DATA, PULL_RESP, PULL_ACK, TX_ACK = 0, 1, 2, 3, 4, 5

log = logging.getLogger("lora_raw")


def printable(raw):
    """Nutzlast als Text, sofern sie wie Text aussieht."""
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return txt if all(c == "\n" or c == "\t" or " " <= c <= "~" or c > "\xa0"
                      for c in txt) else None


def txpk(text, freq, datr, power):
    """Rohes LoRa senden. ipol=false, sonst hoert kein P2P-Node zu -- die
    invertierte Polaritaet ist eine LoRaWAN-Eigenheit der Downlinks."""
    data = text.encode() if isinstance(text, str) else text
    return json.dumps({"txpk": {
        "imme": True,
        "freq": freq,
        "rfch": 0,              # radio_0, nur das hat tx_enable
        "powe": power,
        "modu": "LORA",
        "datr": datr,
        "codr": "4/5",
        "ipol": False,
        "size": len(data),
        "data": base64.b64encode(data).decode(),
    }}).encode()


def handle_rxpk(pkt, args, mq):
    freq = pkt.get("freq", 0.0)
    is_raw = abs(freq - args.freq) <= FREQ_TOL
    if not is_raw and not args.all:
        return

    raw = b""
    if pkt.get("data"):
        try:
            raw = base64.b64decode(pkt["data"])
        except (binascii.Error, ValueError):
            log.warning("unlesbares base64 auf %.3f MHz", freq)
            return

    stat = {1: "ok", -1: "CRC-Fehler", 0: "ohne CRC"}.get(pkt.get("stat"), "?")
    sprung, absender, nutz = zerlege(raw)

    # Selbstfilter. Jedes Geraet muss die eigenen Pakete erkennen: was ueber
    # ein Relais zurueckkommt, ist kein neuer Verkehr. Beide Formate tragen
    # die Absenderkennung mit -- Text als vier Hexstellen vor dem ">", Ebyte
    # als Adresse in Byte 5-6. Ohne diesen Filter wuerde jede Bruecke von
    # MQTT zurueck auf den Steuereingang eine Endlosschleife erzeugen.
    quelle = ebyte_absender(raw) or absender
    if args.self_filter and quelle and quelle.upper() == args.id.upper():
        log.info("%.3f MHz  %-9s RSSI %-5s eigenes Echo von %s%s, %d B "
                 "-- gefiltert (Relais bestaetigt)",
                 freq, pkt.get("datr", "?"), pkt.get("rssi", "?"), quelle,
                 "/%d" % sprung if sprung else "", len(nutz))
        return
    txt = printable(nutz)
    herkunft = "%s%s" % (absender or "----",
                         "/%d" % sprung if sprung else "   ")
    log.info("%.3f MHz  %-9s RSSI %-5s SNR %-5s CRC %-10s von %-8s %3dB  %s",
             freq, pkt.get("datr", "?"), pkt.get("rssi", "?"),
             pkt.get("lsnr", "?"), stat, herkunft, len(nutz),
             '"%s"' % txt if txt else nutz.hex())

    if mq is not None:
        mq.publish(MQTT_TOPIC, json.dumps({
            "freq": freq, "datr": pkt.get("datr"), "chan": pkt.get("chan"),
            "rssi": pkt.get("rssi"), "snr": pkt.get("lsnr"), "crc": stat,
            "absender": absender, "sprung": sprung,
            "raw": raw.hex(), "text": txt, "t": time.time()}), qos=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--freq", type=float, default=RAW_FREQ,
                    help="Mittenfrequenz des Rohkanals in MHz")
    ap.add_argument("--all", action="store_true",
                    help="auch LoRaWAN-Pakete der uebrigen Kanaele zeigen")
    ap.add_argument("--mqtt", action="store_true",
                    help="zusaetzlich auf mosquitto veroeffentlichen")
    ap.add_argument("--send", metavar="TEXT",
                    help="einmal rohes LoRa senden, sobald das Gateway PULL_DATA schickt")
    ap.add_argument("--id", default=None,
                    help="eigene Absenderkennung; Vorgabe sind die letzten "
                         "vier Hexstellen der MAC")
    ap.add_argument("--no-self-filter", dest="self_filter",
                    action="store_false",
                    help="eigene Pakete NICHT herausfiltern; nur zum Messen, "
                         "im Regelbetrieb droht sonst eine Rueckkopplung")
    ap.add_argument("--ctrl-port", type=int, default=1703,
                    help="lokaler Steuereingang; was hier ankommt, wird gefunkt")
    ap.add_argument("--datr", default="SF7BW125")
    ap.add_argument("--power", type=int, default=14,
                    help="dBm ERP; 14 = 25 mW, das Limit in 868.0-868.6")
    args = ap.parse_args()

    if args.id is None:
        args.id = eigene_kennung()

    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    mq = None
    if args.mqtt:
        import paho.mqtt.client as mqtt
        mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="lora-raw")
        mq.connect("127.0.0.1", 1883, keepalive=60)
        mq.loop_start()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", args.port))
    log.info("lausche auf UDP %d, Rohkanal %.3f MHz (+/- %.0f kHz)%s",
             args.port, args.freq, FREQ_TOL * 1000,
             ", alle Kanaele" if args.all else "")

    # Steuereingang: der Dienst haelt 1702 dauerhaft, ein zweites Werkzeug
    # koennte also nicht senden. Wer etwas absetzen will, schickt es hierher
    # -- nur von localhost, das ist kein Fernzugang.
    ctrl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ctrl.bind(("127.0.0.1", args.ctrl_port))
    log.info("Steuereingang auf 127.0.0.1:%d", args.ctrl_port)

    log.info("eigene Kennung %s (aus der MAC), Selbstfilter %s",
             args.id, "an" if args.self_filter else "AUS")

    def mit_kennung(roh):
        """Befehle und Antworten tragen ihr eigenes Praefix, alles andere
        bekommt die Absenderkennung vorangestellt."""
        if roh[:2] in (b"C>", b"A>") or zerlege(roh)[1] is not None:
            return roh
        return args.id.encode() + b">" + roh

    warteschlange = []
    if args.send:
        warteschlange.append(mit_kennung(args.send.encode()))

    while True:
        bereit, _, _ = select.select([s, ctrl], [], [], 1.0)
        if ctrl in bereit:
            roh, _ = ctrl.recvfrom(4096)
            roh = mit_kennung(roh)
            warteschlange.append(roh)
            log.info("eingereiht: %r", roh)
        if s not in bereit:
            continue
        data, peer = s.recvfrom(65535)
        if len(data) < 4:
            continue
        token, kind = data[1:3], data[3]

        if kind == PUSH_DATA:
            s.sendto(bytes([data[0]]) + token + bytes([PUSH_ACK]), peer)
            if len(data) <= 12:
                continue
            try:
                body = json.loads(data[12:].decode("utf-8", "replace"))
            except ValueError:
                continue
            for pkt in body.get("rxpk", []):
                handle_rxpk(pkt, args, mq)

        elif kind == PULL_DATA:
            s.sendto(bytes([data[0]]) + token + bytes([PULL_ACK]), peer)
            if warteschlange:
                naechste = warteschlange.pop(0)
                s.sendto(bytes([data[0]]) + token + bytes([PULL_RESP])
                         + txpk(naechste, args.freq, args.datr, args.power), peer)
                log.info("gesendet: %r auf %.3f MHz %s, %d dBm",
                         naechste, args.freq, args.datr, args.power)

        elif kind == TX_ACK:
            if len(data) > 12:
                err = json.loads(data[12:].decode("utf-8", "replace") or "{}")
                err = (err.get("txpk_ack") or {}).get("error", "NONE")
                log.info("TX_ACK vom Gateway: %s", err)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
