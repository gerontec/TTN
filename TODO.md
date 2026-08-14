# Wiederaufsetzpunkt

Zustand **14.08.2026, 20:40**. Dieses Dokument ist so geschrieben, dass man
allein damit weiterarbeiten kann — ohne den Gesprächsverlauf, aus dem es
entstanden ist.

## Worum es geht

Ein LoRaWAN-Gateway in 83661 Lenggries, zwei Endgeräte daran, und ein
Notfallkanal, der auch dann noch trägt, wenn das Internet weg ist.

## Die vier Rechner

| Name | Adresse | Rolle |
|---|---|---|
| `gh-hpi7` | 192.168.178.27 · `fd00::27` | Notebook, hier steckt der LA66 am USB |
| `dragino-27e318` | 192.168.178.106 · `fd00::106` · 10.9.0.9 | Dragino DLOS8N, Gateway |
| `dell-3660` | 192.168.5.23 · `fd00::23` · 10.9.0.6 | Heimserver, lokaler Netzserver |
| `heissa.de` | 74.208.77.214 · 10.9.0.10 | Internet-Server, Datenhaltung + Traccar |

**IPv4 ist geteilt** (192.168.5.x ≠ 192.168.178.x), **IPv6 nicht** — alle
hängen am selben FritzBox-Segment. Deshalb laufen die festen Adressen über
ULAs `fd00::/64`: die wechseln nie, während die GUAs aus dem Präfix
`2a02:810d:4117:7300::/64` mit jedem Provider-Wechsel andere werden. Alle drei
lokalen Rechner kennen sich über `/etc/hosts` (Block `lora-notfallpfad`, siehe
`hosts_block.sh`).

## Zwei Pfade, absichtlich getrennt

```
                        Endgeräte (EU868)
                     TrackerD        LA66
                        |              |
                        +------+-------+
                               v
                    Dragino DLOS8N Lenggries
                     server1 |        | server2
              Internet/TTN   |        |   LAN, direkt
                             v        v
        eu1.cloud.thethings.network   192.168.5.23
                             |          ChirpStack :8090
                             v          mosquitto :1883
                       heissa.de              |
                    lora-bridge.service       +-- dragino-rx.service
                        |         |           +-- crisis-bcast.service
             wagodb.lora_*    Traccar :5055
```

* **Normalbetrieb** läuft über TTN nach heissa.de. Dort schreibt
  `lora-bridge.service` jeden Uplink nach `wagodb.lora_uplinks` und meldet
  Positionen an Traccar.
* **Krisenpfad** läuft über `server2` direkt ins LAN zum dell — **ohne
  Internet, ohne WireGuard, ohne ipgate1**. Gemessene Laufzeit Gateway → dell:
  1,2 ms. Dieser Pfad ist im Normalbetrieb dauernd aktiv und damit dauernd
  getestet; ein Umschalten im Ernstfall gibt es bewusst nicht.

Das Gateway hat nur **zwei Server-Slots**. `server1` = TTN ist im Krisenfall
ohnehin wertlos, deshalb belegt `server2` den lokalen Weg.

## Was funktioniert (verifiziert)

* Gateway sendet an beide Server gleichzeitig (`server-UP` und `dell-lokal-UP`
  im Wechsel im `logread`).
* **TrackerD** ist bei TTN registrierbar, aber **noch nicht registriert** —
  siehe offene Punkte.
* **LA66** ist bei TTN (OTAA) *und* im lokalen ChirpStack (ABP) angelegt.
  Aktiv genutzt wird **ABP am dell**.
* **Uplink**: `dragino.py wetter/berg "Text"` → LoRa → Gateway → ChirpStack →
  `dragino_rx.py` → MQTT-Topic. Belegt am 14.08. mit RSSI −84, SNR 7,2.
* **Broadcast/Downlink**: `mosquitto_pub -h dell -t crisis -m "..."` →
  `crisis_bcast.py` → ChirpStack-Warteschlange → Class-C-Push → LA66 empfängt
  **unaufgefordert**. Belegt: `AT+RECVB=?` liefert `21:8048414c4c4f2042455247`
  = fPort 21, `HALLO BERG`.
* heissa.de: `lora_uplinks` und `lora_joins` in `wagodb` gefüllt, Traccar-Gerät
  `TrackerD Lenggries` mit `uniqueId` = DevEUI angelegt.

