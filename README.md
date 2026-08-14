# LoRaWAN-Gateway Lenggries — Dragino DLOS8N

Konfiguration und Instandsetzung des LoRaWAN-Gateways in 83661 Lenggries,
Stand **14.08.2026**. Alle Zugangsdaten sind aus diesem Repo entfernt.

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
   |  10.9.0.9 (WireGuard)     |
   +---------------------------+
        |                    |
        | server1            | server2
        | Internet           | WireGuard
        v                    v
  eu1.cloud.thethings   +----------+      +------------------+
    .network:1700       | ipgate1  | ---> | heissa.de        |
   (The Things Network) | 10.9.0.1 |      | 10.9.0.10        |
                        +----------+      | gateway-bridge   |
                                          |   :1700 -> MQTT  |
                                          | ChirpStack :8080 |
                                          +------------------+
```

**Netz-Trennung:** `10.9.0.0/24` = WireGuard (Server ipgate1), `10.8.0.0/24` = OpenVPN
(Server heissa.de). Das Gateway hängt im WG-Netz, weil die Dragino-Firmware
**keinen TUN-Treiber** hat — OpenVPN ist darauf schlicht nicht lauffähig
(`kmod-tun` aus dem Feed ist gegen Kernel 4.9.214 gebaut, das Gerät läuft auf 4.9.109).

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

### 2. WireGuard-Gegenstelle auf heissa.de

`/etc/wireguard/wg0.conf` enthielt keine Konfiguration, sondern die **Ausgabe von
`wg show`**. `wg-quick@wg0` scheiterte deshalb bei jedem Boot mit
`Line unrecognized: 'interface:wg0'` — monatelang unbemerkt.

Nebenwirkung: In `/etc/mosquitto/mosquitto.conf` stand `listener 1883 10.0.0.1` —
die Adresse des alten WG-Interfaces. Ohne wg0 existierte diese IP nicht, mosquitto
konnte nicht binden.

### 3. mosquitto war deinstalliert

Am 23.07.2026 wurde das Paket entfernt (Status `rc`). ChirpStack lief zwar als
Dienst weiter, loggte aber im Sekundentakt `MQTT error … Connection refused` und war
damit funktionslos, weil `chirpstack.toml` sowohl das Gateway-Backend als auch die
Integration auf `tcp://127.0.0.1:1883` zeigt.

### 4. ChirpStack fehlte die Empfangsseite

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
* Erreichbar über `10.9.0.9` (WireGuard) und im Heimnetz über `eth1`.
  Auf `eth1` (WAN-Zone) blockt die OpenWrt-Firewall SSH von außerhalb des LAN.
* Das eigene WLAN des Gateways (`br-lan`, 10.130.1.1) ist der Notzugang, falls
  der Tunnel steht.

## Dateien

| Pfad | Inhalt |
|---|---|
| `gateway/uci-gateway.txt` | `uci show gateway` — Kanäle, Server, Radios |
| `gateway/global_conf.json` | Konzentrator-Konfig: 8× `chan_multiSF` + LoRa-STD + FSK |
| `gateway/local_conf.json` | Server-Liste des Forwarders |
| `gateway/uci-network.txt` | Netzwerk inkl. WireGuard (Keys entfernt) |
| `gateway/uci-wireless.txt` | WLAN (Passphrasen entfernt) |
| `heissa/wg0.conf` | heissa.de als WG-Client von ipgate1 |
| `heissa/chirpstack-gateway-bridge.toml` | Semtech-UDP → MQTT |
| `heissa/chirpstack.toml` | ChirpStack (Secrets entfernt) |
| `heissa/mosquitto.conf` | Broker-Listener |
| `ipgate1/wg0.conf` | WG-Server 10.9.0.0/24 (Keys entfernt) |
| `heissa/lora_bridge.py` | TTN-MQTT → wagodb + Traccar, mit Decoder-Portierung |
| `heissa/lora-bridge.service` | systemd-Unit dazu |
| `heissa/lora_schema.sql` | Tabellen `lora_uplinks` und `lora_joins` |
| `heissa/ttn_register.py` | OTAA-Gerät bei TTN anlegen (IS → JS → NS → AS) |
| `devices/README.md` | Endgeräte, Schlüssel-Herkunft, AT-Kommandos |
| `devices/trackerd.js` | Offizieller TrackerD-Decoder (TTN-Device-Repository) |

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

