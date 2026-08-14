# Endgeräte am Gateway Lenggries

TTN-Anwendung: **`lenggries-sensors`** (Konto `lenggries`, eu1), angelegt 14.08.2026.

| Gerät | DevEUI | JoinEUI | Modus | Rolle |
|---|---|---|---|---|
| Dragino **TrackerD** | `A840414F1188076C` | `A840410000000102` | OTAA | GPS-Tracker, Position → Traccar |
| Dragino **LA66 USB-Adapter v1.3** | `A8404117F18962E0` | `A840410000000101` | OTAA | Krisen-/Notfallgerät, siehe unten |
| Dragino **LHT65** | (aus Gateway-DB) | — | ABP, Altbestand | Temperatur/Feuchte, noch nicht migriert |

Der AppKey des TrackerD steht seit 14.08.2026 unten in diesem Dokument —
bewusste Entscheidung des Eigentümers, obwohl das Repo öffentlich ist. Wer
den Schlüssel hat, kann Funksprüche dieses Geräts entschlüsseln und sich mit
einem beliebigen Radio als das Gerät ausgeben. Das Gerät gilt damit als
öffentlich; wer das nicht will, setzt per AT einen neuen AppKey und trägt ihn
im Netzserver nach. Die übrigen Schlüssel liegen auf heissa.de unter
`~/.config/ttn/` bzw. auf dem Aufkleber des jeweiligen Geräts.

## TrackerD

GPS-Tracker mit ESP32, roter Alarmtaste und USB-C. Meldet sich mit OTAA;
der AppKey ist **gerätespezifisch**, es gibt keinen dokumentierten
Werksschlüssel.

### Der Port verschwindet — und woran es wirklich lag

Am USB-C sitzt ein CH9102 (`1a86:55d4`), der als `ttyACM0` erscheint und rund
1,3 s später wieder weg ist:

```
usb 1-3: New USB device found, idVendor=1a86, idProduct=55d4
cdc_acm 1-3:1.0: ttyACM0: USB ACM device
usb 1-3: USB disconnect, device number 21
```

Verursacher ist `ModemManager`: der probt den Port als Modem, toggelt dabei
DTR/RTS und wirft den ESP32 in den Reset — und weil der CH9102 an dessen
Versorgung hängt, reißt gleich die ganze USB-Verbindung ab. Es ist also kein
Wackelkontakt und keine Firmware-Eigenheit. Abhilfe ist `laptop/99-trackerd.rules`,
die dem ModemManager das Gerät verbietet und nebenbei den festen Namen
`/dev/trackerd` vergibt. Danach funktioniert esptool auf Anhieb:

```
Chip type:  ESP32-PICO-D4 (revision v1.1)   MAC: 64:b7:08:89:17:e0
Flash:      c8 4016, 4 MB, 3,3 V
```

### AppKey aus dem Flash

Der Schlüssel muss nicht vom Aufkleber abgetippt werden — er steht im NVS.
`esptool read-flash 0 0x400000` zieht die 4 MB, `laptop/nvsfind.py` parst die
Partitionstabelle und das NVS. Der Treffer liegt in Namensraum 1 unter dem
Schlüssel `eeprom0`, und zwar als ein Block in genau dieser Reihenfolge:

| Bytes | Inhalt |
|---|---|
| 0–7 | DevEUI, LSB zuerst (`6c0788114f4140a8`) |
| 8–15 | JoinEUI, LSB zuerst (`02010000004140a8`) |
| 16–31 | **AppKey**, MSB zuerst |
| ab 32 | Sitzungsschlüssel — ändern sich bei jedem Join, der AppKey nicht |

Genau daran erkennt man den Wurzelschlüssel: über mehrere NVS-Versionen
hinweg bleiben die 16 Byte stehen, während der Rest wandert.

```
TrackerD AppKey: 1ACAB4E552DBE9BCBF86FEE167E3CC43
```

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

Am 14.08.2026 so verifiziert, an zwei am Gateway mitgeschnittenen
Join-Requests (DevNonce 2673 und 58678): MIC stimmt beide Male. Der Schlüssel
aus dem NVS ist also der richtige, ohne dass dafür ein Join durchlaufen musste.

### Registrierung im lokalen ChirpStack

`dell/cs_trackerd.py` legt Anwendung, Profil und Gerät an — OTAA statt ABP,
weil der TrackerD keine auslesbaren Sitzungsschlüssel hat, und **Class A**
statt Class C wie beim LA66, weil er am Akku hängt. Der Payload-Decoder
`trackerd.js` wird als JS-Codec ins Profil gelegt.

Zwei Fallen, beide im Skript abgefangen:

