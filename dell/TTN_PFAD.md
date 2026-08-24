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

## Die Grenze: TTN nimmt nur eigene DevAddr

Der Spiegel-Versuch am 24.08.2026 ist genau hier gescheitert, und zwar nicht
an einem Konfigurationsfehler:

```
GET /api/v3/ns/dev_addr_prefixes  ->  {"dev_addr_prefixes": ["260B0000/16"]}
```

Der Netzwerkserver von TTN verarbeitet **ausschliesslich** Adressen aus
`260Bxxxx`. Unsere Geraete tragen Adressen aus dem Bereich, den der lokale
ChirpStack vergibt — `00ECA902`, `018962E0`, `008469BB`. Der Gateway-Server
von TTS nimmt die Rahmen an (der Zaehler steigt), der Netzwerkserver verwirft
sie mangels passendem Praefix. Nachgemessen am Pico:

* Schluessel auf beiden Seiten identisch (SHA-256-Fingerabdruecke
  `516ae1feccde` fuer NwkSKey, `10562b94e5fc` fuer AppSKey)
* `mac_settings.resets_f_cnt = true` gesetzt
* TTS-Gateway-Zaehler steigt mit jedem Uplink
* `session.last_f_cnt_up` bei TTS: **nie gesetzt**

Ein ABP-Spiegel mit einer ChirpStack-Adresse kann also nicht funktionieren.
Wer ein Geraet in beiden Netzen haben will, muss die **DevAddr von TTN
vergeben lassen** (ABP-Geraet in der TTN-Konsole anlegen, TTS erzeugt eine aus
`260B…`) und dieselbe Sitzung anschliessend in ChirpStack **und** im Geraet
eintragen. Der umgekehrte Weg — erst bei TTN per OTAA joinen und die Sitzung
lokal nachtragen — wuerde die Sitzungshoheit an TTN abgeben und damit den
Krisenkanal von einer Aussenverbindung abhaengig machen.

## Das Rezept, das funktioniert

Weil die Adresse von TTN kommen **muss**, joint das Geraet dort — und die
entstandene Sitzung wandert anschliessend in den lokalen ChirpStack. Am
24.08.2026 am Pico durchgefuehrt, vier Schritte:

```bash
# 1. Geraet bei TTN als OTAA anlegen, AppKey kommt aus dem lokalen ChirpStack
/home/gh/.venv-chirpstack/bin/python ttn_otaa.py <dev_eui>

# 2. lokal stummschalten -- sonst gewinnt ChirpStack das Join-Rennen immer
#    (1,2 ms ueber LAN gegen rund 40 ms nach eu1). is_disabled statt
#    Schluessel loeschen: ein Aufruf macht es rueckgaengig.
/home/gh/.venv-chirpstack/bin/python cs_device_enable.py <dev_eui> off

# 3. Geraet neu joinen lassen -- beim Pico ueber die Konsole:
#    lwreset ; AT+JOIN     -> "LoRaWAN up: DevAddr 260B0BC4, newly joined"

# 4. TTN-Sitzung als ABP zurueck in den ChirpStack, Geraet wieder scharf
/home/gh/.venv-chirpstack/bin/python cs_abp_from_ttn.py <dev_eui> <ttn_dev_id>
```

Ergebnis, ein Uplink um 11:47:28:

```
TTN    pico-0e22  up  fPort 1  f_cnt 1  -84 dBm  A84041FFFF27E318
lokal  pico-0e22  up  fPort 1  f_cnt 1  -84 dBm  a84041ffff27e318
```

Ein Rahmen, zwei Netze, unterscheidbar an `source`. Gesendet wird weiterhin
lokal, ohne dass ein Join noetig waere — die Krisen-Hoheit bleibt damit auf
dem dell. Ein Vorbehalt: der AppKey liegt weiterhin auch im ChirpStack. Joint
das Geraet spaeter von sich aus neu, gewinnt wieder der lokale Server, und die
Adresse faellt aus dem TTN-Bereich heraus. Dann Schritt 2 bis 4 wiederholen.

## ABP-Geraete gehen den kuerzeren Weg

Der LA66 faehrt ohnehin ABP (`AT+NJM=0`) und braucht den Join-Umweg nicht.
Fuer ihn wird die Sitzung selbst gewaehlt — DevAddr aus `260B0000/16` — und in
alle drei Ebenen geschrieben: Geraet, TTN, ChirpStack. Kein Join, also auch
kein Rennen zwischen den Servern, und nichts, was spaeter von selbst
zurueckfallen koennte.

```bash
# im Geraet (9600 Baud): AT+DADDR=260B….  AT+NWKSKEY=…  AT+APPSKEY=…  ATZ
/home/gh/.venv-chirpstack/bin/python abp_session_apply.py <sitzung.json>
```

**`ATZ` nicht vergessen**: der LA66 quittiert die drei AT-Befehle mit `OK`,
benutzt die neue Sitzung aber erst nach dem Neustart. Vorher sendet er weiter
mit der alten Adresse, und beide Server verwerfen ihn.

## Damit es nicht zurueckfaellt: lokalen Join sperren

Bei Pico und TrackerD liegt der AppKey weiterhin auch im lokalen ChirpStack.
Joint so ein Geraet spaeter von sich aus neu — nach einem Stromausfall etwa —,
gewinnt wieder der lokale Server, und die Adresse faellt aus dem TTN-Bereich
heraus. Dagegen hilft das **Geraeteprofil**: eines mit `supports_otaa = false`
beantwortet keinen JoinRequest, verarbeitet die ABP-Sitzung aber unveraendert
weiter.

```bash
cs_local_join.py <dev_eui> off   # gesperrt: nur TTN darf noch joinen
cs_local_join.py <dev_eui> on    # zurueck zum OTAA-Profil
cs_local_join.py <dev_eui>       # nur nachsehen
```

Das ist der Unterschied zu `cs_device_enable.py`: `is_disabled` schaltet auch
das Mithoeren ab und taugt nur fuer die paar Sekunden des Umzugs, das Profil
ist der Dauerzustand.

**Die Empfangsfenster muessen dabei mitwandern.** Ein Geraet, das bei TTN
gejoint hat, uebernimmt dessen MAC-Parameter — am 24.08.2026 gemessen:
RX1-Verzoegerung **5 s**, RX2 auf **DR3** und **869,525 MHz**. ChirpStacks
ABP-Vorgabe ist eine andere; ohne Angleichung sendet der Krisen-Rundruf am
Fenster vorbei und keine Downlink kommt mehr an. `cs_local_join.py` liest die
Werte deshalb aus TTS und traegt sie ins neue Profil ein, statt sie zu raten.

Stand 24.08.2026: alle drei Geraete gesperrt (`pico-abp-eu868`,
`trackerd-abp-eu868`, `la66-abp-eu868`), Uplinks laufen weiter in beide Netze.

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
