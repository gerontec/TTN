#!/usr/bin/env python3
"""Legt die eigene ABP-Identitaet des Repeaters im lokalen ChirpStack an.

Im Repeater-Modus gibt der Pico fremde Rahmen unveraendert weiter -- veraendern
duerfte er sie nicht, der MIC des Originalgeraets wuerde brechen und der
Netzwerkserver saehe nur noch "No device-session exists for dev_addr". Die
Kennung, welcher Rahmen ueber den Repeater lief, geht deshalb *daneben*
hinaus: als eigener Uplink des Repeaters auf FPort 20 (MODE_REPEAT_ID).

Dafuer braucht er eine zweite Identitaet, unabhaengig von der OTAA-Sitzung des
Knotens: der Bericht wird von Hand gebaut und darf den Zaehler der
RadioLib-Sitzung nicht anfassen.

**skip_fcnt_check ist Absicht.** Der Zaehler des Berichts lebt nur im RAM. Ihn
im Flash zu halten hiesse ein viertes Feld in `Zustand`, und eine geaenderte
Struktur macht jeden gespeicherten Sektor ungueltig (storage.cpp prueft die
Laenge): der Knoten verloere Modus, DevNonces und LoRaWAN-Sitzung auf einen
Schlag, und der naechste OTAA-Join floege als Replay raus. Der Preis ist, dass
dieses eine Geraet keinen Replay-Schutz hat -- fuer eine Diagnose im eigenen
Netz die billigere Seite des Tauschs.

    /home/gh/.venv-chirpstack/bin/python cs_repeater.py

Gibt am Ende die drei Zeilen aus, die nach src/lorawan_secret.h gehoeren.
Vorhandene Schluessel werden nie neu gewuerfelt -- ein neuer Wurf machte die
Sitzung im Netzwerkserver ungueltig, ohne dass der Knoten es merkt.
"""
import json
import os
import secrets
import sys

import grpc
from chirpstack_api import api
from chirpstack_api import common

TENANT = "d2d00763-756f-4da6-91d4-57204a065051"
DEV_EUI = "5049434f00000e23"        # "PICO" + 0E23, neben dem Knoten 0E22
DEV_ADDR = "01de2200"               # wie beim dell ausserhalb von 260B0000/16
APP_NAME = "pico"                   # dieselbe Anwendung wie der Knoten
PROFILE_NAME = "pico-repeater-abp-eu868"
DEV_NAME = "pico-0e22-repeater"
DATEI = os.path.expanduser("~/.config/pseudo-lorawan/repeater.json")

# Vier Byte Kopf, dann neun je Satz: DevAddr, FCnt, RSSI, SNR*4, MType.
CODEC = """
function decodeUplink(input) {
  var b = input.bytes;
  if (input.fPort !== 20 || b.length < 4) return { data: { roh: b } };
  var s8 = function (v) { return v > 127 ? v - 256 : v; };
  var hex = function (v) { return ("0000000" + v.toString(16)).slice(-8); };
  var saetze = [];
  for (var i = 4; i + 8 < b.length; i += 9) {
    saetze.push({
      dev_addr: hex(b[i] | (b[i+1] << 8) | (b[i+2] << 16) | (b[i+3] << 24)),
      f_cnt: b[i+4] | (b[i+5] << 8),
      rssi: s8(b[i+6]),
      snr: s8(b[i+7]) / 4,
      m_type: b[i+8]
    });
  }
  return { data: {
    version: b[0],
    weitergegeben: b[1] | (b[2] << 8),
    anzahl: b[3],
    weitergaben: saetze
  } };
}
"""


def token():
    with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
        for zeile in f:
            if zeile.startswith("CHIRPSTACK_TOKEN="):
                return zeile.strip().split("=", 1)[1]
    sys.exit("kein ChirpStack-Token gefunden")


chan = grpc.insecure_channel("127.0.0.1:8090")
AUTH = [("authorization", "Bearer " + token())]

appsvc = api.ApplicationServiceStub(chan)
dpsvc = api.DeviceProfileServiceStub(chan)
devsvc = api.DeviceServiceStub(chan)

liste = appsvc.List(api.ListApplicationsRequest(limit=100, tenant_id=TENANT),
                    metadata=AUTH)
app_id = next((a.id for a in liste.result if a.name == APP_NAME), None)
if not app_id:
    sys.exit("Anwendung '%s' gibt es nicht -- erst cs_pico.py" % APP_NAME)