- `CreateDevice` meldet eine Doublette nicht als `ALREADY_EXISTS`, sondern
  reicht den Postgres-Fehler als `INTERNAL: duplicate key value` durch.
- Anwendungen und Profile dürfen mehrfach denselben Namen tragen. Ein zweiter
  Lauf legt also stillschweigend Karteileichen an, statt das Vorhandene zu
  finden — deshalb erst suchen, dann anlegen. `dell/cs_dedupe.py` räumt weg,
  was schon entstanden ist (löscht nur leere Anwendungen und unbenutzte Profile).

Solange die Schlüssel fehlen, quittiert ChirpStack jeden Join-Request mit
`Join Server client for join_eui … does not exist` — das klingt nach fehlender
Join-Server-Konfiguration, heißt aber schlicht: zu diesem JoinEUI ist hier
kein Gerät mit Schlüsseln bekannt.

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

### Was der rote Knopf wirklich tut

Quelle: [dragino/TrackerD](https://github.com/dragino/TrackerD), namentlich
[`extiButtonLS.cpp`](https://github.com/dragino/TrackerD/blob/main/Example/LoRaWAN/examples/TrackerD/extiButtonLS.cpp)
und [`TrackerD.ino`](https://github.com/dragino/TrackerD/blob/main/Example/LoRaWAN/examples/TrackerD/TrackerD.ino).
Die Firmware ist ein Arduino-Sketch; unser Gerät ist `sensor_type == 13`.

Die **Haltezeit** entscheidet, in drei Stufen (`attachDuringLongPress1()`):

| Gedrückt | Wirkung | LED |
|---|---|---|
| 2–10 s | `sys.alarm = 1` → **Alarm** | rot + grün |
| 10–30 s | `sys.sleep_flag = 1` → Standby | rot + blau |
| > 30 s | `sys.alarm = 1; alarm();` | rot |

Die untere Grenze ist `sys.exit_alarm_time`, in `TrackerD.ino:1301` auf
**2000 ms** gesetzt und per `AT+EAT` oder Downlink änderbar.

Die mittlere Stufe ist die Falle. Beim Loslassen greift dort
`attachLongPressStop1()`:

```c
else if (sys.sleep_flag == 1) {
  if (LongPress1 == 1) {
    sys.gps_alarm = 0;
    sys.alarm     = 0;
    sys.alarm_count = 0;
    myIMU2.imu_power_down();     // Beschleunigungssensor stromlos
  }
}
```

Wer in diesem Fenster loslässt, schaltet den Alarm also ab statt ein — und
nimmt den Bewegungssensor gleich mit, der der Auslöser der regulären
Positionsmeldungen ist (`Transport: "STILL"` im dekodierten Uplink). Aus
diesem Zustand hilft zuverlässig nur ein harter Reset über USB.

**Vorsicht bei der Diagnose:** Ausbleibende Uplinks beweisen das noch nicht.
Beim Test am 14.08.2026 blieb es nach dem Knopfdruck rund 2½ Minuten
vollständig still — auch auf Gateway-Ebene — und der Alarm kam dann doch. Wer
zu früh urteilt, hält eine normale Sendepause für einen abgeschalteten Sensor.

### Wie der Alarm im Rahmen aussieht

Zwei Uplinks desselben Geräts, fPort 2, 15 Byte, einmal ruhig und einmal
ausgelöst:

```
ruhig  00000000000000000df62001640179   fCnt 2, RSSI -103
Alarm  00000000000000004de6200167015d   fCnt 3, RSSI  -90
                       ^^
```

Es ist ein einziges Bit: **Byte 8, Bit 6** (`bytes[8] & 0x40` im Decoder).
Der Rest des Unterschieds ist Messrauschen — Byte 8/9 tragen ohne die oberen
zwei Bits die Batteriespannung (`0x0df6` = 3574 mV), Byte 11/12 die Feuchte
(35,6 → 35,9 %), Byte 13/14 die Temperatur (37,7 → 34,9 °C). Die ersten acht
Byte sind Breite und Länge, hier mangels Fix durchgehend null.

Zwei weitere Eigenheiten, die im Datenblatt fehlen:

- **Ein kurzer Druck tut nichts.** `attachClick` und `attachDoubleClick` sind
  auskommentiert (`extiButtonLS.cpp:325–326`), registriert sind nur
  LongPressStart/During/Stop und MultiClick.
- **`attachMultiClick1()` entschärft eher, als dass es auslöst:** 3 Klicks im
  Standby → `esp_deep_sleep_start()`, 10 Klicks → „Exit Alarm", und der
  `default:`-Zweig — also *jede andere* Klickzahl — setzt ebenfalls
  `sys.alarm = 0` und fährt die IMU herunter.

Im Alarmzustand sendet er wiederholt (`send NO.%d Alarm data`, `alarm_state()`
in `TrackerD.ino:1807`), im Abstand `sys.atdc` — einstellbar per `AT+ATDC`
oder per Downlink (`TrackerD.ino:2627`).

### Erst speichern, dann filtern

Der Weg vom Uplink zum Rundruf ist seit 14.08.2026 in zwei Schritte geteilt,
und die Reihenfolge ist der Punkt:

```
  ChirpStack ──MQTT──▶ lora_log.py ──▶ wagodb.loradevice   (Geräteereignisse)
       Chat  ──MQTT──▶     "      ──▶ wagodb.lorachat     (Textebene)
                                            │
                                            ▼
                                       lora_bcast.py       (Filter)
                                            │
                                            ▼
                                        MQTT crisis ──▶ crisis_bcast.py ──▶ alle Geräte
```

**`dell/lora_log.py`** (`lora-log.service`) schreibt jedes Ereignis von
`application/#` nach `wagodb.loradevice` — up, join, ack, txack, status, log.
Was sich sinnvoll herausziehen lässt, steht in eigenen Spalten; der
vollständige Rahmen bleibt zusätzlich als JSON in `raw`. Schema:
`dell/loradevice.sql`.

Derselbe Dienst schreibt die **Textebene** nach `wagodb.lorachat`
(`dell/lorachat.sql`) — alles, was nicht `application/#` ist: der Rundruf auf
`crisis`, die Betriebsmeldungen auf `…/status` und das, was `dragino_rx.py`
aus einem hereingefunkten LoRa-Text zusammensetzt.

| richtung | woran erkannt |
|---|---|
| `raus` | Topic ist `crisis` |
| `status` | Topic endet auf `/status` |
| `rein` | alles übrige |

Die Erkennung geht bewusst über den Rest-Fall, nicht über eine Topic-Liste:
`dragino_rx.py` veröffentlicht unter dem Topic, das der Absender im Funkspruch
selbst gewählt hat — das steht nirgends vorher fest.

Zwei Tabellen statt einer, weil es zwei Dinge sind: `loradevice` sagt, was ein
Gerät gesendet hat (DevEUI, fPort, Zählerstand), `lorachat` sagt, was Menschen
einander mitgeteilt haben. In eine Tabelle gezwungen bliebe dauerhaft die
Hälfte der Spalten leer.

Ein Detail, das sonst still Doubletten erzeugt: aufbewahrte Nachrichten
(`retain`) liefert der Broker jedem neuen Abonnenten nach. Das ist ein Abbild
des Zustands, kein neues Ereignis — sonst stünde nach jedem Neustart des
Dienstes derselbe Satz noch einmal in der Tabelle. Sie werden übersprungen.

Die Gateway-Ebene (`eu868/#`) bleibt draußen: dieselben Uplinks noch einmal,
nur unentschlüsselt, dazu alle 30 s Statistik.

**`dell/lora_bcast.py`** (`lora-bcast.service`) liest aus `loradevice` und
entscheidet, was gesendet wird. Wer umgekehrt vorgeht — erst filtern, dann
speichern — kann eine Filterregel nie an vergangenen Daten prüfen. So dagegen
schon, ohne ein einziges Byte zu senden:

```
./lora_bcast.py --trocken --seit 0                        # auf dem dell
./lora_bcast.py --trocken --seit 0 --db-host 192.168.5.23 # von woanders
```

Beide Dienste sind für den dell gebaut, wo Broker und MariaDB lokal stehen —
die Vorgabe ist deshalb `127.0.0.1`. Von einem anderen Rechner aus zeigt man
mit `--db-host`/`--broker` bzw. `LORA_DB_HOST`/`LORA_BROKER` hin; ohne das
bricht `lora_bcast.py` mit einer Erklärung ab statt mit einem Traceback und
verweist für den Handbetrieb auf `laptop/crisis_client.py`.

Ein Detail, das zweimal falsch war, bevor es stimmte: ob auf die Datenbank
gewartet oder abgebrochen wird, entscheidet der ausdrückliche Schalter
`--warten` (den nur die systemd-Unit setzt) — **nicht** `isatty()`. In einer
Pipe oder unter `nohup` ist das Terminal weg, und dann hängt der Aufruf still
in einer Warteschleife, statt den Fehler zu zeigen.

Ein Detail im Schema, das leicht in die falsche Richtung geht: es gibt
**keinen** eindeutigen Schlüssel auf `(dev_eui, f_cnt)`. Der LA66 fängt nach
einem Neustart wieder bei 0 an; ein Unique würde die neuen Uplinks
stillschweigend verwerfen. In einem Rohspeicher ist eine Doublette das
kleinere Übel als eine Lücke.

### Was im Rundruf steht

Alarmknopf, GPS-Position, Empfangspegel. Sonst nichts.

```
TrackerD ALARM 47.67912,11.57934 -90dBm    39 Byte
TrackerD ALARM kein Fix -90dBm             30 Byte
TrackerD 47.67912,11.57934 -118dBm         34 Byte
kein Alarm, kein Fix                       → es geht nichts hinaus
```

Temperatur, Feuchte, Batterie und Bewegungszustand bleiben in der Datenbank.
Im Krisenfall zählt, wo jemand ist und ob er gedrückt hat; jedes weitere Byte
kostet Sendezeit bei **jedem** Empfänger. Aus demselben Grund bleibt der Text
unter 49 Byte — darüber stückelt `crisis_bcast`, und jedes Stück kostet bei
SF12 rund eine Sekunde pro Empfänger. Bei 1 % Duty Cycle ist das der
Unterschied zwischen "geht sofort raus" und "Gateway sendet stundenlang nach".

Der **RSSI** ist der des Uplinks am Gateway und steht mit im Text, damit die
Empfänger einschätzen können, wie belastbar die Meldung ist: −90 dBm ist
solide, jenseits von −115 dBm reißt die Verbindung gleich ab. Dann ist das
Ausbleiben der nächsten Meldung eine Funklücke — und keine Entwarnung.

Ohne Satellitenfix meldet der TrackerD `Latitude`/`Longitude` als `0.0`. Das
als Position weiterzugeben wäre schlimmer als gar keine, deshalb steht dann
ausdrücklich **kein Fix** im Text — aber nur, wenn ein Alarm anliegt. Ohne
beides geht gar nichts hinaus: eine Meldung "kein Fix, kein Alarm" bindet
Sendezeit, ohne etwas mitzuteilen.

**"kein Fix" heißt nicht "kein Positionsfeld".** Der TrackerD wechselt den
Port: liegt nur ein Alarm an, schickt er drei Byte auf **fPort 7** statt
fünfzehn auf fPort 2.

```
fPort 2   00000000000000004dc920016e0143   Position (0/0), Alarm, Feuchte, Temperatur
fPort 7   4dc420                           Alarm + Batterie, sonst nichts
```

In der fPort-7-Meldung steht überhaupt keine Position — das ist kein
fehlender Satellitenempfang und darf auch nicht so aussehen. Der Filter
schreibt "kein Fix" deshalb nur, wenn der Rahmen ein Positionsfeld führt und
es 0/0 ist; auf fPort 7 heißt es schlicht `TrackerD ALARM -106dBm`.

Nebenwirkung, bewusst so belassen: `crisis_bcast` reiht bei jedem Rundruf
*alle* Geräte ein, der TrackerD bekommt seine eigene Meldung also als Downlink
zurück. Harmlos, aber es kostet Sendezeit — wer das nicht will, filtert in
`crisis_bcast.all_devices()` auf die Anwendung `notfall`.

### Taugt ESPHome als Ersatzfirmware?

Für die Sensorik ja, für LoRaWAN nein. Geprüft gegen ESPHome 2026.2.4:

| Teil | ESPHome |
|---|---|
| ESP32-PICO-D4 | `esp32: board: pico32` |
| SX1276/78 | `sx127x` — **rohes LoRa**, kein LoRaWAN |
| GPS | `gps` (NMEA über UART) |
| GXHT3X | `sht3xd`, der Sensor ist SHT3x-kompatibel |
| BLE | `esp32_ble_tracker` |
| Batterie/Ladung | `adc` |
| LIS3DH | keine Komponente — externe Einbindung nötig |

Ausschlaggebend ist die zweite Zeile: `sx127x` kennt weder OTAA noch Join,
DevEUI oder AppKey (im Quelltext kommt keines dieser Wörter vor). Es überträgt
rohe LoRa-Pakete, wahlweise über `packet_transport`. Mit ESPHome wird aus dem
TrackerD also ein Punkt-zu-Punkt-Funkknoten wie die E22-Module, kein
LoRaWAN-Gerät — Gateway, ChirpStack und TTN fallen damit aus dem Pfad.

Wer es trotzdem versucht: **vorher den Flash sichern.** Ein ESPHome-Flash
überschreibt das NVS, und damit wäre der AppKey weg. Der Abzug vom 14.08.2026
liegt auf dem ESPHome-Pi als `/home/pi/trackerd_flash_4mb_2026-08-14.bin`
(md5 `df9e89a1dd6ff4de928389b3c16515c4`).

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