## Fallen, die Zeit gekostet haben

Wer hier weiterarbeitet, spart sich damit die Wiederholung:

1. **`AT+RX1DL` überlebt den Netzwechsel.** Der OTAA-Join bei TTN hatte im
   Gerät RX1DL auf 5000 ms gesetzt. ChirpStack sendet nach 1000 ms — das
   Gateway meldete brav `JIT send done`, das Gerät `rxTimeout`. Zurückgesetzt
   auf `AT+RX1DL=1000`, `AT+RX2DL=2000`.
2. **Class C greift erst nach erneuter Aktivierung.** ChirpStack leitet
   `device.enabled_class` bei der Aktivierung aus dem Profil ab. Profil
   nachträglich auf Class C umgestellt heißt: Gerät bleibt auf `A`, bis
   `cs_reactivate.py` läuft.
3. **`region_config_id ''`.** Direkt nach einer ABP-Aktivierung kennt die
   Sitzung die Region noch nicht, der Class-C-Scheduler scheitert im
   Zweisekundentakt. Ein einziger Uplink des Geräts füllt das Feld.
4. **Downlink-Zählerkonflikt.** Nach der Neuaktivierung stand ChirpStack bei
   `FCntDown=0`, das Gerät bei 5 — der Rahmen kam an (`rxDone`), wurde aber
   verworfen, `AT+RECVB=?` blieb leer. `AT+FCD` ist nur lesbar; es half
   `ATZ` (setzt die ABP-Sitzung im Gerät auf 0) plus `AT+DISFCNTCHECK=1`.
5. **Enum-Werte in chirpstack-api sind nicht der Reihe nach.** `region=3` ist
   CN779, EU868 ist `0`; LoRaWAN 1.0.3 ist `mac_version=3`. Immer die
   Konstanten aus `chirpstack_api.common` nehmen, nie rohe Zahlen.
6. **Kein REST bei ChirpStack.** Weder auf heissa.de noch auf dem dell — alle
   `/api/...`-Pfade antworten 404. Nur gRPC (Port **8090** auf dem dell, 8080
   war belegt). Python-Umgebung dafür: `/home/gh/.venv-chirpstack`.
7. **mosquitto 2.0 bindet ohne `listener` nur an Loopback**, und eine
   `conf.d`-Datei mit Modus 0600 liest der Dienst gar nicht erst — sie muss
   0644 sein.
8. **MariaDB auf heissa.de nur über den Unix-Socket.** Ein Grant auf
   `@'localhost'` gilt nicht für TCP nach 127.0.0.1 (`1130 Host not allowed`).
9. **`f_cnt` fehlt bei 0.** TTN lässt Nullwerte im JSON weg; als `NULL`
   gespeichert greift der `UNIQUE`-Index nicht.
10. **`generate-config.sh` schreibt für server1 hart `"enable": "false"`.**
    Das ist Kosmetik, der Forwarder ignoriert es — kein Grund zur Panik.
11. **TrackerD am USB.** AT-Konsole 115200 Baud über USB-C, aber der Port
    verschwindet nach ~1,5 s wieder, sobald ModemManager ihn parallel öffnet
    und dabei DTR togglet. Der LA66 (CP2102, 9600) bleibt dagegen stabil.

## Offene Punkte

1. **TrackerD registrieren.** Fehlt allein am **AppKey** — der ist
   gerätespezifisch und steht auf dem Aufkleber, es gibt keinen dokumentierten
   Werksschlüssel (geprüft und widerlegt: der verbreitete Dragino-Default
   `5572404C…`, DevEUI doppelt, DevEUI+AppEUI und weitere Kandidaten). Ein
   Kandidat lässt sich ohne Registrierung testen, indem man die MIC eines
   mitgeschnittenen Join-Requests nachrechnet — Rezept in
   `devices/README.md`. Sobald der Schlüssel vorliegt:
   `APPKEY=<hex> ttn_register.py trackerd-1188076c A840414F1188076C A840410000000102 "Dragino TrackerD"`.
   Danach in TTN den Payload-Formatter setzen (Device Repository:
   `dragino` / `trackerd`) — der Decoder liegt als `devices/trackerd.js` bei
   und ist in `heissa/lora_bridge.py` als Python-Portierung gegen das
   Referenzbeispiel geprüft.
