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
import json
import logging
import socket
import sys
import time

PORT = 1702
RAW_FREQ = 868.125          # chan_Lora_std, siehe /etc/lora/global_conf.json
FREQ_TOL = 0.02             # MHz; deckt den Quarzversatz des Nodes ab
MQTT_TOPIC = "lora/raw"

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
    txt = printable(raw)
    log.info("%.3f MHz  %-9s ch%-2s RSSI %-5s SNR %-5s CRC %-10s %3dB  %s%s",
             freq, pkt.get("datr", "?"), pkt.get("chan", "?"),
             pkt.get("rssi", "?"), pkt.get("lsnr", "?"), stat, len(raw),
             raw.hex(), '  "%s"' % txt if txt else "")

    if mq is not None:
        mq.publish(MQTT_TOPIC, json.dumps({
            "freq": freq, "datr": pkt.get("datr"), "chan": pkt.get("chan"),
            "rssi": pkt.get("rssi"), "snr": pkt.get("lsnr"), "crc": stat,
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
    ap.add_argument("--datr", default="SF7BW125")
    ap.add_argument("--power", type=int, default=14,
                    help="dBm ERP; 14 = 25 mW, das Limit in 868.0-868.6")
    args = ap.parse_args()

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

    pending_tx = args.send
    while True:
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
            if pending_tx is not None:
                s.sendto(bytes([data[0]]) + token + bytes([PULL_RESP])
                         + txpk(pending_tx, args.freq, args.datr, args.power), peer)
                log.info("gesendet: %r auf %.3f MHz %s, %d dBm",
                         pending_tx, args.freq, args.datr, args.power)
                pending_tx = None

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
