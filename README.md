# LoRaWAN-Gateway Lenggries — Dragino DLOS8N

Konfiguration und Instandsetzung des LoRaWAN-Gateways in 83661 Lenggries,
Stand **14.08.2026**. Alle Zugangsdaten sind aus diesem Repo entfernt.

**Einstieg für die Weiterarbeit: [TODO.md](TODO.md)** — Zustand, Fallen und
offene Punkte, geschrieben als Wiederaufsetzpunkt.

## Gerät

| | |
|---|---|
| Modell | Dragino **DLOS8N** (Board meldet sich intern als `LG08`) |
| Konzentrator | Semtech **SX1302**, 8 Kanäle |
| Gateway-EUI | `A84041FFFF27E318` |
| Hostname | `dragino-27e318` |
| Firmware | `Dragino-v2 lgw-5.4.1785230224` (Build 28.07.2026) |
| Basis | OpenWrt 18.06, Kernel 4.9.109, ar71xx/mips_24kc |
| Standort | 47.679 N, 11.579 O, 680 m |
| TTN | [`eui-a84041ffff27e318`](https://eu1.cloud.thethings.network/console/gateways/eui-a84041ffff27e318) — öffentlich, EU_863_870_TTN |

## Architektur

```
   LoRa-Geräte (EU868, 8 Kanäle)
              |
              v
   +---------------------------+
   |  Dragino DLOS8N           |  fwd -d sx1302 (Semtech-UDP-Forwarder)
   |  im Heimnetz an eth1      |
   +---------------------------+
        |                    |                    |
        | server1            | server2            | server3
        | Internet (optional)| LAN, direkt (1,2 ms)| LAN, roh
        v                    v                    v
  eu1.cloud.thethings   +----------------------+  :1702
    .network:1700       | dell-3660            |  lora_raw.py
   (The Things Network) | 192.168.5.23         |  -> MQTT lora/raw
                        | ChirpStack :8090     |
                        | mosquitto :1883      |
                        +----------------------+
                          Dieser Weg braucht weder Internet
                          noch Tunnel. Er ist der Normalbetrieb.
```

Neben der LoRaWAN-Kette hängt ein **roher Kanal** für P2P-Verkehr
(`chan_Lora_std`, 868.125 MHz, SF7, BW125) — ChirpStack verwirft solche Pakete
mangels gültigem LoRaWAN-Rahmen, deshalb wird daneben abgegriffen und nicht
dahinter. Aufbau, Fallen und Messungen: **[gateway/RAWKANAL.md](gateway/RAWKANAL.md)**.

**Kein Tunnel im Pfad.** Das Gateway erreicht `192.168.5.23` direkt über das
LAN. Frühere Aufbauten hingen an WireGuard und einem Server im Internet; beides
ist aus diesem Repo entfernt, weil der Notfallkanal genau daran nicht hängen
darf.

## Was kaputt war

### 1. Gateway sendete überhaupt kein LoRaWAN

`gateway.general.server_type` stand auf `mqtt` — das ist der IoT-/Raw-LoRa-Modus,
nicht LoRaWAN. In diesem Modus läuft der Paket-Forwarder `fwd` gar nicht, es lief nur
`mqtt_process.sh`. Der 8-Kanal-Plan in `global_conf.json` war dabei völlig intakt;
wirksam waren aber die Raw-Radio-Settings `gateway.radio1/radio2` — und die standen
auf **915 MHz** (US-Band), also für EU nutzlos.

Fix:

```sh
uci set gateway.general.server_type='lorawan'
uci commit gateway
/usr/bin/generate-config.sh      # schreibt global_conf.json + local_conf.json neu
/etc/init.d/lora_gw restart
```

Gültige Werte für `server_type`: `lorawan`, `station`, `mqtt`, `abpdecode`,
`tcpudp`, `loriot`, `disabled`. Bei `disabled`/`loriot`/`station` stoppt
`/etc/init.d/lora_gw` den Forwarder bewusst.

### 2. mosquitto war deinstalliert

Am 23.07.2026 wurde das Paket entfernt (Status `rc`). ChirpStack lief zwar als
Dienst weiter, loggte aber im Sekundentakt `MQTT error … Connection refused` und war
damit funktionslos, weil `chirpstack.toml` sowohl das Gateway-Backend als auch die
Integration auf `tcp://127.0.0.1:1883` zeigt.

### 3. ChirpStack fehlte die Empfangsseite

ChirpStack v4 spricht kein Semtech-UDP. Der `chirpstack-gateway-bridge` fehlte
komplett und wurde nachinstalliert. Wichtig: `marshaler="json"` und das
Topic-Präfix `eu868` müssen zu `chirpstack.toml` passen, sonst kommen die Pakete
zwar an, aber niemand hört zu:

```
ChirpStack abonniert: $share/chirpstack/eu868/gateway/+/event/+
Bridge publiziert an: eui868/gateway/{{ .GatewayID }}/event/{{ .EventType }}
```

## Firmware-Update

Von `5.4.1765963883` (17.12.2025) auf `5.4.1785230224` (28.07.2026):

```sh
# Image gehört zur "dragino-lgw"-Linie, gilt modellübergreifend;
# der Chip wird zur Laufzeit erkannt (/var/iot/chip)
scp dragino-lgw--v5.4.1785230224-squashfs-sysupgrade.bin root@GW:/tmp/fw.bin
ssh root@GW 'sha256sum /tmp/fw.bin'     # gegen sha256sums prüfen
ssh root@GW 'sysupgrade /tmp/fw.bin'    # OHNE -n: Einstellungen behalten
```

`sysupgrade -T` meldet bei diesen Images „Image metadata not found" — das ist
normal, der Flash läuft trotzdem. Beim Remote-Flash die Einstellungen **behalten**,
sonst fallen WLAN-AP und VPN auf Werkszustand zurück und der Zugang ist weg.

Bezugsquelle: `dragino.com/downloads/…/LoRa_Gateway/DLOS8/Firmware/Release/`
(einen eigenen DLOS8N-Ordner gibt es nicht).

## Zugang

* SSH-Key liegt in `/etc/dropbear/authorized_keys` (Dropbear, akzeptiert ssh-rsa).
  Für alte Hostkeys: `ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa`.
* Erreichbar im Heimnetz über `eth1`.
  Auf `eth1` (WAN-Zone) blockt die OpenWrt-Firewall SSH von außerhalb des LAN.
* Das eigene WLAN des Gateways (`br-lan`, 10.130.1.1) ist der Notzugang, falls
  der Tunnel steht.

## Dateien

| Pfad | Inhalt |
|---|---|
| `gateway/uci-gateway.txt` | `uci show gateway` — Kanäle, Server, Radios |
| `gateway/global_conf.json` | Konzentrator-Konfig: 8× `chan_multiSF` + LoRa-STD + FSK |
| `gateway/local_conf.json` | Server-Liste des Forwarders |
| `gateway/uci-network.txt` | Netzwerk (LAN/WAN; der Tunnel-Abschnitt ist entfernt) |
| `gateway/uci-wireless.txt` | WLAN (Passphrasen entfernt) |
| `ttn/ttn_register.py` | Gerät bei TTN anlegen — OTAA oder ABP (IS → JS → NS → AS) |
| `ttn/ttn_delete.py` | Gerät über alle vier TTS-Dienste entfernen |
| `ttn/ttn_show.py` | Was TTS wirklich gespeichert hat (Session, Frame-Counter) |
| `ttn/ttn_last.py` | Letzte Uplinks aus der Storage-Integration |
| `devices/README.md` | Endgeräte, Schlüssel-Herkunft, AT-Kommandos |
| `devices/trackerd.js` | Offizieller TrackerD-Decoder (TTN-Device-Repository) |
| `TODO.md` | Wiederaufsetzpunkt: Zustand, Fallen, offene Punkte |
| `dell/dell_chirpstack.sh` | Lokalen Netzserver auf 192.168.5.23 aufsetzen |
| `dell/cs_setup.py` | Gateway, Anwendung, Profil und LA66 (ABP) anlegen |
| `dell/cs_trackerd.py` | TrackerD anlegen |
| `dell/cs_state.py` | Welche Geräte kennt der lokale Server, wann zuletzt gehört |
| `dell/cs_dupapp.py` | Anwendungen auflisten, leere Doppel löschen |
| `dell/cs_classc.py` | Geräteprofil auf Class C |
| `dell/cs_reactivate.py` | ABP-Aktivierung erneuern, damit Class C greift |
| `dell/cs_fix_profile.py` | Region/MAC-Version über die Enum-Konstanten geradeziehen |
| `dell/dragino_rx.py` | LoRa-Uplink → MQTT-Topic |
| `dell/crisis_bcast.py` | MQTT-Topic `crisis` → Downlink an alle Geräte |
| `devices/la66_p2p/ANLEITUNG.md` | LA66 auf P2P flashen, Schritt für Schritt |
| `devices/la66_p2p/la66_uart_flash.py` | LA66 unter Linux flashen, ohne Windows |
| `devices/la66_p2p/la66_mode.py` | LA66 zwischen LoRaWAN und P2P umschalten |
| `laptop/dragino.py` | Nachricht über den LA66 funken |
| `hosts_block.sh` | Gegenseitige `/etc/hosts`-Einträge über ULAs |

## EU868-Kanalplan

| Kanal | Radio | Offset | Frequenz |
|---|---|---|---|
| 0 | 1 | −400 kHz | 868.1 MHz |
| 1 | 1 | −200 kHz | 868.3 MHz |
| 2 | 1 | 0 | 868.5 MHz |
| 3 | 0 | −400 kHz | 867.1 MHz |
| 4 | 0 | −200 kHz | 867.3 MHz |
| 5 | 0 | 0 | 867.5 MHz |
| 6 | 0 | +200 kHz | 867.7 MHz |
| 7 | 0 | +400 kHz | 867.9 MHz |

Dazu `chan_Lora_std` (868.3 MHz, 250 kHz, SF7) und `chan_FSK` (868.8 MHz).
Radio 0 liegt auf 867.5 MHz, Radio 1 auf 868.5 MHz; nur Radio 0 sendet.

## Krisenpfad und Notfallkanal

Seit 14.08.2026 hängt am Gateway ein zweiter, vollständig lokaler Weg. Der
Einstieg für alles Weitere ist **[TODO.md](TODO.md)** — dort stehen Zustand,
Fallen und offene Punkte.

```
   LA66 am USB des Notebooks
            |
            v
   Dragino DLOS8N  --server1-->  TTN  (optional, nur mit Internet)            |
            +-----server2----->  192.168.5.23  (LAN, 1,2 ms)
                                 ChirpStack + mosquitto
                                   |
                                   +-- dragino-rx.service   LoRa  -> MQTT
                                   +-- crisis-bcast.service MQTT  -> LoRa
```

Der lokale Weg braucht **kein Internet und keinen Tunnel**. Er läuft
im Normalbetrieb dauernd mit und ist damit dauernd getestet — ein Umschalten im
Ernstfall gibt es bewusst nicht.

| Richtung | Aufruf |
|---|---|
| Berg → Heimserver | `dragino.py wetter/berg "Schneefall"` |
| Heimserver → alle Geräte | `mosquitto_pub -h dell -t crisis -m "Lawinenwarnung"` |

Der LA66 läuft als **Class C** und lauscht dauerhaft auf 869.525 MHz, empfängt
einen Broadcast also ohne vorher selbst zu senden. Als Class-A-Gerät wäre er
fast nur Sender gewesen.

Feste Adressen über ULAs `fd00::/64` — die GUAs aus dem FritzBox-Präfix
wechseln mit jedem Provider-Wechsel, ULAs nie. Über IPv6 sind die getrennten
IPv4-Netze 192.168.5.x und 192.168.178.x dasselbe Segment.

## Endgeräte

Details zu den Geräten in [`devices/README.md`](devices/README.md).

Die TrackerD-Firmware ist ein offener Arduino-Sketch:
[dragino/TrackerD](https://github.com/dragino/TrackerD). Er lohnt den Blick,
weil er Verhalten festlegt, das in keinem Datenblatt steht — etwa dass der rote
Knopf je nach Haltezeit den Alarm auslöst *oder* abschaltet
([`extiButtonLS.cpp`](https://github.com/dragino/TrackerD/blob/main/Example/LoRaWAN/examples/TrackerD/extiButtonLS.cpp),
aufgeschlüsselt in `devices/README.md`).

```
  TrackerD          LA66 USB-Adapter
  A840414F1188076C  A8404117F18962E0
        |                  |
        +--------+---------+
                 v
        Dragino DLOS8N (Lenggries)
                 |
        +--------+-------------------+
        v                            v
  192.168.5.23 (ChirpStack)    TTN eu1 / lenggries-sensors
  maßgeblich, ohne Internet    Mitschnitt, wenn Internet da ist
```

## Krisenfall: 192.168.5.23 trägt allein

Der LA66 ist Notfallgerät: **fällt das Internet aus, ist er eines der wenigen
Mittel, um vom Berg aus mit dem Heimserver `192.168.5.23` zu sprechen.**

Das trägt, weil **das Gateway `192.168.5.23` direkt erreicht** — gemessen
1,2 ms über das LAN, ohne Internet und ohne Tunnel. Der Pfad hängt an keiner
Außenverbindung, und er läuft im Normalbetrieb dauernd mit; ein Umschalten im
Ernstfall gibt es bewusst nicht, weil ungetestete Umschaltungen im Ernstfall
scheitern.

Das Gateway hat zwei Server-Slots: `server1` zeigt auf TTN, `server2` auf den
lokalen ChirpStack. Fällt das Internet aus, ist server1 wertlos, server2 läuft
unverändert weiter.

**Beide Geräte sind bewusst als ABP eingetragen**, lokal wie im TTN. Der Grund
ist kein Geschmack: Das Gateway schiebt jeden Uplink an beide Server, und beide
dürfen Downlinks senden. Ein OTAA-Gerät bekäme auf seinen JoinRequest zwei
JoinAccepts und nähme das zuerst eintreffende — der lokale Server könnte das
Gerät also jederzeit an TTN verlieren, genau im falschen Moment. Ohne Join gibt
es nichts zu kapern; beide Netze hören dieselbe Sitzung mit, maßgeblich bleibt
der lokale.

| | lokal (192.168.5.23) | TTN |
|---|---|---|
| LA66 | `la66-notfall`, DevAddr `018962E0` | `la66-f18962e0` |
| TrackerD | `trackerd-lenggries`, DevAddr `00EA9F34` | `trackerd-1188076c` |

Status: **umgesetzt und verifiziert** — beide Geräte werden lokal gehört, im
TTN steigen die Frame-Counter mit.
