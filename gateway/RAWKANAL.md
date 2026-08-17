# Roher LoRa-Kanal neben der LoRaWAN-Kette

Stand **16.08.2026**. Ziel: der P2P-Kanal des TrackerD wird vom DLOS8N gehört,
und die Nutzlast ist von `192.168.5.23` aus verwendbar — ohne LoRaWAN, ohne
Verschlüsselung, ohne den laufenden ChirpStack-Betrieb anzufassen.

## Warum das überhaupt geht

Auf dem Gateway wird an **keiner Stelle** ver- oder entschlüsselt. Der SX1302
hat keine Krypto-Einheit; LoRaWAN verschlüsselt ausschließlich die FRMPayload,
und zwar auf dem Node, bevor der sie seinem eigenen Funkchip über SPI übergibt.

```
Node-MCU:  Klartext --AES-128--> FRMPayload --> SPI --> SX1276 --> Funk
                                 (LoRaMac-node, VOR dem SPI des Nodes)
                                                            |
Gateway:   Funk --> SX1302 --> SPI /dev/spidev1.0 --> libloragw lgw_receive()
                                                            |  lgw_pkt_rx_s.payload[]
                                                            |  byte-identisch wie auf Luft
                                                            v
           fwd --> base64 --> {"rxpk":[{"data":"..."}]} --> Semtech-UDP
                                                            |  Klartext-UDP, keine TLS
                                                            v
Server:    ChirpStack --> HIER erst: MIC-Prüfung (NwkSKey), FRMPayload
                          entschlüsseln (AppSKey bzw. NwkSKey bei FPort 0)
```

Der Forwarder interpretiert das MAC nicht einmal — `local_conf.json` hat
`"mac_decode": false` und alle vier Filter (`fport`, `devaddr`, `nwkid`,
`deveui`) auf 0. Er reicht also jede demodulierte PHYPayload roh durch.

Nebenbei: MHDR, DevAddr, FCnt und FPort liegen bei LoRaWAN ohnehin **im
Klartext auf der Luft**, nur der MIC schützt sie gegen Manipulation.

## Die drei Hürden

**1. Das Syncword — chipweit stimmt nur für die 8 MultiSF-Kanäle.**
`global_conf.json` hat `"lorawan_public": true` → Syncword **0x34**, und einen
Parameter pro Kanal gibt es tatsächlich nicht.

**Diese Hürde ist seit dem 17.08.2026 aber nur noch eine halbe.** Der SX1302
hat nicht ein Syncword-Register, sondern **vier**, und eines davon gehört
allein dem Rohkanal:

| Registerpaar | Adressen | gilt für |
|---|---|---|
| `SF5_PEAK1/2` | `0x588A/0x588B` | alle 8 MultiSF-Kanäle, nur SF5 |
| `SF6_PEAK1/2` | `0x588C/0x588D` | alle 8 MultiSF-Kanäle, nur SF6 |
| `SF7TO12_PEAK1/2` | `0x588E/0x588F` | alle 8 MultiSF-Kanäle, SF7–12 |
| `LORA_SERVICE_PEAK1/2` | `0x5B2E/0x5B2F` | **nur `chan_Lora_std`** |

Die 8 MultiSF-Kanäle teilen sich einen Demodulator-Block, dessen Syncword nur
nach Spreizfaktor aufgeteilt ist — *einer* von diesen 8 kann also weiterhin
kein eigenes Syncword bekommen, das ist eine Eigenschaft des Chips.
`chan_Lora_std` kann es sehr wohl. Nur schreibt der HAL dort stur 0x12 oder
0x34, abgeleitet aus `lorawan_public`.

`sx1302_syncword/` macht dieses Register zugänglich: ein `LD_PRELOAD`-Shim
ersetzt genau eine HAL-Funktion und liest die Werte aus
`/etc/lora/syncword.conf`. Damit läuft der Rohkanal auf einem **beliebigen**
Syncword 0x00–0xFF, während die 8 LoRaWAN-Kanäle unangetastet auf 0x34 bleiben
— gleichzeitig, ohne Umschalten. Details und Messungen dort im README.

