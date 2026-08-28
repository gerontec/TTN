#!/usr/bin/env python3
"""Der dell als eigenstaendiges LoRaWAN-Geraet -- ohne eigenen Funkchip.

Der dell hat kein LoRa-Modul. Was er bisher funkte, ging entweder als
Ebyte-Rahmen ueber den zweiten Paket-Forwarder (`lora_raw.py`, UDP 1702) oder
als Downlink an ein fremdes Geraet (`crisis_bcast.py`). In beiden Faellen ist er
Absender ohne Identitaet: kein DevEUI, keine Sitzung, kein Eintrag in einer
Geraeteliste. Am 28.08.2026 fiel genau das auf -- der dell fehlt in jeder
Uebersicht, obwohl er der aktivste Sender im Netz ist.

Hier bekommt er eine Identitaet. `--anlegen` traegt ihn im lokalen ChirpStack
als ABP-Geraet ein (eigene Anwendung, eigenes Profil, selbst gewuerfelte
Sitzungsschluessel), `--senden` baut daraus einen echten LoRaWAN-Uplink:
MHDR, DevAddr, FCnt, mit dem AppSKey verschluesselte Nutzlast und ein MIC ueber
den NwkSKey. Was dabei herauskommt, ist von einem Rahmen aus einem echten
Knoten nicht zu unterscheiden -- er entsteht nur in Software statt in einem
SX1262.

**Zwei Wege, und sie tun Verschiedenes.** Der Unterschied ist keine Feinheit,
sondern der Kern der Sache:

* `--weg luft` gibt den Rahmen dem Gateway zum Senden (MQTT
  `eu868/gateway/<id>/command/down`, Polaritaet **nicht** invertiert, also
  Uplink-Polaritaet). Er geht wirklich in die Luft, und jedes Gateway in
  Reichweite hoert ihn -- **nur das sendende nicht**. Ein SX1302 kann waehrend
  des Sendens nicht empfangen, das ist Physik und keine Einstellung. Ueber
  diesen Weg allein taucht der dell im lokalen ChirpStack also *nicht* auf.
  Er taucht auf, wenn ein zweites Gateway ihn hoert -- oder wenn der Pico im
  Repeater-Modus laeuft: der hoert auf 868.1 SF9 und gibt den Rahmen 2 s
  spaeter auf 867.1 wieder aus, wo der DLOS8N zuhoert. Deshalb sind die
  Vorgaben hier 868.1 MHz und SF9.
* `--weg ns` speist denselben Rahmen als Empfangsereignis in den Gateway
  Bridge (`.../event/up`). Der lokale ChirpStack nimmt ihn an wie jeden
  anderen Uplink und zeigt den dell als Geraet -- ohne dass ein einziges Byte
  gefunkt wurde. Das ist der ehrliche Weg fuer "soll in der Liste stehen".

Vorgabe ist `beides`: der Rahmen geht in die Luft *und* der Netzwerkserver
sieht ihn. Kommt er zusaetzlich ueber den Repeater zurueck, verwirft ChirpStack
die Kopie als Wiederholung desselben FCnt -- doppelt gezaehlt wird nichts.

Der Zaehler lebt in ~/.config/pseudo-lorawan/zustand.json, die Schluessel
daneben in schluessel.json (0600). Ein Uplink mit einem schon benutzten FCnt
wird vom Netzwerkserver als Replay verworfen, deshalb wird nach jedem Senden
sofort geschrieben, auch wenn das Senden danach scheitert.

    ./pseudo-lorawan.py --anlegen
    ./pseudo-lorawan.py --senden "dell meldet sich"
    ./pseudo-lorawan.py --senden hallo --weg ns --port 2
    ./pseudo-lorawan.py --zeigen

Alles ausser --anlegen kommt ohne ChirpStack-API aus; gebraucht werden nur der
MQTT-Broker und die Schluesseldatei.
"""
import argparse
import base64
import json
import os
import random
import secrets
import struct
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.publish as publish
from cryptography.hazmat.primitives import cmac
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# --- feste Kennungen --------------------------------------------------------
# Die DevEUI ist frei gewaehlt ("DELL" + laufende Nummer), so wie beim Pico
# ("PICO" + 0E22): ein Softwaregeraet hat keine vom Hersteller.
DEV_EUI = "44454c4c00000001"
# Die DevAddr ebenso -- bewusst *ausserhalb* von 260B0000/16. Dieser Block
# gehoert TTN, und was von dort kommt, soll unterscheidbar bleiben von dem,
# was der dell sich selbst gibt.
DEV_ADDR = "01de1100"
APP_NAME = "dell"
PROFILE_NAME = "dell-abp-eu868"
DEV_NAME = "pseudo-lorawan"
TENANT = "d2d00763-756f-4da6-91d4-57204a065051"

