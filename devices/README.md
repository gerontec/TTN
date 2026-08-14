# Endgeräte am Gateway Lenggries

TTN-Anwendung: **`lenggries-sensors`** (Konto `lenggries`, eu1), angelegt 14.08.2026.

| Gerät | DevEUI | JoinEUI | Modus | Rolle |
|---|---|---|---|---|
| Dragino **TrackerD** | `A840414F1188076C` | `A840410000000102` | OTAA | GPS-Tracker, Position → Traccar |
| Dragino **LA66 USB-Adapter v1.3** | `A8404117F18962E0` | `A840410000000101` | OTAA | Krisen-/Notfallgerät, siehe unten |
| Dragino **LHT65** | (aus Gateway-DB) | — | ABP, Altbestand | Temperatur/Feuchte, noch nicht migriert |

AppKeys stehen **nicht** in diesem Repo. Sie liegen auf heissa.de unter
`~/.config/ttn/` bzw. auf dem Aufkleber des jeweiligen Geräts.

## TrackerD

GPS-Tracker mit ESP32, roter Alarmtaste und USB-C. Meldet sich mit OTAA;
der AppKey ist **gerätespezifisch** und steht auf dem Aufkleber — es gibt
keinen dokumentierten Werksschlüssel. Ein Auslesen per AT ist möglich, aber
mühsam: die AT-Konsole läuft mit **115200** Baud über USB-C, und der Port
verschwindet nach rund 1,5 s wieder, sobald ModemManager ihn parallel öffnet
und dabei DTR togglet.

Nützlich zur Kontrolle: ein mitgeschnittener Join-Request verrät, ob ein
AppKey-Kandidat stimmt, ohne dass man ihn erst beim Netzserver eintragen muss.
Die letzten vier Byte des Join-Requests sind ein AES-CMAC über die ersten 19
Byte mit genau diesem Schlüssel.

```python
from cryptography.hazmat.primitives.cmac import CMAC
from cryptography.hazmat.primitives.ciphers import algorithms
c = CMAC(algorithms.AES(bytes.fromhex(kandidat))); c.update(phy[:19])
stimmt = c.finalize()[:4] == phy[19:23]
```

Payload-Decoder: `trackerd.js`, unverändert aus dem
[TTN-Device-Repository](https://github.com/TheThingsNetwork/lorawan-devices/blob/master/vendor/dragino/trackerd.js).
Die Brücke auf heissa.de führt dieselbe Logik als Python-Portierung aus —
inklusive der Eigenheit, dass `MD` in Port 2/3 unverschoben (`& 0xc0`), in
Port 8 dagegen verschoben (`>> 6`) gebildet wird.

| fPort | Inhalt |
|---|---|
| 2 | GPS + Batterie + Alarm + Temperatur/Feuchte |
| 3 | GPS + Batterie + Alarm |
| 4 | GPS + Datum/Uhrzeit |
| 5 | Gerätestatus (Firmware, Band, Modus) |
| 6 | BLE-Beacon (UUID, Major/Minor, RSSI) |
| 7 | nur Alarm + Batterie |
| 8 | WLAN-SSID + RSSI |

## LA66 USB-Adapter — Krisengerät

CP2102 an USB, AT-Konsole **9600** Baud, bleibt stabil verbunden (anders als
der TrackerD). Der Adapter hat keine eigenen Sensoren: was er sendet, gibt der
Host per `AT+SENDB` vor. Deshalb ist für ihn **kein Decoder hinterlegt** —
Payload und Funkmetadaten landen roh in `lora_uplinks`.

Er ist das Notfallgerät: **fällt das Internet aus, ist er eines der wenigen
Mittel, um vom Berg aus mit dem Heimserver `192.168.5.23` zu sprechen.**

```
AT+VER=?      Firmware (hier: EU868 v1.3)
AT+CFG        komplette Konfiguration inkl. Schlüssel
AT+JOIN       OTAA-Join auslösen
AT+NJS=?      1 = beigetreten
AT+SENDB=<bestätigt>,<fPort>,<länge>,<hex>
```

Verifiziert am 14.08.2026: Join über das Lenggrieser Gateway (RSSI −85),
Test-Uplink auf fPort 10 mit SF12 bei −88 dBm, 1319 ms Airtime.