→ Konsequenz **neu**: der Node muss sich *nicht* mehr anpassen. Die
Umstellung der TrackerD-P2P-Firmware von `0x12` auf `0x34`
(`devices/trackerd_p2p/p2p/src/main.cpp`, `cfgSync`) war unter der alten
Annahme nötig und kann zurückgenommen werden.

**2. CRC.** Pakete ohne CRC verwirft der Forwarder, solange
`forward_crc_disabled` false ist. Der Rohkanal-Server hat das Flag auf `true`,
damit auch Sender ohne CRC durchkommen. Der TrackerD sendet ohnehin mit CRC
(`cfgCrc = true`).

**3. ChirpStack filtert.** Der Netzwerkserver parst MHDR/DevAddr und verwirft
alles, was kein gültiges LoRaWAN-Frame ist. Deshalb wird **neben** der
LoRaWAN-Kette abgegriffen, nicht dahinter.

## Aufbau

```
                   TrackerD (app1, P2P-Firmware)
                   868.125 MHz / SF7 / BW125 / Sync 0x34 / CRC an
                              |
                              v
   +-------------------------------------------------------+
   |  DLOS8N 10.9.0.9   fwd -d sx1302                       |
   |  chan_multiSF_0..7  LoRaWAN  867.1-868.5               |
   |  chan_Lora_std      ROHKANAL 868.125 SF7 BW125         |
   +-------------------------------------------------------+
        |                    |                    |
        | server1            | server2            | server3
        v                    v                    v
   eu1.cloud.thethings  192.168.5.23:1700    192.168.5.23:1702
     .network:1700      chirpstack-gw-bridge  lora_raw.py
     (TTN, unverändert)  -> ChirpStack         -> stdout + MQTT lora/raw
                            (verwirft Rohes)      (Rohbytes, ungefiltert)
```

Jeder Server bekommt **alle** rxpk — der Forwarder filtert nicht pro Server.
Getrennt wird auf der Gegenseite: `lora_raw.py` nimmt nur, was auf
868.125 MHz ± 20 kHz hereinkommt, ChirpStack ignoriert dasselbe Paket
mangels gültigem LoRaWAN-Rahmen.

### Kanalwahl

`chan_Lora_std` ist der richtige Kanal: ein eigenständiger Modem-Block mit
festem SF/BW, unabhängig von den acht multiSF-Kanälen. Die multiSF-Kanäle
bringen nichts, weil sie sich einen Modem-Block teilen und ohnehin alles hören.

Er stand auf 868.3 MHz / BW 250 / SF7, also auf LoRaWAN **DR6**, und liegt
jetzt auf **868.125 MHz / BW 125 / SF7** — exakt der Werksvorgabe der
TrackerD-P2P-Firmware (`cfgFreq = 868125000`). Damit muss am Node nur das
Syncword geändert werden. Verloren geht dadurch DR6, das praktisch kein Gerät
benutzt.

`if` = 868125000 − 868500000 = **−375000** relativ zu radio_1. Innerhalb der
erprobten ±400 kHz, die auch die multiSF-Kanäle nutzen.

Der Kanal liegt 25 kHz neben `chan_multiSF_0` (868.1). Pakete werden daher
teils doppelt gehört — einmal über den Rohkanal, einmal über multiSF_0. Das ist
unschädlich (die Gegenseite filtert auf 868.125) und war der Weg, auf dem der
Empfang ursprünglich nachgewiesen wurde.

### Funkrechtliches

868.0–868.6 MHz (ERC 70-03 h1.3): **25 mW ERP, 1 % Duty Cycle**. Die Firmware
steht auf `cfgPower = 17` dBm ≈ 50 mW und liegt damit über dem Limit — für den
Dauerbetrieb auf **14 dBm** (= 25 mW) stellen, per `AT+POWER=14` oder im
Quelltext. Bewusst *nicht* stillschweigend geändert, weil es die Reichweite
kostet.