GATEWAY = "a84041ffff27e318"
BROKER = "127.0.0.1"
TOPIC_DOWN = "eu868/gateway/%s/command/down"
TOPIC_UP = "eu868/gateway/%s/event/up"

# 868.1 ist der Vorgabekanal, weil der Pico-Repeater genau dort hoert
# (LWRPT_RX_FREQ_MHZ in lorawanparms.h). SF9 aus demselben Grund.
FREQ_MHZ = 868.1
SF = 9
BW_KHZ = 125
# 14 dBm ERP, das Limit in 868.0-868.6. Der Forwarder deckelt selbst, aber ein
# Wert, den er ablehnt, faellt lautlos aus.
POWER_DBM = 14

VERZ = os.path.expanduser("~/.config/pseudo-lorawan")
DATEI_SCHLUESSEL = os.path.join(VERZ, "schluessel.json")
DATEI_ZUSTAND = os.path.join(VERZ, "zustand.json")

# EU868-Uplinkkanaele, fuer --hopfen
KANAELE = [868.1, 868.3, 868.5, 867.1, 867.3, 867.5, 867.7, 867.9]


# --- LoRaWAN-Rahmenbau ------------------------------------------------------
# Alles nach LoRaWAN 1.0.3, Abschnitt 4. Bewusst von Hand statt mit einer
# Bibliothek: es sind dreissig Zeilen, und wer den Rahmen spaeter debuggen
# muss, will sie sehen koennen.

def aes_ecb(schluessel: bytes, block: bytes) -> bytes:
    c = Cipher(algorithms.AES(schluessel), modes.ECB()).encryptor()
    return c.update(block) + c.finalize()