2. **Der TrackerD hat noch nie eine Position gesendet.** Bisher nur
   Join-Requests. Nach der Registrierung prüfen, ob Traccar Positionen sieht.
3. **LHT65** (Altbestand, ABP, DevAddr `018229BB`) ist weiterhin nur in der
   sqlite-DB des Gateways registriert, nicht bei TTN oder ChirpStack. Sein
   alter Decoder ist ein Lua-Skript und nicht portierbar.
4. **`dragino.py --verify`** setzt eine IP-Verbindung zum dell voraus und ist
   damit ausgerechnet im Krisenfall nutzlos. Ein Rückkanal über LoRa (Quittung
   per Downlink) wäre der ehrlichere Ersatz.
5. **`web.registration` bei Traccar** steht noch offen, und `:8082` lauscht auf
   allen Schnittstellen inklusive der öffentlichen IP. Fremde Registrierungen
   sind bis auf Weiteres möglich.
6. **Alte ChirpStack-Gatewayzeile** `48621185db7c38ca` („Dragino") auf
   heissa.de ist bewusst unangetastet geblieben.
7. **Duty Cycle.** Der LA66 hat die eigene Prüfung aus (`AT+DCS=0`). Rechtlich
   gilt das 1-%-Limit trotzdem; `dragino.py` wartet deshalb zwischen den
   Teilrahmen. Bei SF12 sind das rund vier Minuten je Rahmen.

## Wo die Geheimnisse liegen

Nichts davon gehört ins Repo.

| Was | Wo |
|---|---|
| TTN-API-Keys (`gerontec`, `lenggries`, Anwendung) | heissa.de `~/.config/ttn/*.key`, Modus 600 |
| ChirpStack-Token heissa.de / dell | jeweils `~/.config/chirpstack/api.key` |
| ChirpStack-DB-Passwort (dell) | dell `~/.config/chirpstack/db.env` |
| MariaDB-Zugang der Brücke | heissa.de `~/.config/lora/db.env` |
| Traccar-DB-Passwort | heissa.de `/opt/traccar/conf/traccar.xml`, Modus 640 |
| LA66-Sitzungsschlüssel | im Gerät, `AT+CFG` |
| TrackerD-AppKey | Aufkleber am Gerät |
| Gateway-Root-Passwort, WG-Schlüssel, WLAN-PSK | nicht im Repo |

## Handgriffe

```sh
# Nachricht vom Berg an den Heimserver
python3 ~/python/dragino.py wetter/berg "Schneefall, Abstieg verzoegert"
python3 ~/python/dragino.py --dr 0 notruf "Hilfe noetig"      # grösste Reichweite

# Broadcast an alle Geräte
mosquitto_pub -h dell -t crisis -m "Lawinenwarnung Stufe 4"

# Mitlesen
mosquitto_sub -h dell -t '#' -v
ssh gh@dell 'journalctl -u dragino-rx -f'
ssh gh@dell 'journalctl -u crisis-bcast -f'

# Gateway
ssh root@dragino 'logread | grep -E "server-UP|dell-lokal-UP"'
ssh root@dragino 'uci show gateway | grep server_address'

# Datenbank auf heissa.de
ssh gh@heissa.de 'sudo mysql wagodb -e "select received_at,device_id,f_port,payload_hex,rssi from lora_uplinks order by id desc limit 10"'
```

## Zustand der Geräte

**LA66** (Notfallgerät, hängt am USB des Notebooks):
`AT+NJM=0` ABP · `AT+CLASS=C` Dauerempfang · `AT+RX1DL=1000` ·
`AT+RX2DL=2000` · `AT+DISFCNTCHECK=1` · `AT+ADR=0` · `AT+RPL=2` ·
DevAddr `018962E0`.

Nach jedem `ATZ` beginnen die Zähler wieder bei 0 — das ist gewollt und hält
sie mit ChirpStack im Gleichschritt.

**Gateway**: `server_type='lorawan'`, `server2` = 192.168.5.23,
feste ULA `fd00::106/64` als eigene Schnittstelle `ula6` in
`/etc/config/network`, DHCPv6-Client `odhcp6c` nachinstalliert.