Das 10-%-Band 869.4–869.65 MHz wäre für einen Krisenkanal attraktiver, ist aber
von radio_1 (868.5 MHz, ±400 kHz) nicht erreichbar, ohne die LoRaWAN-Kanäle
868.1/868.3/868.5 mitzuverschieben.

## Persistenz — zwei Fallen

**Falle 1: `global_conf.json` und `local_conf.json` werden bei jedem Start neu
erzeugt.** `/etc/init.d/lora_gw` ruft `/usr/bin/generate-config.sh` auf. Ein
direktes Editieren der beiden Dateien ist nach dem nächsten Reboot weg.

**Falle 2: der UCI-Weg für Kanäle ist eine Sackgasse.** `generate-config.sh`
baut die Kanäle nur dann aus UCI (`gateway.general.chan*`, `lorachan*`), wenn
`gateway.general.gwcfg` auf `CUS` steht. Bei `EU` — dem Ist-Zustand — wird
stattdessen `/etc/lora/cfg-302/EU-global_conf.json` einfach **kopiert**.

Auf `CUS` umzustellen wäre gefährlich: `gen_cus_cfg()` ist erkennbar noch für
den SX1301 geschrieben und setzt `rssi_offset -166.0` (richtig für SX1250 wäre
−215.4, also ~50 dB daneben), `clksrc 1` statt 0 und eine `tx_lut_*`-Tabelle im
alten Format statt `tx_gain_lut`.

→ Der Kanal wird deshalb in der **Quelldatei der Kopie** geändert:
`/etc/lora/cfg-302/EU-global_conf.json`. Welche Datei das ist, wurde per md5
bestimmt (identisch mit dem aktiven `global_conf.json`). Original liegt als
`.orig` daneben.

Für `local_conf.json` gilt das Gegenteil: die wird komplett aus UCI erzeugt,
also gehört der dritte Server nach UCI — siehe unten.

## Änderungen im Einzelnen

### Gateway 10.9.0.9

| Datei | Änderung | Sicherung |
|---|---|---|
| `/etc/lora/cfg-302/EU-global_conf.json` | `chan_Lora_std` → `if −375000`, `bandwidth 125000` | `.orig` |
| `/usr/bin/generate-config.sh` | dritter Server-Block aus `gateway.server3.*` | `.orig` |
| `/etc/config/gateway` | neue Sektion `gateway.server3` | UCI |
| `/etc/config/firewall` | WAN-Zone `input` REJECT → ACCEPT | `.bak-20260816` |

Der Generator kennt von Haus aus nur zwei Server-Slots. Der Patch
(`generate-config.sh.patch`) hängt additiv einen dritten an, gesteuert über
`gateway.server3.enable`. Bei `server2` sind die CRC-Flags im Skript
hartkodiert, bei `server1` und dem neuen `server3` kommen sie aus UCI — nur
deshalb lässt sich `forward_crc_disabled` für den Rohkanal setzen.

```sh
uci set gateway.server3=server
uci set gateway.server3.enable=1
uci set gateway.server3.server_id=raw-dell
uci set gateway.server3.server_address=192.168.5.23
uci set gateway.server3.upp=1702
uci set gateway.server3.dpp=1702
uci set gateway.server3.forward_crc_error=0
uci set gateway.server3.forward_crc_disabled=1
uci commit gateway
/etc/init.d/lora_gw restart
```

`generate-config.sh` meldet dabei vier `uci: Entry not found` — das ist
Alt-Rauschen des Vendor-Skripts (`gateway.general.provider` ist ungesetzt) und
war vorher schon so.

### dell-3660 192.168.5.23

`dell/lora_raw.py` → `/home/gh/python/lora_raw.py`, als `lora-raw.service`
(`enable --now`). Semtech-UDP v2 auf 1702: beantwortet PUSH_DATA mit PUSH_ACK
und PULL_DATA mit PULL_ACK, filtert rxpk auf den Rohkanal, gibt Hex und — wenn
die Bytes wie Text aussehen — Klartext aus, und veröffentlicht mit `--mqtt` auf
`lora/raw`.

