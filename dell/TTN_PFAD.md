# Zweiter Weg: derselbe Funkverkehr auch an TTN

Seit 24.08.2026 gibt der dell den Gateway-Strom zusaetzlich an
`eu1.cloud.thethings.network` weiter. Der lokale ChirpStack bleibt
unveraendert massgeblich.

## Warum auf dem dell und nicht am Gateway

Das DLOS8N hat einen Server-Slot fuer TTN (`gateway.server1`, `provider
ttn_V3`), der steht auf `enable: false`. Ihn einzuschalten waere ein Zweizeiler
— kostet aber einen Neustart des Paket-Forwarders. Dort laeuft ein
**angepasster Forwarder**, der den Syncword des Rohkanals nach dem Start in die
Register schreibt (`/etc/init.d/lora_gw.orig-syncword` liegt als Sicherung
daneben). Jeder Neustart gefaehrdet damit den Krisenkanal.

Auf dem dell ist derselbe Effekt jederzeit ruecknehmbar. **Am Gateway wurde
nichts geaendert.**

## Aufbau

```
DLOS8N 192.168.178.106
   |
   | UDP :1700 (Semtech)
   v
chirpstack-packet-multiplexer          <- neu, 4.0.1 aus dem ChirpStack-Repo
   |                     \
   | :1710                \ eu1.cloud.thethings.network:1700
   v                       v
gateway-bridge          TTN            uplink_only = true
   |                       |
   v                       v
ChirpStack -> MQTT      TTS-Broker (MQTT 8883)
   |                       |
   v                       v
lora_log.py             ttn_log.py     -> beide nach wagodb.loradevice
```

Der Rohkanal (UDP :1702 -> `lora_raw.py`) laeuft daran vorbei und ist
unberuehrt.

**TTN darf nur hoeren** (`uplink_only = true`). Zwei antwortende Netze wuerden
auf derselben DevAddr mit eigenen `FCntDown` senden und sich im selben
RX-Fenster gegenseitig zerstoeren; ausserdem sieht die TTN-Fair-Use-Richtlinie
nur zehn Downlinks am Tag vor. Die Downlink-Hoheit — und damit der
Krisen-Rundruf — bleibt beim lokalen ChirpStack.

## Nachweis

Ein von Hand ausgeloester Pico-Uplink (`lwsend`) am 24.08.2026, 10:42:46:

```
listener  PushData  gateway_id=a84041ffff27e318  token=19139
forwarder Sending   127.0.0.1:1710       -> PushAck token=19139
forwarder Sending   52.212.223.226:1700  -> PushAck token=19139
```

Beide Seiten quittieren denselben Token — TTS nimmt das Gateway also an. Der
lokale Weg schreibt unveraendert weiter in `loradevice`.

## Was noch fehlt: der API-Key

`ttn_log.py` ist ausgerollt (`/home/gh/python/ttn_log.py`), die Unit
`ttn-log.service` liegt installiert, aber **gestoppt**. Es fehlt allein der
Schluessel:

1. TTN-Konsole -> Applications -> `lenggries-sensors` -> API keys -> Add
2. Recht: **Read application traffic (uplink and downlink)**
3. Ablegen als `TTN_KEY=NNSXS....` in `~/.config/ttn/lenggries.key` auf dem
   dell (dasselbe Format, das `ttn/ttn_register.py` erwartet)
4. `sudo systemctl enable --now ttn-log.service`

Der alte Schluessel ist nicht auffindbar: weder auf dem dell noch im Repo, und
laut `git log -S` war auch nie einer eingecheckt.

## Was ueber TTN ankommt — und was nicht

Solange ein Geraet nur im lokalen ChirpStack eingetragen ist, verwirft TTS
seine Rahmen (unbekannte DevAddr). In `loradevice` erscheint es dann weiterhin
nur einmal. Erst ein Geraet, das **zusaetzlich** bei TTN als ABP mit derselben
Sitzung eingetragen ist, erzeugt je Uplink zwei Zeilen — eine je Netz.
Auseinanderhalten:

```sql
SELECT * FROM loradevice WHERE application LIKE 'ttn:%';   -- ueber TTN
SELECT * FROM loradevice WHERE application NOT LIKE 'ttn:%';
```

Der eigentliche Gewinn steht in der Spalte `gateway_id`: TTS meldet **jede**
Empfangsstelle, also auch fremde Gateways. Wer den Uplink ausser dem eigenen
DLOS8N noch gehoert hat — etwa `B827EBFFFE3CEC15` am Lenggrieser Gymnasium,
970 m entfernt — steht damit messbar in der Datenbank, statt geschaetzt zu
werden.

## Zurueckbauen

```bash
sudo systemctl stop chirpstack-packet-multiplexer
sudo cp /etc/chirpstack-gateway-bridge/chirpstack-gateway-bridge.toml.vor-multiplexer \
        /etc/chirpstack-gateway-bridge/chirpstack-gateway-bridge.toml
sudo systemctl restart chirpstack-gateway-bridge
```