def nutzlast_verschluesseln(app_s_key: bytes, dev_addr: bytes, fcnt: int,
                            daten: bytes, richtung: int = 0) -> bytes:
    """FRMPayload-Verschluesselung (1.0.3, 4.3.3.1).

    Kein Blockchiffre-Modus im ueblichen Sinn: aus Zaehlerbloecken wird ein
    Schluesselstrom erzeugt und mit der Nutzlast XOR-verknuepft. Deshalb ist
    Ver- und Entschluesseln dieselbe Operation.
    """
    aus = bytearray()
    for i in range(0, len(daten), 16):
        block = daten[i:i + 16]
        a = (b"\x01" + b"\x00" * 4 + bytes([richtung]) + dev_addr
             + struct.pack("<I", fcnt) + b"\x00" + bytes([i // 16 + 1]))
        s = aes_ecb(app_s_key, a)
        aus += bytes(x ^ y for x, y in zip(block, s))
    return bytes(aus)


def mic(nwk_s_key: bytes, dev_addr: bytes, fcnt: int, nachricht: bytes,
        richtung: int = 0) -> bytes:
    """MIC ueber den B0-Block (1.0.3, 4.4)."""
    b0 = (b"\x49" + b"\x00" * 4 + bytes([richtung]) + dev_addr
          + struct.pack("<I", fcnt) + b"\x00" + bytes([len(nachricht)]))
    c = cmac.CMAC(algorithms.AES(nwk_s_key))
    c.update(b0 + nachricht)
    return c.finalize()[:4]


def uplink_bauen(nwk_s_key: bytes, app_s_key: bytes, dev_addr_hex: str,
                 fcnt: int, port: int, daten: bytes,
                 bestaetigt: bool = False) -> bytes:
    """Ein vollstaendiger PHYPayload eines unbestaetigten Uplinks.

    DevAddr und FCnt stehen im Rahmen little endian, in der Konfiguration aber
    big endian -- die Umdrehung hier ist der haeufigste Fehler beim Selbstbau.
    """
    dev_addr = bytes.fromhex(dev_addr_hex)[::-1]
    mhdr = bytes([0xA0 if bestaetigt else 0x40])
    fctrl = b"\x00"                      # kein ADR, keine FOpts
    verschluesselt = nutzlast_verschluesseln(app_s_key, dev_addr, fcnt, daten)
    mac = (dev_addr + fctrl + struct.pack("<H", fcnt & 0xFFFF)
           + bytes([port]) + verschluesselt)
    nachricht = mhdr + mac
    return nachricht + mic(nwk_s_key, dev_addr, fcnt, nachricht)


# --- Zustand ----------------------------------------------------------------

def schluessel_laden():
    if not os.path.exists(DATEI_SCHLUESSEL):
        sys.exit("keine Schluessel -- erst './pseudo-lorawan.py --anlegen'")
    with open(DATEI_SCHLUESSEL) as f:
        return json.load(f)


def zustand_laden():
    try:
        with open(DATEI_ZUSTAND) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"fcnt": 0, "gesendet": 0}


def zustand_schreiben(z):
    os.makedirs(VERZ, exist_ok=True)
    with open(DATEI_ZUSTAND, "w") as f:
        json.dump(z, f, indent=2)


# --- die zwei Wege ----------------------------------------------------------

def senden_luft(phy: bytes, freq_mhz: float, sf: int, trocken: bool):
    """Dem Gateway zum Senden geben. Uplink-Polaritaet, also nicht invertiert.

    `polarizationInversion` ist der Punkt, an dem ein Downlink zum Uplink
    wird: LoRaWAN-Downlinks laufen invertiert, damit Geraete einander nicht
    hoeren. Wer als Geraet auftreten will, muss sie ausschalten -- sonst
    versteht kein Gateway den Rahmen.
    """
    rahmen = {
        "downlinkId": random.getrandbits(32),
        "gatewayId": GATEWAY,
        "items": [{
            "phyPayload": base64.b64encode(phy).decode(),
            "txInfo": {
                "frequency": int(freq_mhz * 1e6),
                "power": POWER_DBM,
                "modulation": {"lora": {
                    "bandwidth": BW_KHZ * 1000,
                    "spreadingFactor": sf,
                    "codeRate": "CR_4_5",
                    "polarizationInversion": False,
                }},
                "timing": {"immediately": {}},
            },
        }],
    }
    ziel = TOPIC_DOWN % GATEWAY
    if trocken:
        print("  [trocken] %s" % ziel)
        return
    publish.single(ziel, json.dumps(rahmen), hostname=BROKER, qos=0)
    print("  Luft:  %.1f MHz SF%d, %d dBm, %d B ueber Gateway %s"
          % (freq_mhz, sf, POWER_DBM, len(phy), GATEWAY))


def senden_ns(phy: bytes, freq_mhz: float, sf: int, trocken: bool):
    """Als Empfangsereignis in den Gateway Bridge legen.

    Kein Funk: der Rahmen geht denselben Weg, den ein wirklich gehoerter
    Uplink ab dem Bridge nimmt. RSSI und SNR sind erfunden und als solche
    erkennbar (-1 dBm gibt es in der Luft nicht) -- wer die Zahlen spaeter in
    der Datenbank sieht, soll sofort wissen, dass hier niemand gefunkt hat.
    """
    ereignis = {
        "phyPayload": base64.b64encode(phy).decode(),
        "txInfo": {
            "frequency": int(freq_mhz * 1e6),
            "modulation": {"lora": {
                "bandwidth": BW_KHZ * 1000,
                "spreadingFactor": sf,
                "codeRate": "CR_4_5",
            }},
        },
        "rxInfo": {
            "gatewayId": GATEWAY,
            "uplinkId": random.getrandbits(16),
            "gwTime": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"),
            "rssi": -1,
            "snr": 12.0,
            "channel": 0,
            "context": base64.b64encode(
                struct.pack(">I", int(time.time()) & 0xFFFFFFFF)).decode(),
            "crcStatus": "CRC_OK",
        },
    }
    ziel = TOPIC_UP % GATEWAY
    if trocken:
        print("  [trocken] %s" % ziel)
        return
    publish.single(ziel, json.dumps(ereignis), hostname=BROKER, qos=0)
    print("  NS:    als Empfang eingespeist (RSSI -1 = nicht gefunkt)")


# --- ChirpStack: Geraet anlegen ---------------------------------------------

def anlegen():
    import grpc
    from chirpstack_api import api
    from chirpstack_api import common

    def token():
        with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
            for zeile in f:
                if zeile.startswith("CHIRPSTACK_TOKEN="):
                    return zeile.strip().split("=", 1)[1]
        sys.exit("kein ChirpStack-Token gefunden")

    chan = grpc.insecure_channel("127.0.0.1:8090")
    auth = [("authorization", "Bearer " + token())]

    # Anwendung. Erst suchen, dann anlegen: ChirpStack erlaubt gleiche Namen
    # und meldet kein Duplikat -- ein zweiter Lauf liesse sonst eine leere
    # Huelle zurueck (dieselbe Falle wie in cs_pico.py).
    appsvc = api.ApplicationServiceStub(chan)
    liste = appsvc.List(api.ListApplicationsRequest(limit=100,
                                                    tenant_id=TENANT),
                        metadata=auth)
    app_id = next((a.id for a in liste.result if a.name == APP_NAME), None)
    if app_id:
        print("[hat] Anwendung %s" % APP_NAME)
    else:
        r = api.CreateApplicationRequest()
        r.application.name = APP_NAME
        r.application.description = ("Der dell selbst -- Rahmen aus Software, "
                                     "gefunkt vom Gateway")
        r.application.tenant_id = TENANT
        app_id = appsvc.Create(r, metadata=auth).id
        print("[neu] Anwendung %s" % APP_NAME)

    # Profil: ABP, kein Join. Die RX-Fenster stehen auf den EU868-Vorgaben --
    # gebraucht werden sie nur, wenn jemand dem dell antwortet.
    dpsvc = api.DeviceProfileServiceStub(chan)
    liste = dpsvc.List(api.ListDeviceProfilesRequest(limit=100,
                                                     tenant_id=TENANT),
                       metadata=auth)
    dp_id = next((x.id for x in liste.result if x.name == PROFILE_NAME), None)
    if dp_id:
        print("[hat] Profil %s" % PROFILE_NAME)
    else:
        r = api.CreateDeviceProfileRequest()
        p = r.device_profile
        p.name = PROFILE_NAME
        p.description = "dell als Softwaregeraet, ABP, EU868, Klasse A"
        p.tenant_id = TENANT
        p.region = common.EU868
        p.mac_version = common.LORAWAN_1_0_3
        p.reg_params_revision = common.A
        p.adr_algorithm_id = "default"
        # Kein OTAA: ein Softwaregeraet joint nicht, es bekommt seine Sitzung
        # hier eingetragen und behaelt sie.
        p.supports_otaa = False
        p.supports_class_b = False
        p.supports_class_c = False
        p.abp_rx1_delay = 1
        p.abp_rx1_dr_offset = 0
        p.abp_rx2_dr = 0
        p.abp_rx2_freq = 869525000
        p.payload_codec_runtime = api.CodecRuntime.JS
        p.payload_codec_script = (
            "function decodeUplink(input) {\n"
            "  return { data: { text: String.fromCharCode.apply("
            "null, input.bytes) } };\n"
            "}\n")
        dp_id = dpsvc.Create(r, metadata=auth).id
        print("[neu] Profil %s" % PROFILE_NAME)

    # Geraet
    devsvc = api.DeviceServiceStub(chan)
    try:
        devsvc.Get(api.GetDeviceRequest(dev_eui=DEV_EUI), metadata=auth)
        print("[hat] Geraet %s" % DEV_EUI)
    except grpc.RpcError:
        r = api.CreateDeviceRequest()
        r.device.dev_eui = DEV_EUI
        r.device.join_eui = "0000000000000000"
        r.device.name = DEV_NAME
        r.device.description = ("Der dell ohne Funkchip: Rahmen in Software, "
                               "gesendet ueber das Gateway")
        r.device.application_id = app_id
        r.device.device_profile_id = dp_id
        devsvc.Create(r, metadata=auth)
        print("[neu] Geraet %s (%s)" % (DEV_NAME, DEV_EUI))

    # Schluessel: einmal wuerfeln, dann liegen bleiben. Ein neuer Wurf wuerde
    # die Sitzung im Netzwerkserver ungueltig machen, ohne dass das Skript es
    # merkt -- deshalb wird eine vorhandene Datei nie ueberschrieben.
    os.makedirs(VERZ, exist_ok=True)
    if os.path.exists(DATEI_SCHLUESSEL):
        s = schluessel_laden()
        print("[hat] Schluessel in %s" % DATEI_SCHLUESSEL)
    else:
        s = {"dev_eui": DEV_EUI, "dev_addr": DEV_ADDR,
             "nwk_s_key": secrets.token_hex(16),
             "app_s_key": secrets.token_hex(16)}
        with open(DATEI_SCHLUESSEL, "w") as f:
            json.dump(s, f, indent=2)
        os.chmod(DATEI_SCHLUESSEL, 0o600)
        print("[neu] Schluessel gewuerfelt -> %s" % DATEI_SCHLUESSEL)

    # Sitzung eintragen. Wie in cs_abp_from_ttn.py: 1.0.x kennt genau einen
    # NwkSKey, den ChirpStack in drei Feldern fuehrt.
    akt = api.DeviceActivation()
    akt.dev_eui = DEV_EUI
    akt.dev_addr = s["dev_addr"]
    akt.f_nwk_s_int_key = s["nwk_s_key"]
    akt.s_nwk_s_int_key = s["nwk_s_key"]
    akt.nwk_s_enc_key = s["nwk_s_key"]
    akt.app_s_key = s["app_s_key"]
    z = zustand_laden()
    akt.f_cnt_up = z.get("fcnt", 0)
    akt.n_f_cnt_down = 0
    akt.a_f_cnt_down = 0
    devsvc.Activate(api.ActivateDeviceRequest(device_activation=akt),
                    metadata=auth)
    nach = devsvc.GetActivation(api.GetDeviceActivationRequest(dev_eui=DEV_EUI),
                                metadata=auth).device_activation
    print("[ok]  Sitzung: DevAddr %s, FCntUp %d"
          % (nach.dev_addr, nach.f_cnt_up))
    zustand_schreiben(z)


# --- Hauptteil --------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Der dell als LoRaWAN-Geraet ohne eigenen Funkchip")
    ap.add_argument("--anlegen", action="store_true",
                    help="Anwendung, Profil, Geraet und ABP-Sitzung im "
                         "lokalen ChirpStack anlegen (idempotent)")
    ap.add_argument("--senden", metavar="TEXT",
                    help="einen Uplink mit diesem Text absetzen")
    ap.add_argument("--hex", metavar="HEX",
                    help="statt Text rohe Bytes senden")
    ap.add_argument("--port", type=int, default=1, help="FPort (Vorgabe 1)")
    ap.add_argument("--weg", choices=("luft", "ns", "beides"), default="beides",
                    help="luft = das Gateway funkt den Rahmen; ns = als "
                         "Empfang einspeisen; beides (Vorgabe)")
    ap.add_argument("--freq", type=float, default=FREQ_MHZ,
                    help="Sendefrequenz in MHz (Vorgabe %.1f, der Kanal, auf "
                         "dem der Pico-Repeater hoert)" % FREQ_MHZ)
    ap.add_argument("--sf", type=int, default=SF,
                    help="Spreizfaktor (Vorgabe %d)" % SF)
    ap.add_argument("--hopfen", action="store_true",
                    help="Kanal zufaellig aus den acht EU868-Kanaelen waehlen, "
                         "wie ein echtes Geraet")
    ap.add_argument("--fcnt", type=int,
                    help="FCnt erzwingen statt aus dem Zustand zu zaehlen")
    ap.add_argument("--zeigen", action="store_true",
                    help="Kennungen und Zaehlerstand ausgeben")
    ap.add_argument("--trocken", action="store_true",
                    help="Rahmen bauen und zeigen, nichts veroeffentlichen")
    a = ap.parse_args()

    if a.anlegen:
        anlegen()
        if not (a.senden or a.hex):
            return

    if a.zeigen:
        s = schluessel_laden()
        z = zustand_laden()
        print("DevEUI   %s" % s["dev_eui"])
        print("DevAddr  %s" % s["dev_addr"])
        print("FCntUp   %d (naechster Uplink: %d)"
              % (z.get("fcnt", 0), z.get("fcnt", 0)))
        print("gesendet %d" % z.get("gesendet", 0))
        print("Gateway  %s, Broker %s" % (GATEWAY, BROKER))
        return

    if not (a.senden is not None or a.hex):
        ap.error("nichts zu tun -- --anlegen, --senden, --hex oder --zeigen")

    if a.hex:
        try:
            daten = bytes.fromhex(a.hex.replace(" ", ""))
        except ValueError:
            sys.exit("--hex will eine gerade Zahl von Hexziffern")
    else:
        daten = a.senden.encode()
    if not 1 <= a.port <= 223:
        sys.exit("FPort muss zwischen 1 und 223 liegen")

    s = schluessel_laden()
    z = zustand_laden()
    fcnt = a.fcnt if a.fcnt is not None else z.get("fcnt", 0)
    freq = random.choice(KANAELE) if a.hopfen else a.freq

    phy = uplink_bauen(bytes.fromhex(s["nwk_s_key"]),
                       bytes.fromhex(s["app_s_key"]),
                       s["dev_addr"], fcnt, a.port, daten)

    print("Uplink FCnt %d, FPort %d, %d B Nutzlast, PHY %d B"
          % (fcnt, a.port, len(daten), len(phy)))
    print("  PHY:   %s" % phy.hex())

    # Zaehler *vor* dem Senden fortschreiben: ein zweimal benutzter FCnt ist
    # fuer den Netzwerkserver ein Replay und kostet den Uplink. Ein Zaehler,
    # der bei einem Fehlschlag eine Nummer ueberspringt, kostet nichts --
    # LoRaWAN erlaubt Luecken nach oben.
    if a.fcnt is None and not a.trocken:
        z["fcnt"] = fcnt + 1
        z["gesendet"] = z.get("gesendet", 0) + 1
        z["zuletzt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        zustand_schreiben(z)

    if a.weg in ("luft", "beides"):
        senden_luft(phy, freq, a.sf, a.trocken)
    if a.weg in ("ns", "beides"):
        senden_ns(phy, freq, a.sf, a.trocken)


if __name__ == "__main__":
    main()