Senden geht über `--send TEXT`: sobald das Gateway sein PULL_DATA schickt,
antwortet das Skript mit PULL_RESP/`txpk`. Wichtig dabei `"ipol": false` — die
invertierte Polarität ist eine LoRaWAN-Eigenheit der Downlinks, ein P2P-Node
hört sonst nichts. Und `"rfch": 0`, weil nur radio_0 `tx_enable` hat.

### TrackerD

`devices/trackerd_p2p/p2p/src/main.cpp`: `cfgSync` von `0x12` auf **`0x34`**.
Die Konfiguration der P2P-Firmware lebt nur im RAM und steht nach jedem Start
wieder auf den Defaults — ohne diese Quelltextänderung müsste nach jedem Reset
von Hand `AT+SYNCWORD=0x34` gesetzt werden.

Zur Laufzeit ohne Neuflashen:

```
AT+SYNCWORD=0x34
AT+FRE=868.125
AT+SF=7
AT+BW=125000
AT+SEND=hallo
```

## Was verifiziert ist

- **Roher Empfang grundsätzlich**: schon am 15.08. nachgewiesen — TrackerD auf
  868.100/SF7/BW125/Sync 0x34, der Konzentrator demoduliert sauber und schiebt
  die Nutzlast unverändert als `rxpk.data` weiter (`stat:1`, RSSI −77, 6,5 kHz
  Quarzversatz). Der Forwarder liest das Muster anschließend als LoRaWAN-Frame
  und verhaspelt sich erwartungsgemäß (DevAddr „KCAR" aus `RACK`).
- **Kanal aktiv**: `/etc/lora/desc` meldet nach dem Neustart
  `chan_Lora_std: RAW P2P, 125kHz, SF7, 868.125 MHz (TrackerD)`; der
  Konzentrator startet ohne Fehler, `if −375000` wird akzeptiert.
- **Drei Server laufen**: `[THREAD][raw-dell] Semtech UP service Starting...`
  plus `[SETTING][raw-dell] packets received with a no CRC will be forwarded`.
- **Strecke Gateway→dell**: `[NETWORK][raw-dell-DOWN] PULL_ACK received in 0 ms`,
  Statistikpakete kommen auf 1702 an.
- **Empfangspfad auf dell**: mit einem synthetischen PUSH_DATA geprüft —
  PUSH_ACK `02abcd01` korrekt, Paket geparst, gefiltert, ausgegeben als
  `868.125 MHz SF7BW125 ch8 RSSI -77 SNR 9.2 CRC ok 16B 545241…` mit
  Klartext `"TRACKERD-TEST 42"`, und auf `lora/raw` veröffentlicht.

### Ergänzung 17.08.2026 — eigenes Syncword auf dem Rohkanal

- **Rohkanal mit eigenem Syncword**: `chan_Lora_std` auf **0x55**, die 8
  MultiSF-Kanäle gleichzeitig weiter auf **0x34**. Beim Start meldet der
  Forwarder `[syncword] multi-SF ch0-7: SF5=0x12 SF6=0x12 SF7-12=0x34 |
  Lora_std (SF11): 0x55`. Registerkontrolle im laufenden Betrieb mit
  `sx1302_poke`: `0x5B2E = 0x0A`, `0x5B2F = 0x0A`.
- **Ebyte E22 empfangen**: E22-900T (USB, Werkskonfig 2.4k = SF11/BW500,
  Kanal 18 = 868.125 MHz) am Regeldienst empfangen — `chan 8`, `SF11BW500`,
  RSSI −63 dBm, `stat:1`. Nutzlast nach XOR 0x12 exakt `PROD-03`.
  Rahmenformat: `2C 12 <2B lfd> 00 FF FF <len> | Nutzlast XOR 0x12`, wobei
  Byte 1 die Kanalnummer *und* zugleich der XOR-Schlüssel ist.
- **LDRO muss erzwungen werden**: der HAL leitet es aus
  `SET_PPM_ON(bw, dr)` ab, das bei **BW500 nie** greift; Ebyte sendet aber mit
  LDRO 1. Ohne Override rastet der Header ein und jede Nutzlast käme mit
  CRC-Fehler. Der Shim setzt `0x5B22` Bits 4–5 auf 1 (`ldro = 1` in
  `syncword.conf`), kontrolliert als `0x5B22 = 0x98`.
- **LoRaWAN unverändert funktionsfähig** (Regressionstest mit LA66-USB,
  EU868 v1.3, DevEUI `A840 4117 F189 62E0`, bereits gejoint): Uplink auf
  868.500 MHz DR0 kommt auf `chan 2` an, `SF12BW125`, RSSI −85, `stat:1`.
  Frame sauber: MHDR `0x40` Unconfirmed Data Up, DevAddr `0x018962E0`,
  FCnt 0, FPort 2, Nutzlast `LORAWN`. Der Eingriff berührt die LoRaWAN-Kette
  also nachweislich nicht.
- **Zeitmultiplex geprüft und verworfen**: eine Syncword-Umschaltung des
  MultiSF-Paares kostet gemessene 295 µs, hin und zurück 590 µs — schnell
  genug gegenüber dem SF7-Sync-Fenster von 2050 µs. Es scheitert trotzdem,
  weil es **keinen Trigger** gibt: die Paketerkennung *ist* der
  Syncword-Vergleich. Blindes Duty-Cycling wäre ein Nullsummenspiel und ist
  gegenüber dem eigenen Register des Service-Modems immer schlechter.

**Noch nicht verifiziert**, weil der TrackerD gerade nicht angesteckt ist
(`/dev/ttyACM0` fehlt): der Funkweg über den neuen Kanal 868.125 mit der
geänderten Firmware, und der Sendeweg `--send`.

## Alternative: ChirpStack als Roh-Router

Geprüft, funktioniert, aber nur zur Hälfte:

- Der **`chirpstack-gateway-bridge`** parst die Nutzlast **nicht**. Er baut
  rxpk auf MQTT um und veröffentlicht — hier mit `marshaler="json"` — unter
  `eu868/gateway/a84041ffff27e318/event/up`. Die Rohbytes stehen dort also
  bereits als JSON zur Verfügung, ohne jede Gateway-Änderung.
- Der **Netzwerkserver dahinter** kann es nicht: er parst MHDR/DevAddr, findet
  kein Gerät bzw. keinen gültigen MIC und verwirft.

Ein Abgriff auf `event/up` wäre also möglich und spart den dritten Server —
hängt dafür aber an ChirpStack: läuft die Bridge nicht, ist auch der Rohkanal
still. Der eigene UDP-Server ist davon unabhängig und kann zusätzlich
`forward_crc_disabled` setzen, was über die Bridge nicht steuerbar ist.

## Rückbau

```sh
# Gateway
cp /etc/lora/cfg-302/EU-global_conf.json.orig /etc/lora/cfg-302/EU-global_conf.json
cp /usr/bin/generate-config.sh.orig /usr/bin/generate-config.sh
uci delete gateway.server3 && uci commit gateway
/etc/init.d/lora_gw restart

# dell
sudo systemctl disable --now lora-raw.service
```

## Offene Punkte

- TrackerD anstecken, Firmware mit `cfgSync = 0x34` neu flashen (app1, über
  `switch_app.py` — **nie** `pio run -t upload`), Funkweg auf 868.125 messen.
- Sendeweg `--send` gegen den TrackerD gegenprüfen (`ipol:false`, `rfch:0`).
- Sendeleistung auf 14 dBm entscheiden (25 mW ERP ist das Limit in h1.3).
- `server1` (TTN) hat im erzeugten `local_conf.json` ein `"enable": "false"`,
  das als **String** geschrieben wird (`generate-config.sh`, hartkodiert) und
  vom Forwarder ignoriert wird — der Server läuft. Roher Verkehr geht damit
  auch an TTN. Soll TTN bleiben, ist das hinzunehmen; sonst `gateway.server1`
  umbiegen oder den Slot leeren.
