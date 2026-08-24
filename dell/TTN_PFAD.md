# Zweiter Weg: derselbe Funkverkehr auch an TTN

**TTN lief die ganze Zeit schon.** Das war die Ueberraschung des
24.08.2026: in `local_conf.json` steht beim TTN-Eintrag `"enable": "false"` —
aber als **String**, und den wertet der Forwarder als wahr. Das Gateway
schickt seit dem 14.08.2026 an `eu1.cloud.thethings.network`, nachweisbar an
zwei Stellen:

```
logread:  [PKTS~][server-UP] {"stat":{...}}
          [INFO~][NETWORK][server-UP]   PUSH_ACK received in 37 ms

TTS:      connected_at             2026-08-14T15:51:05Z
          last_uplink_received_at  2026-08-24T08:42:46Z   (der Pico-Test)
          uplink_count             4876
          protocol                 udp
```

Ein zusaetzlicher Weg vom dell aus ist damit ueberfluessig: er wuerde jeden
Uplink ein zweites Mal bei TTS abliefern. Das TTN-Backend im Multiplexer war
deshalb nur rund 20 Minuten aktiv und ist wieder entfernt.

## Der Multiplexer bleibt, faechert aber nur noch lokal

`chirpstack-packet-multiplexer` 4.0.1 sitzt weiterhin auf UDP :1700 vor dem
Gateway Bridge (der auf `127.0.0.1:1710` gerueckt ist), hat aber nur noch ein
Ziel. Er ist damit ein Durchreicher — nuetzlich, wenn spaeter ein weiteres
Ziel dazukommen soll, ansonsten eine Schicht mehr im Weg. Rueckbau:

```bash
sudo systemctl disable --now chirpstack-packet-multiplexer
sudo cp /etc/chirpstack-gateway-bridge/chirpstack-gateway-bridge.toml.vor-multiplexer \
        /etc/chirpstack-gateway-bridge/chirpstack-gateway-bridge.toml
sudo systemctl restart chirpstack-gateway-bridge
```

Der Rohkanal (UDP :1702 -> `lora_raw.py`) laeuft an beidem vorbei.

## Warum nicht am Gateway schrauben

Sollte der TTN-Eintrag doch einmal wirklich abgeschaltet werden: das kostet
einen Neustart des Paket-Forwarders, und dort laeuft ein **angepasster**
Forwarder, der den Syncword des Rohkanals nach dem Start in die Register
schreibt (`/etc/init.d/lora_gw.orig-syncword` liegt als Sicherung daneben).
Jeder Neustart gefaehrdet den Krisenkanal — deshalb im Zweifel lieber auf dem
dell eingreifen.

## Logging nach MariaDB: fehlt noch ein Anwendungs-Schluessel

`ttn_log.py` ist ausgerollt (`/home/gh/python/ttn_log.py`), die Unit
`ttn-log.service` installiert, aber **abgeschaltet**. Der vorhandene
Schluessel taugt dafuer nicht:

```
Name    GerontecTTNapi
Entity  gateway_ids: eui-a84041ffff27e318
Rechte  14, alle RIGHT_GATEWAY_* (inkl. RIGHT_GATEWAY_ALL)
```

Das ist ein **Gateway**-Schluessel, kein Anwendungs-Schluessel — der
MQTT-Broker der Anwendung antwortet darauf mit `Not authorized`. Er liegt
deshalb als `~/.config/ttn/gateway.key` (nicht `lenggries.key`, sonst greifen
die Skripte in `ttn/` daneben).

Gut ist er trotzdem: mit ihm sieht man, was **TTS selbst** vom Gateway haelt.

```bash
curl -sH "Authorization: Bearer $KEY" \
  https://eu1.cloud.thethings.network/api/v3/gs/gateways/eui-a84041ffff27e318/connection/stats
```

Fuer Logging und Geraeteeintraege braucht es einen zweiten Schluessel auf der
**Anwendung** `lenggries-sensors`:

| Zweck | Recht |
|---|---|
| `ttn_log.py` | `RIGHT_APPLICATION_TRAFFIC_READ` |
| `ttn/ttn_register.py` | zusaetzlich `RIGHT_APPLICATION_DEVICES_READ/WRITE` |

Ablegen als `TTN_KEY=NNSXS....` in `~/.config/ttn/lenggries.key` auf dem dell,
dann `sudo systemctl enable --now ttn-log.service`.

## Was ueber TTN ankommt — und was nicht

Solange ein Geraet nur im lokalen ChirpStack eingetragen ist, verwirft TTS
seine Rahmen (unbekannte DevAddr) — obwohl das Gateway sie brav abliefert.
Erst ein Geraet, das **zusaetzlich** bei TTN als ABP mit derselben Sitzung
eingetragen ist, taucht dort auf und erzeugt in `loradevice` je Uplink zwei
Zeilen, eine je Netz:

```sql
SELECT * FROM loradevice WHERE application LIKE 'ttn:%';   -- ueber TTN
SELECT * FROM loradevice WHERE application NOT LIKE 'ttn:%';
```

Der eigentliche Gewinn steht dann in der Spalte `gateway_id`: TTS meldet
**jede** Empfangsstelle, also auch fremde Gateways. Wer einen Uplink ausser
dem eigenen DLOS8N noch gehoert hat — etwa `B827EBFFFE3CEC15` am Lenggrieser
Gymnasium, 970 m entfernt — steht damit gemessen in der Datenbank statt
geschaetzt.
