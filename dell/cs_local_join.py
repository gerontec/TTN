#!/usr/bin/env python3
"""Schalter: darf der lokale ChirpStack Joins dieses Geraets beantworten?

Hintergrund: TTN verarbeitet nur DevAddr aus `260B0000/16`. Damit ein Geraet
dort ankommt, muss es **bei TTN** joinen — und der lokale ChirpStack gewinnt
jedes Join-Rennen (1,2 ms ueber LAN gegen rund 40 ms nach eu1). Joint ein
Geraet also spaeter von sich aus neu, etwa nach einem Stromausfall, faellt es
zurueck auf eine lokale Adresse und verschwindet aus TTN.

Dauerhaft verhindern laesst sich das ueber das **Geraeteprofil**: eines mit
`supports_otaa = false` beantwortet keinen JoinRequest, verarbeitet die
ABP-Sitzung aber unveraendert weiter. Das ist der Unterschied zu
`is_disabled` (cs_device_enable.py), das auch das Mithoeren abschaltet und
deshalb nur fuer die paar Sekunden des Umzugs taugt.

**Die Empfangsfenster muessen mitwandern.** Ein Geraet, das bei TTN gejoint
hat, uebernimmt dessen MAC-Parameter — gemessen am 24.08.2026: RX1-Verzoegerung
5 s, RX2 auf DR3 und 869,525 MHz. ChirpStacks ABP-Vorgabe ist eine andere;
ohne Angleichung sendet der Krisen-Rundruf am Fenster vorbei und keine
Downlink kommt mehr an. Die Werte werden deshalb aus TTS gelesen.

    cs_local_join.py <dev_eui> off   # lokaler Join gesperrt, TTN gewinnt
    cs_local_join.py <dev_eui> on    # zurueck zum OTAA-Profil
    cs_local_join.py <dev_eui>       # nur nachsehen
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

import grpc
from chirpstack_api import api

if not 2 <= len(sys.argv) <= 3:
    sys.exit(__doc__)
DEV_EUI = sys.argv[1].lower()
WUNSCH = sys.argv[2] if len(sys.argv) == 3 else None
if WUNSCH not in (None, "on", "off"):
    sys.exit(__doc__)

TENANT = "d2d00763-756f-4da6-91d4-57204a065051"
cfg = {}
with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            cfg[k] = v
chan = grpc.insecure_channel("127.0.0.1:8090")
auth = [("authorization", "Bearer " + cfg["CHIRPSTACK_TOKEN"])]
devsvc = api.DeviceServiceStub(chan)
dpsvc = api.DeviceProfileServiceStub(chan)

dev = devsvc.Get(api.GetDeviceRequest(dev_eui=DEV_EUI), metadata=auth).device
prof = dpsvc.Get(api.GetDeviceProfileRequest(id=dev.device_profile_id),
                 metadata=auth).device_profile
print(f"{dev.name}: Profil {prof.name}, "
      f"lokaler Join {'erlaubt' if prof.supports_otaa else 'gesperrt'}")
if WUNSCH is None or (WUNSCH == "off") != prof.supports_otaa:
    sys.exit(0)


def rx_von_tts():
    """Die Fenster, die das Geraet nach dem TTN-Join wirklich benutzt."""
    with open(os.path.expanduser("~/.config/ttn/lenggries.key")) as f:
        k = re.search(r"NNSXS\.[A-Z0-9]+\.[A-Z0-9]+", f.read()).group(0)
    base = "https://eu1.cloud.thethings.network/api/v3"
    info = json.load(urllib.request.urlopen(urllib.request.Request(
        base + "/auth_info", headers={"Authorization": "Bearer " + k}), timeout=10))
    app = (((info.get("api_key") or {}).get("entity_ids") or {})
           .get("application_ids") or {}).get("application_id")
    dev_id = dev.name.lower().replace("_", "-")
    url = (f"{base}/ns/applications/{app}/devices/{dev_id}?field_mask="
           "mac_state.current_parameters.rx1_delay,"
           "mac_state.current_parameters.rx2_data_rate_index,"
           "mac_state.current_parameters.rx2_frequency")
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(
            url, headers={"Authorization": "Bearer " + k}), timeout=12))
    except urllib.error.HTTPError:
        return None
    cp = ((d.get("mac_state") or {}).get("current_parameters") or {})
    if not cp.get("rx1_delay"):
        return None
    return (int(cp["rx1_delay"]), int(cp.get("rx2_data_rate_index") or 0),
            int(cp.get("rx2_frequency") or 869525000))


ziel_name = (prof.name.replace("-otaa-", "-abp-") if WUNSCH == "off"
             else prof.name.replace("-abp-", "-otaa-"))
if ziel_name == prof.name:
    ziel_name = prof.name + ("-abp" if WUNSCH == "off" else "-otaa")

vorhanden = next((p for p in dpsvc.List(api.ListDeviceProfilesRequest(
    limit=100, tenant_id=TENANT), metadata=auth).result if p.name == ziel_name), None)

if vorhanden:
    ziel_id = vorhanden.id
    print(f"Zielprofil {ziel_name} vorhanden")
else:
    neu = api.DeviceProfile()
    neu.CopyFrom(prof)
    neu.ClearField("id")
    neu.name = ziel_name
    neu.supports_otaa = (WUNSCH == "on")
    if WUNSCH == "off":
        rx = rx_von_tts()
        if rx is None:
            sys.exit("RX-Fenster nicht aus TTS lesbar — ohne die passenden "
                     "Werte wuerde der Rundruf am Fenster vorbeisenden. "
                     "Erst das Geraet bei TTN joinen lassen.")
        neu.abp_rx1_delay, neu.abp_rx2_dr, neu.abp_rx2_freq = rx
        neu.abp_rx1_dr_offset = 0
        print(f"Zielprofil {ziel_name} wird angelegt "
              f"(RX1 {rx[0]} s, RX2 DR{rx[1]} auf {rx[2]/1e6:.3f} MHz, aus TTS)")
    ziel_id = dpsvc.Create(api.CreateDeviceProfileRequest(device_profile=neu),
                           metadata=auth).id

dev.device_profile_id = ziel_id
devsvc.Update(api.UpdateDeviceRequest(device=dev), metadata=auth)
nach = dpsvc.Get(api.GetDeviceProfileRequest(id=ziel_id), metadata=auth).device_profile
print(f"{dev.name}: Profil {nach.name}, "
      f"lokaler Join {'erlaubt' if nach.supports_otaa else 'gesperrt'}")
