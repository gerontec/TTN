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
  ./lora_raw.py --netid bb           # als Gruppe BB senden statt als 00

Der Steuereingang (UDP 127.0.0.1:1703) nimmt Gruppe und Ziel je Datagramm:

  printf '@bb:hallo'      | nc -u -w0 127.0.0.1 1703   # NETID BB
  printf '@/ffff:hallo'   | nc -u -w0 127.0.0.1 1703   # Rundruf
  printf '@bb/ffff:hallo' | nc -u -w0 127.0.0.1 1703   # beides

Ohne Praefix gelten --netid und --ziel. Damit laesst sich in jede Gruppe und
an jedes Ziel senden, ohne den Dienst neu zu starten -- noetig etwa, um die
Rueckrichtung des E90-Relais (BB -> 00) auszuloesen, die sich sonst mangels
Sender auf BB nie zeigt.
"""
import argparse
import base64
import binascii
import glob
import json
import logging
import re
import select
import socket
import sys
import time

PORT = 1702
RAW_FREQ = 868.125          # chan_Lora_std, siehe /etc/lora/global_conf.json
RAW_DATR = "SF11BW500"      # dito -- Ebyte-Profil seit 17.08.2026. Stand hier
                            # bis dahin auf SF7BW125: Downlinks gingen dann mit
                            # falscher Modulation hinaus und niemand hoerte sie.
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
#   2 Byte Zieladresse | Laenge | Nutzlast, XOR 0x12
# Byte 5-6 ist das *Ziel*, nicht der Absender -- einen Absender enthaelt der
# Rahmen ueberhaupt nicht. Dass es wie eine Absenderkennung wirkt, liegt daran,
# dass ein Modul im Transparentmodus seine eigene Adresse ins Zielfeld setzt.
# Das Pruefbytepaar ist eine XOR-Summe ueber die Nutzlast, kein Zaehler:
# gleiche Nutzlast ergibt Byte fuer Byte denselben Rahmen.
EBYTE_MAGIC = 0x2C
EBYTE_KOPF = 8
EBYTE_XOR = 0x12            # Weissung, konstant -- nicht die Kanalnummer
EBYTE_KANAL = 18            # 850.125 + 18 = 868.125 MHz, Werksdefault der 900er
EBYTE_NETID = 0x00          # Vorgabe-Quellgruppe, ueberschreibbar mit --netid
                            # und je Datagramm mit dem Praefix @hh: am
                            # Steuereingang. Der E90 leitet als Zwei-Wege-
                            # Relais zwischen 0x00 und 0xBB weiter (ADDH/ADDL
                            # sind im Relaismodus keine Adressen, sondern das
                            # NETID-Paar). Nach Gruppe BB kommt man damit auf
                            # zwei Wegen: auf 0x00 bleiben und das Relais
                            # tragen lassen, oder direkt als 0xBB senden --
                            # letzteres ist der einzige Weg, die Rueckrichtung
                            # des Relais (BB -> 00) ueberhaupt auszuloesen.

# Praefix am Steuereingang, mit dem ein einzelnes Datagramm Gruppe und Ziel
# setzt -- beides einzeln weglassbar:
#   @bb:Nachricht        NETID 0xBB, Ziel aus --ziel
#   @/ffff:Nachricht     NETID aus --netid, Ziel FFFF (Rundruf)
#   @bb/ffff:Nachricht   beides
# Bewusst ein Zeichen, das in keinem Rahmenformat des Netzes vorkommt (die
# tragen C>, A> oder vier Hexstellen vor dem >). Wer wirklich eine Nutzlast
# senden will, die so beginnt, muss --netid bzw. --ziel nehmen.
PRAEFIX = re.compile(rb"^@([0-9a-fA-F]{0,2})(?:/([0-9a-fA-F]{4}))?:")

# --- Geraeteerkennung -----------------------------------------------------
# Jede Station traegt ihre Kennung im Rahmen: Ebyte in der Adresse Byte 5-6,
# Text als vier Hexstellen vor dem ">". Beide sind vier Hexstellen, also
# dieselbe Tabelle. Ueberschreibbar durch /etc/lora/geraete.json, damit neue
# Knoten ohne Codeaenderung dazukommen.
# Adressen der Knoten. Bei Ebyte-Rahmen ist das die *Ziel*adresse, beim
# Textformat die Absenderkennung -- zwei verschiedene Dinge, dieselbe Tabelle.
GERAETE_DATEI = "/etc/lora/geraete.json"
# Nur Stationen, die tatsaechlich in Betrieb sind. Unbekannte Kennungen
# bleiben ohnehin sichtbar -- "geraet" ist dann null, "absender" steht da.
GERAETE = {
    "E09C": "dell-3660 (aus der MAC cc:96:e5:01:e0:9c)",
    "2201": "E22-900T am Notebook (NETID 00)",
    "0C2B": "Pico SX1262 am Notebook (Gruppe BB)",
    "FFFF": "Ebyte Werksadresse / Monitor",
    # Im Relaismodus ist ADDH/ADDL keine Adresse mehr, sondern ein
    # NETID-Weiterleitungspaar: 0000 heisst "von NETID 0 nach NETID 0". Der
    # E90 taucht deshalb nie selbst als Absender auf -- er reicht die Rahmen
    # unveraendert durch, mit der Kennung des urspruenglichen Senders.
    "0000": "E90-DTU(900SL33), Relais (NETID-Paar 0->0)",
}
# Selbstempfang: das Gateway hoert die eigene Aussendung. Gemessen -16 dBm bei
# nur -59 Hz Versatz -- derselbe Oszillator. Eine Weitergabe traegt den
# Quarzversatz der Gegenstelle, ein Ebyte-Modul rund -27 kHz.
SELBST_FOFF_HZ = 300

# Broadcast. Laut Handbuch 7.1.x traegt ein Broadcast-Paket die Adresse FFFF,
# und *dann filtert der Empfaenger nicht* -- unabhaengig von seiner eigenen
# Adresse und sogar bei abweichender NETID ("Network code filtering has lower
# priority than broadcast addresses"). Wer sicher gehoert werden will, sendet
# damit. Der Preis: die eigene Kennung steht dann nicht mehr im Rahmen, der
# Selbstfilter kann sich nicht auf die Adresse stuetzen -- dafuer der
# Kurzzeitspeicher unten.
EBYTE_BROADCAST = "FFFF"
GESENDET_SPERRE_S = 120


def geraete_laden():
    try:
        with open(GERAETE_DATEI) as f:
            GERAETE.update({k.upper(): v for k, v in json.load(f).items()})
    except (OSError, ValueError):
        pass
    return GERAETE


class Gesendet:
    """Was wir selbst gefunkt haben, kurz gemerkt.

    Der Selbstfilter kann sich nicht mehr auf die Absenderadresse stuetzen,
    sobald wir als Broadcast senden -- dann steht FFFF im Rahmen wie bei jedem
    anderen auch. Der Inhalt taugt aber immer: ein Ebyte-Rahmen ist bei
    gleicher Nutzlast byteweise identisch, weil das Pruefbyte aus der Nutzlast
    gerechnet wird und nicht hochzaehlt.
    """

    def __init__(self, sperre_s=GESENDET_SPERRE_S):
        self.sperre_s = sperre_s
        self._eintraege = {}

    def merken(self, roh):
        self._eintraege[bytes(roh)] = time.time()

    def war_das_ich(self, roh):
        jetzt = time.time()
        for k, t in list(self._eintraege.items()):
            if jetzt - t > self.sperre_s:
                del self._eintraege[k]
        return bytes(roh) in self._eintraege


def geraet_zu(kennung):
    """Klarname zur Kennung, oder None wenn unbekannt."""
    return GERAETE.get(kennung.upper()) if kennung else None


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


def ist_ebyte(roh):
    """Kennung in Byte 0 und Laengenangabe in Byte 7 zusammen sind ein
    belastbares Merkmal, das Textpakete nicht zufaellig erfuellen."""
    return (len(roh) > EBYTE_KOPF and roh[0] == EBYTE_MAGIC
            and roh[EBYTE_KOPF - 1] == len(roh) - EBYTE_KOPF)


def ebyte_ziel(roh):
    """**Ziel**adresse als vier Hexstellen, oder None wenn kein Ebyte-Rahmen.

    Wichtig, und lange falsch verstanden: Byte 5-6 ist die Adresse des
    **Empfaengers**, nicht des Senders. Handbuch der T22U-Serie, 4.1
    "Targeted launch": ein Sender auf 0x0001 schickt `00 03 | 04 | Daten` --
    Zieladresse, Zielkanal, Nutzlast. Nur das Modul mit Adresse 0x0003 auf
    Kanal 4 gibt etwas aus, die anderen schweigen. Die eigene Adresse des
    Senders taucht im Paket ueberhaupt nicht auf.

    Ein Ebyte-Rahmen sagt also, **an wen** er geht -- nie, von wem er kam.
    """
    return "%02X%02X" % (roh[5], roh[6]) if ist_ebyte(roh) else None


def ebyte_netid(roh):
    """NETID aus Byte 4, oder None.

    Seit der E90 als Zwei-Wege-Relais zwischen NETID 0x00 und 0xBB laeuft, ist
    das der **eindeutige** Unterschied zwischen Original und Weitergabe: das
    Relais schreibt die Ziel-NETID in den Rahmen, sonst wuerden die Empfaenger
    der Gegengruppe ihn verwerfen. Vorher liess sich das nur aus dem
    Quarzversatz erschliessen -- ein Indizienbeweis, der mehrfach in die Irre
    fuehrte.
    """
    return roh[4] if ist_ebyte(roh) else None


def ebyte_fuer_gruppe(roh, netid):
    """Wuerde ein Knoten unserer Gruppe diesen Rahmen ausgeben?

    Zwei Wege hinein, und der zweite sticht den ersten: gleiche NETID, oder
    Rundruf an FFFF -- "network code filtering has lower priority than
    broadcast addresses". Kein Ebyte-Rahmen: None, die Frage stellt sich nicht.
    """
    if not ist_ebyte(roh):
        return None
    return roh[4] == (netid & 0xFF) or ebyte_ziel(roh) == EBYTE_BROADCAST


def ebyte_nutzlast(roh):
    """Klartext-Nutzlast aus einem Ebyte-Rahmen (XOR-Weissung zuruecknehmen)."""
    laenge = roh[EBYTE_KOPF - 1]
    return bytes(b ^ EBYTE_XOR for b in roh[EBYTE_KOPF:EBYTE_KOPF + laenge])


def netid_lesen(wert):
    """NETID von der Kommandozeile, immer hexadezimal.

    Im ganzen Netz heissen die Gruppen hex -- 00 und BB -- also wird auch hier
    hex gelesen: '11' ist 0x11, nicht elf. Ein '0x' davor ist erlaubt. Wer
    dezimal denkt, faellt nicht still herein: '187' ist als Hexzahl zu gross
    und wird abgewiesen.
    """
    t = wert.lower()
    if t.startswith("0x"):
        t = t[2:]
    if not 1 <= len(t) <= 2 or set(t) - set("0123456789abcdef"):
        raise argparse.ArgumentTypeError(
            "NETID als ein oder zwei Hexstellen angeben, z.B. bb")
    return int(t, 16)


def praefix_abtrennen(roh, netid_vorgabe, ziel_vorgabe):
    """'@bb/ffff:Text' -> (0xBB, 'FFFF', b'Text').

    Fehlt ein Teil, gilt die Vorgabe; ohne Praefix bleibt alles unveraendert.
    """
    treffer = PRAEFIX.match(roh)
    if not treffer:
        return netid_vorgabe, ziel_vorgabe, roh
    netid, ziel = treffer.group(1), treffer.group(2)
    return (int(netid, 16) if netid else netid_vorgabe,
            ziel.decode().upper() if ziel else ziel_vorgabe,
            roh[treffer.end():])


def ebyte_rahmen(nutz, kennung, netid=EBYTE_NETID):
    """Nutzlast in einen Ebyte-Rahmen packen.

    Ein E22/E90 verwirft alles, was nicht seinem Format entspricht -- Klartext
    kommt dort gar nicht erst zur seriellen Seite. Wer ueber das Gateway einen
    Ebyte-Knoten erreichen will, muss deshalb selbst rahmen.

        0x2C | Kanal | xx | xx^0xA1 | NETID | ADDH | ADDL | Laenge | Nutzlast

    xx ist eine XOR-Summe ueber die Nutzlast, kein Zaehler. ADDH/ADDL sind die
    *Zieladresse*; ein Absender steht im Rahmen nicht.

    netid waehlt die Gruppe, in der der Rahmen unterwegs ist. Ein Empfaenger
    gibt nur aus, was seine eigene NETID traegt -- ausser bei Broadcast FFFF,
    der die Netzkennung ueberstimmt. Damit ist die NETID die einzige Stellung,
    mit der dell gezielt in eine Gruppe sendet, statt sich vom Relais
    hinuebertragen zu lassen.
    """
    if isinstance(nutz, str):
        nutz = nutz.encode()
    nutz = nutz[:255]
    xx = 0
    for b in nutz:
        xx ^= b
    xx = (xx ^ 0xA0) & 0xFF
    adr = int(kennung, 16) & 0xFFFF
    kopf = bytes([EBYTE_MAGIC, EBYTE_KANAL, xx, xx ^ 0xA1, netid & 0xFF,
                  (adr >> 8) & 0xFF, adr & 0xFF, len(nutz)])
    return kopf + bytes(b ^ EBYTE_XOR for b in nutz)


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


def txpk(text, freq, datr, power, prea=None):
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
        # Praeambel. Ohne Angabe nimmt der Forwarder seinen Vorgabewert (8).
        # Ein Ebyte-Empfaenger braucht genug Symbole zum Einrasten; sendet die
        # Gegenstelle laenger, als wir es tun, hoert sie uns nie.
        **({"prea": prea} if prea else {}),
        "size": len(data),
        "data": base64.b64encode(data).decode(),
    }}).encode()


def handle_rxpk(pkt, args, mq, gesendet=None):
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

    # Ebyte-Rahmen aufloesen: der Absender steht in der Adresse, die Nutzlast
    # ist verweisst. Ohne das bliebe auf MQTT beides leer -- und ein Verbraucher
    # koennte nicht einmal sagen, von wem ein Paket kam.
    formt = "text" if absender else "roh"
    ziel = None
    if ist_ebyte(raw):
        ziel = ebyte_ziel(raw)
        absender = None          # Ebyte nennt den Sender nicht
        nutz = ebyte_nutzlast(raw)
        formt = "ebyte"

    # Selbstfilter. Jedes Geraet muss die eigenen Pakete erkennen: was ueber
    # ein Relais zurueckkommt, ist kein neuer Verkehr. Beide Formate tragen
    # die Absenderkennung mit -- Text als vier Hexstellen vor dem ">", Ebyte
    # als Adresse in Byte 5-6. Ohne diesen Filter wuerde jede Bruecke von
    # MQTT zurueck auf den Steuereingang eine Endlosschleife erzeugen.
    # Eigenes Paket: entweder traegt es unsere Kennung, oder wir haben genau
    # diesen Rahmen kurz zuvor selbst gefunkt (greift auch bei Broadcast).
    # Eigenes Paket. Bei Textrahmen steht die Absenderkennung drin, bei
    # Ebyte-Rahmen nicht -- dort traegt allein der Inhaltsspeicher, denn die
    # Adresse im Rahmen ist das Ziel und sagt ueber die Herkunft nichts aus.
    eigen = bool(absender) and absender.upper() == args.id.upper()
    if gesendet is not None and gesendet.war_das_ich(raw):
        eigen = True
    foff = pkt.get("foff")
    # Selbstempfang von Weitergabe trennen: gleiche Kennung sagt nur, dass es
    # von uns stammt -- ob es ueber ein Relais kam, verraet erst der Versatz.
    selbst = eigen and foff is not None and abs(foff) < SELBST_FOFF_HZ
    if args.self_filter and eigen:
        quelle = absender
        log.info("%.3f MHz  %-9s RSSI %-5s %s von %s%s, %d B -- gefiltert",
                 freq, pkt.get("datr", "?"), pkt.get("rssi", "?"),
                 "Selbstempfang (foff %s Hz)" % foff if selbst
                 else "Echo ueber ein Relais", quelle,
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
            # Der Frequenzversatz unterscheidet zwei Sender desselben Inhalts:
            # ein Ebyte-Modul liegt gemessen ~27 kHz daneben, das Gateway und
            # ein SX1262 nur wenige hundert Hertz. Damit laesst sich eine
            # Weitergabe vom Original trennen -- und Selbstempfang erkennen.
            "foff": pkt.get("foff"),
            # Zeitstempel des Konzentrators in Mikrosekunden. Damit laesst sich
            # der Abstand zwischen einem Original und seiner Weitergabe messen
            # -- und damit klaeren, ob der einzelne Demodulator von
            # chan_Lora_std beide ueberhaupt nacheinander nehmen kann.
            "tmst": pkt.get("tmst"),
            "absender": absender, "geraet": geraet_zu(absender),
            "ziel": ziel, "zielgeraet": geraet_zu(ziel),
            "netid": ebyte_netid(raw),
            # Gehoert der Rahmen in unsere Gruppe? dell ist mit --netid selbst
            # Mitglied einer Gruppe, und ein echter Ebyte-Knoten wuerde genau
            # nach dieser Regel entscheiden, ob er die Nutzlast ausgibt:
            # NETID gleich -- oder Rundruf, denn Broadcast hat Vorrang vor der
            # Netzkennung. Damit ist im Datensatz sichtbar, was ein Knoten
            # unserer Gruppe tatsaechlich zu sehen bekaeme; ein Original aus
            # der Nachbargruppe ist "fremd", erst die Relaiskopie "eigen".
            "fuer_uns": ebyte_fuer_gruppe(raw, args.netid),
            "sprung": sprung, "format": formt, "selbstempfang": selbst,
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
    ap.add_argument("--prea", type=int, default=None,
                    help="Praeambellaenge in Symbolen; ohne Angabe der "
                         "Vorgabewert des Forwarders (8)")
    ap.add_argument("--txfreq", type=float, default=None,
                    help="Sendefrequenz in MHz, Vorgabe = --freq. Ein Ebyte "
                         "hoert mit demselben Quarz, mit dem er sendet -- "
                         "misst man an seinen Paketen foff, gleicht man den "
                         "Versatz hier aus (z.B. 868.0973 bei -27.7 kHz)")
    ap.add_argument("--ziel", dest="sendeadresse", default=EBYTE_BROADCAST,
                    help="Zieladresse im gesendeten Ebyte-Rahmen. FFFF "
                         "adressiert die ganze Gruppe auf dem Kanal, eine "
                         "konkrete Adresse genau einen Knoten darin")
    ap.add_argument("--netid", type=netid_lesen, default=EBYTE_NETID,
                    help="NETID der gesendeten Ebyte-Rahmen, hexadezimal "
                         "(Vorgabe 00 = Gruppe A, bb = Gruppe B). Einzelne "
                         "Datagramme am Steuereingang setzen sie mit @bb:")
    ap.add_argument("--no-ebyte", dest="ebyte", action="store_false",
                    help="ungerahmt senden; ein E22/E90 verwirft das, nur fuer "
                         "Gegenstellen die rohes LoRa lesen")
    ap.add_argument("--no-self-filter", dest="self_filter",
                    action="store_false",
                    help="eigene Pakete NICHT herausfiltern; nur zum Messen, "
                         "im Regelbetrieb droht sonst eine Rueckkopplung")
    ap.add_argument("--ctrl-port", type=int, default=1703,
                    help="lokaler Steuereingang; was hier ankommt, wird gefunkt")
    ap.add_argument("--datr", default=RAW_DATR,
                    help="Modulation des Rohkanals; muss zu chan_Lora_std "
                         "im global_conf.json des Gateways passen")
    ap.add_argument("--power", type=int, default=14,
                    help="dBm ERP; 14 = 25 mW, das Limit in 868.0-868.6")
    args = ap.parse_args()

    if args.id is None:
        args.id = eigene_kennung()
    if args.txfreq is None:
        args.txfreq = args.freq

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

    geraete_laden()
    log.info("eigene Kennung %s (aus der MAC), Selbstfilter %s, senden %s",
             args.id, "an" if args.self_filter else "AUS",
             "als Ebyte-Rahmen" if args.ebyte else "ungerahmt")

    def mit_kennung(roh, netid=None, ziel=None):
        """Sendefertig machen.

        Im Ebyte-Modus wird gerahmt. Die Adresse im Rahmen ist per Vorgabe
        FFFF, also Broadcast -- laut Handbuch filtert der Empfaenger dann
        nicht, unabhaengig von seiner eigenen Adresse. Ein Textpraefix waere
        hier doppelt gemoppelt. Sonst wie bisher: Befehle und Antworten tragen
        ihr eigenes Praefix, alles andere bekommt die Absenderkennung voran.

        netid/ziel None = die Vorgaben aus --netid und --ziel; der
        Steuereingang reicht hier durch, was am Datagramm stand.
        """
        if args.ebyte:
            roh = ebyte_rahmen(roh,
                               args.sendeadresse if ziel is None else ziel,
                               args.netid if netid is None else netid)
            gesendet.merken(roh)
            return roh
        if roh[:2] in (b"C>", b"A>") or zerlege(roh)[1] is not None:
            return roh
        return args.id.encode() + b">" + roh

    gesendet = Gesendet()
    warteschlange = []
    if args.send:
        netid, ziel, nutz = praefix_abtrennen(args.send.encode(),
                                             args.netid, args.sendeadresse)
        warteschlange.append(mit_kennung(nutz, netid, ziel))

    while True:
        bereit, _, _ = select.select([s, ctrl], [], [], 1.0)
        if ctrl in bereit:
            roh, _ = ctrl.recvfrom(4096)
            netid, ziel, nutz = praefix_abtrennen(roh, args.netid,
                                                 args.sendeadresse)
            roh = mit_kennung(nutz, netid, ziel)
            warteschlange.append(roh)
            log.info("eingereiht (NETID %02x, Ziel %s): %r", netid, ziel, roh)
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
                handle_rxpk(pkt, args, mq, gesendet)

        elif kind == PULL_DATA:
            s.sendto(bytes([data[0]]) + token + bytes([PULL_ACK]), peer)
            if warteschlange:
                naechste = warteschlange.pop(0)
                s.sendto(bytes([data[0]]) + token + bytes([PULL_RESP])
                         + txpk(naechste, args.txfreq, args.datr, args.power, args.prea), peer)
                log.info("gesendet: %r auf %.4f MHz %s, %d dBm, Praeambel %s",
                         naechste, args.txfreq, args.datr, args.power,
                         args.prea or "Vorgabe")

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