## Endgeräte, Datenhaltung und Traccar

Seit 14.08.2026 hängt an dem Gateway eine vollständige Verarbeitungskette.
Details zu den Geräten in [`devices/README.md`](devices/README.md).

```
  TrackerD          LA66 USB-Adapter
  A840414F1188076C  A8404117F18962E0
        |                  |
        +--------+---------+
                 v
        Dragino DLOS8N (Lenggries)
                 |
                 v
        TTN eu1 / Anwendung lenggries-sensors
                 |  MQTT über TLS :8883
                 v
        heissa.de — lora-bridge.service
                 |
        +--------+--------------+
        v                       v
  wagodb.lora_uplinks     Traccar :5055
  wagodb.lora_joins       (OsmAnd-Protokoll)
```

Die Brücke dekodiert **selbst**, obwohl TTN das auch könnte. Damit landen die
Werte auch dann in der Datenbank, wenn am Payload-Formatter in der Konsole
jemand schraubt, und die Zeile bleibt vollständig, wenn TTN `decoded_payload`
einmal nicht mitliefert.

Zwei Ebenen in `lora_uplinks` mit Absicht: `raw` hält die komplette
TTN-Nachricht, damit auch Felder erhalten bleiben, an die beim Anlegen niemand
gedacht hat; die Einzelspalten daneben sind nur Spiegel der häufig gebrauchten
Werte, damit Grafana und SQL nicht jedes Mal JSON auspacken müssen.

Ein Uplink kommt über mehrere Gateways herein — für die Funkspalten wird das
mit dem stärksten Signal genommen.

### Stolperstellen

* **`f_cnt` fehlt bei 0.** TTN lässt Nullwerte im JSON weg. Als `NULL`
  gespeichert greift der `UNIQUE`-Index nicht (NULL ist in MySQL nie gleich
  NULL), und jeder Neustart der Brücke schriebe den ersten Uplink nach einem
  Join erneut. Die Brücke setzt deshalb `f_cnt or 0`.
* **Decoder gehört zum Gerät, nicht zum fPort.** Sonst liefe die
  TrackerD-Logik auch über LA66-Payloads und lieferte Unsinn. Zuordnung über
  `DECODERS` per DevEUI.
* **MariaDB nur über den Unix-Socket.** `bind-address = 0.0.0.0`, aber ein
  Grant auf `@'localhost'` gilt nicht für TCP nach `127.0.0.1` — von dort
  kommt `1130 Host not allowed`.
* **Traccar `uniqueId` = DevEUI in Kleinbuchstaben.** Die Brücke meldet über
  das OsmAnd-Protokoll; `batt` erwartet Prozent, der TrackerD liefert Volt,
  also linear über den nutzbaren Bereich einer 1S-Li-Ion-Zelle geschätzt —
  der genaue Wert steht als `voltage` daneben.

## Krisenfall: 192.168.5.23 übernimmt

Der LA66 ist Notfallgerät: **fällt das Internet aus, ist er eines der wenigen
Mittel, um vom Berg aus mit dem Heimserver `192.168.5.23` zu sprechen.** Damit
das trägt, muss der Heimserver im Krisenfall die Rolle von heissa.de
übernehmen — und **der dell wird dann WireGuard-Master**.

Was dafür spricht, dass das funktionieren kann: **das Gateway erreicht
`192.168.5.23` direkt** (gemessen 1,2 ms), ohne Umweg über Internet, ipgate1
oder WireGuard. Der Pfad hängt an keiner Außenverbindung.

Die harte Randbedingung: das Gateway hat nur **zwei Server-Slots**
(`gateway.server1` = TTN, `gateway.server2` = ChirpStack auf heissa.de über
10.9.0.10). Beide zeigen heute auf Ziele, die Internet brauchen. Im Krisenfall
ist server1 ohnehin wertlos — TTN ist dann nicht erreichbar.

Status: **geplant, noch nicht umgesetzt.** Offen sind lokaler Netzserver,
Broker, Datenbank und Traccar auf dem dell sowie die Umschaltung des
WG-Masters von ipgate1 auf den dell.