print("[ok]  Anwendung %s" % APP_NAME)

liste = dpsvc.List(api.ListDeviceProfilesRequest(limit=100, tenant_id=TENANT),
                   metadata=AUTH)
dp_id = next((x.id for x in liste.result if x.name == PROFILE_NAME), None)
if dp_id:
    print("[hat] Profil %s" % PROFILE_NAME)
else:
    r = api.CreateDeviceProfileRequest()
    p = r.device_profile
    p.name = PROFILE_NAME
    p.description = "Pico im Repeater-Modus, eigene Stimme, ABP, EU868"
    p.tenant_id = TENANT
    p.region = common.EU868
    p.mac_version = common.LORAWAN_1_0_3
    p.reg_params_revision = common.A
    p.adr_algorithm_id = "default"
    p.supports_otaa = False
    p.supports_class_b = False
    p.supports_class_c = False
    p.abp_rx1_delay = 1
    p.abp_rx1_dr_offset = 0
    p.abp_rx2_dr = 0
    p.abp_rx2_freq = 869525000
    p.payload_codec_runtime = api.CodecRuntime.JS
    p.payload_codec_script = CODEC
    dp_id = dpsvc.Create(r, metadata=AUTH).id
    print("[neu] Profil %s" % PROFILE_NAME)

try:
    devsvc.Get(api.GetDeviceRequest(dev_eui=DEV_EUI), metadata=AUTH)
    print("[hat] Geraet %s" % DEV_EUI)
except grpc.RpcError:
    r = api.CreateDeviceRequest()
    r.device.dev_eui = DEV_EUI
    r.device.join_eui = "0000000000000000"
    r.device.name = DEV_NAME
    r.device.description = ("Die eigene Stimme des Repeaters -- sagt, welcher "
                            "Rahmen ueber ihn lief, ohne ihn anzufassen")
    r.device.application_id = app_id
    r.device.device_profile_id = dp_id
    # Siehe Kopf: der Zaehler lebt im RAM des Knotens und faengt nach jedem
    # Stromausfall wieder bei 0 an.
    r.device.skip_fcnt_check = True
    devsvc.Create(r, metadata=AUTH)
    print("[neu] Geraet %s (%s), skip_fcnt_check" % (DEV_NAME, DEV_EUI))

os.makedirs(os.path.dirname(DATEI), exist_ok=True)
if os.path.exists(DATEI):
    with open(DATEI) as f:
        s = json.load(f)
    print("[hat] Schluessel in %s" % DATEI)
else:
    s = {"dev_eui": DEV_EUI, "dev_addr": DEV_ADDR,
         "nwk_s_key": secrets.token_hex(16),
         "app_s_key": secrets.token_hex(16)}
    with open(DATEI, "w") as f:
        json.dump(s, f, indent=2)
    os.chmod(DATEI, 0o600)
    print("[neu] Schluessel gewuerfelt -> %s" % DATEI)

akt = api.DeviceActivation()
akt.dev_eui = DEV_EUI
akt.dev_addr = s["dev_addr"]
akt.f_nwk_s_int_key = s["nwk_s_key"]
akt.s_nwk_s_int_key = s["nwk_s_key"]
akt.nwk_s_enc_key = s["nwk_s_key"]
akt.app_s_key = s["app_s_key"]
akt.f_cnt_up = 0
akt.n_f_cnt_down = 0
akt.a_f_cnt_down = 0
devsvc.Activate(api.ActivateDeviceRequest(device_activation=akt), metadata=AUTH)
print("[ok]  Sitzung eingetragen: DevAddr %s" % s["dev_addr"])


def c_bytes(hexstr):
    b = bytes.fromhex(hexstr)
    zeilen = []
    for i in (0, 8):
        zeilen.append(", ".join("0x%02x" % x for x in b[i:i + 8]))
    return zeilen


print()
print("Nach src/lorawan_secret.h (nicht in git), dann neu bauen und flashen:")
print()
print("#define LWRPT_ID_DEVADDR 0x%sUL" % s["dev_addr"].upper())
for name, key in (("LWRPT_ID_NWKSKEY", s["nwk_s_key"]),
                  ("LWRPT_ID_APPSKEY", s["app_s_key"])):
    a, b = c_bytes(key)
    print("#define %s { %s, \\" % (name, a))
    print("%s  %s }" % (" " * len(name), b))
