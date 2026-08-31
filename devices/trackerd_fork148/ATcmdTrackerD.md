# TrackerD: die AT-Befehle

Vollstaendige Liste der seriellen Befehle des Dragino TrackerD, geprueft gegen
den Quelltext (`src/at.h`, `src/at.cpp`) und gegen das Geraet in Lenggries
(DevEUI `a840414f1188076c`).

Stand 31.08.2026, beide Slots am Geraet gelesen:

| Slot | Firmware | meldet | Befehle |
|---|---|---|---|
| app0 | aelterer Fork-Bau | `TrackerD ,v1.4.6` | 41 |
| app1 | Fork mit Konfigrahmen und empfindlicherem Sensor, Bootpartition | `TrackerD ,v1.4.8` | 41 |

Beide stehen auf **derselben Basis**: Draginos Tag `v1.4.8`. Dass der aeltere
Bau sich als 1.4.6 meldet, ist Draginos Unordnung — die Tags v1.4.6, v1.4.7,
v1.4.8 und V1.4.9 zeigen alle auf denselben Commit (`a66935b`), und dessen
`Pro_version` ist bei `v1.4.6` stehen geblieben. Der neue Bau setzt den String
auf die Nummer, mit der die Basis geholt wird.

**Der Preis:** `fire_version` ist damit 148 statt 146, und weil die Firmware
diesen Wert beim Kaltstart mit dem EEPROM vergleicht, kostet jeder Wechsel
zwischen den Slots einen `DATA_CLEAR()` — Einstellungen zurueck auf die
einkompilierten Vorgaben, Schluessel bleiben. Welcher Slot laeuft, sagt
ohnehin nicht die Version, sondern das Feld `app` im Konfigrahmen (fPort 9).

`AT+DEVICE`, `AT+PDTA` und `AT+BTDC` gibt es hier **nicht** — sie kamen erst mit
1.5.x, und 1.5.x gehoert nicht auf diese Hardware (Alarmknopf tot, siehe
[README.md](README.md), Abschnitt "Warum nicht 1.5.x"). Wer sie eintippt,
bekommt `ERROR`; das ist kein Tippfehler, sondern die fehlende Tabellenzeile.

## Anschluss

USB-CDC, **115200 8N1**, Zeilenende `\r\n`. Zwei Dinge, die jede Sitzung kosten:

* **DTR muss unten bleiben.** Das Signal haengt am Alarmknopf; ein Terminal, das
  DTR setzt, haelt ihn gedrueckt (gruene LED dauerhaft an, keine Uplinks).
  Zuruecksetzen geht ueber RTS, nie ueber DTR.
* **Jedes Oeffnen der Konsole ist ein Power-on-Reset.** Der RTC-Speicher ist
  damit weg, `RTC_LMIC.seqnoUp = 0`, das Geraet macht ein neues OTAA-Join und
  faellt kurz in den Sekundentakt. Wer nur nachsehen will, zahlt trotzdem den
  vollen Preis.

Nach einem Aufwachen per Taste bleibt das Geraet `AT+ATST` Sekunden wach
(Vorgabe 15), erst dann schlaeft es wieder ein. Innerhalb dieses Fensters
nimmt es Befehle an.

## Form der Befehle

| Form | Bedeutung |
|---|---|
| `AT` | Lebenszeichen, antwortet `OK` |
| `AT?` | Hilfeliste aller Befehle |
| `AT+CMD=?` | Wert lesen |
| `AT+CMD?` | Hilfezeile zu diesem Befehl |
| `AT+CMD=<wert>` | Wert setzen |
| `AT+CMD` | Befehl ausfuehren (nur bei `ATZ`, `AT+FDR`, `AT+SLEEP`, `AT+CFG`) |

Geantwortet wird mit dem Wert, dann einer Leerzeile, dann einem der Woerter
`OK`, `ERROR`, `AT_PARAM_ERROR`, `AT_BUSY_ERROR`, `AT_TEST_PARAM_OVERFLOW`,
`AT_RX_ERROR`. `ERROR` heisst "Befehl unbekannt", `AT_PARAM_ERROR` heisst
"Befehl bekannt, Wert unzulaessig".

**Jeder erfolgreiche `=`-Befehl schreibt die gesamte Konfiguration ins EEPROM**
(`ATInsPro()` ruft `config_Write()`). Einstellungen ueberleben also Neustart
und Stromausfall — bis auf die vier Wege unter "Fallen".

## Geraet und Sitzung

| Befehl | Wert | Wirkung |
|---|---|---|
| `AT+MODEL` | lesen | `TrackerD ,v1.4.6` |
| `ATZ` | ausfuehren | Konfiguration sichern, dann Neustart |
| `AT+FDR` | ausfuehren | **Werksreset**: `DATA_CLEAR()` + Neustart, alle Einstellungen weg |
| `AT+SLEEP` | ausfuehren | sofort in den Deep Sleep |
| `AT+CFG` | ausfuehren | alle Einstellungen als `AT+X=Y`-Zeilen ausgeben |

## LoRaWAN-Identitaet und Funk

| Befehl | Wert | Wirkung |
|---|---|---|
| `AT+DEUI` | 8 Byte hex | DevEUI |
| `AT+APPEUI` | 8 Byte hex | JoinEUI/AppEUI |
| `AT+APPKEY` | 16 Byte hex | AppKey (wird im Klartext zurueckgelesen) |
| `AT+DADDR` | 4 Byte hex | DevAddr fuer ABP |
| `AT+NWKSKEY` | 16 Byte hex | NwkSKey fuer ABP |
| `AT+APPSKEY` | 16 Byte hex | AppSKey fuer ABP |
| `AT+NJM` | `0` ABP / `1` OTAA | wirkt erst nach `ATZ` |
| `AT+ADR` | `0` / `1` | Adaptive Data Rate. Intern invertiert gespeichert — wer das EEPROM liest, sieht den Gegenwert |
| `AT+DR` | `0`..`7` | Datenrate, genau eine Ziffer, wirkt erst nach `ATZ` |
| `AT+TXP` | `0`..`5` | Sendeleistung, 0 = maximal |
| `AT+CHS` | `0`..`88` | Einzelkanal-Betrieb, wirkt erst nach `ATZ` |
| `AT+CHE` | `0`..`9` | Subband (US915/AU915), wirkt erst nach `ATZ` |
| `AT+DWELLT` | `0` / `1` | Uplink Dwell Time (AS923/AU915) |
| `AT+CFM` | `0`..`2` | bestaetigte Uplinks |

## Takte

| Befehl | Einheit | Wirkung |
|---|---|---|
| `AT+TDC` | ms, min 60 | Sendetakt in Ruhe. Bei uns 1200000 (20 min) |
| `AT+MTDC` | ms, min 60 | Sendetakt in Bewegung. Bei uns 180000 (3 min) |
| `AT+ATDC` | ms | Sendetakt im Alarmzustand. 60000 |
| `AT+ATST` | s, min 15 | wie lange das Geraet nach dem Aufwachen wach bleibt |

`AT+TDC` setzt auch `sys_time`, den Wert, aus dem `setup()` den Takt bei jedem
Start neu nimmt. `AT+MTDC` gilt nur, wenn `AT+INTWK=1` ist.

## Betriebsart, Bewegung, Alarm

| Befehl | Wert | Wirkung |
|---|---|---|
| `AT+SMOD` | `a,b,c` (genau 5 Zeichen) | a = Arbeitsmodus (1 = GPS, 2 = BLE, 3 = gemischt), b = Rahmenvariante, c = BLE-Modus. Bei uns `1,0,0` |
| `AT+INTWK` | `0` / `1` | Bewegungsmodus. 1 = der LIS3DH weckt das Geraet, danach gilt `MTDC` |
| `AT+PM` | `0` / `1` | Schrittzaehler |
| `AT+FD` | `0` / `1` | Sturzerkennung. **`FD=1` setzt `INTWK` auf 0** — beides zusammen geht nicht |
| `AT+PT` | 2 Hex-Ziffern | Ansprechschwelle des Beschleunigungssensors. Vorgabe hier `0A` = 10 LSB x 16 mg = 160 mg, damit Gehen mit 4 km/h weckt; Dragino liefert `14` (320 mg) |
| `AT+EAT` | ms | Dauer des langen Tastendrucks zum Verlassen des Alarms |
| `AT+BEEP` | `0` / `1` | Summer |
| `AT+LON` | `0` / `1` | LED-Blitz beim Senden |
| `AT+SHOWID` | `0`..`2` | zusaetzliche Ausgaben auf der Konsole |

## GPS

| Befehl | Wert | Wirkung |
|---|---|---|
| `AT+GF` | `0`..`2` | GPS ein/aus |
| `AT+FTIME` | s | maximale Suchzeit je Zyklus (intern ×1000). Bei uns 180 |
| `AT+PDOP` | Zahl | Guetegrenze. **Wird mit `atoi()` gelesen** — `7.5` wird zu 7 |
| `AT+BG` | `0` / `1` | GPS-Zeit mit in den Positionsrahmen |
| `AT+NMEA353` | `0`..`4` | Suchmodus, nur bei GPS-Chipversion 1, sonst `AT_PARAM_ERROR` |
| `AT+NMEA886` | Zahl | Frequenzmodus des GPS-Empfaengers |

## Spur im NVS

| Befehl | Wert | Wirkung |
|---|---|---|
| `AT+PNACKMD` | `0`..`2` | Werks-Datalog. `1` sichert ungehoerte Fixes **und setzt `CFM=1`**, also bestaetigte Uplinks mit bis zu acht Versuchen je Rahmen |

Ein Datensatz: `lat` int32 (Grad ×10^6), `lon` int32, `jahr` uint16, dann
Monat, Tag, Stunde, Minute, Sekunde als je ein Byte — dasselbe Format, in dem
fPort 4 die nachgelieferte Spur bringt:

    02 d7 8a 84 00 b0 b0 5f 07 ea 08 18 09 28 18
    -> 47.616132 / 11.579487, 24.08.2026 09:40:24

Einen Befehl, der den Ring ausliest, gibt es hier nicht: `AT+PDTA` kam erst mit
1.5.x. Was drin liegt, zeigt der Zaehler `datalog count:` beim Start.

## BLE und WiFi

`AT+BLEMASK=<hex>` und `AT+WiFiMASK=<hex>` filtern, welche Beacons bzw. APs
gemeldet werden; leer heisst "alles". Beide sind bei uns leer.

## Was es nicht gibt

**Keinen Befehl fuer den Fuellstand der Spur.** Die Zeiger `addr_gps_write` und
`addr_gps_read` haben keinen Get-Handler. Der Bewegungs-Stand gibt den Stand
deshalb bei jedem Start auf der Konsole aus:

    datalog count:0
    INTWK:1 MTDC:180000

Im Werksstand v1.4.8 fehlt selbst diese Zeile; dort bleibt nur das Zaehlen der
`up-log`-Zeilen in `wagodb.loradevice`.

## Dieselben Einstellungen als Downlink

Geprueft in `LORA_RxData()`. Hex, auf jedem Port ausser 0:

| Downlink | entspricht |
|---|---|
| `01 xx xx xx` | `AT+TDC` (Sekunden) |
| `03 xx xx xx` | `AT+MTDC` (Sekunden) |
| `04 FF` | `ATZ` |
| `04 FE` | `AT+FDR` — **loescht alle Einstellungen** |
| `05 00` / `05 01` | `AT+CFM` |
| `20 00` / `20 01` | `AT+NJM` |
| `22 01` | `AT+ADR=1` |
| `23 01` | **Geraetestatus anfordern** — loest den Rahmen auf fPort 5 aus (`gps_start = 1` → `device_send()`), nicht etwa eine Positionsmeldung |
| `24 xx` | `AT+CHE` |
| `25 xx` | `AT+DWELLT` |
| `34 xx` | `AT+PNACKMD` |
| `A5 …` | `AT+SMOD` |
| `AA xx xx` | `AT+FTIME` |
| `AD xx xx` | `AT+PDOP` (Wert ×10) |
| `AE xx` | `AT+LON` |
| `AF xx` | `AT+INTWK` |
| `B1 xx xx xx` | `AT+ATDC` |
| `B2 …` / `B3 …` | `AT+BLEMASK` / `AT+WiFiMASK` |
| `B4 xx` | `AT+PT` |
| `B5 xx` | `AT+ATST` |
| `B6 xx` | `AT+PM` |
| `B7 xx` | `AT+FD` |
| `B8 xx` | `AT+BG` |
| `B9 xx` | `AT+BEEP` |
| `BA xx` | `AT+EAT` (Sekunden) |

Die `//---->`-Kommentare im Quelltext stimmen in diesem Block stellenweise
nicht; die Tabelle oben folgt den tatsaechlichen Zuweisungen.

## Fallen

1. **Vier Wege setzen alles zurueck:** ein Versionswechsel beim Booten
   (`fire_version_write != fire_version` → `DATA_CLEAR()` + Neustart, erkennbar
   an Blau-Rot-Gruen), `AT+FDR`, der Downlink `04FE` und — nur fuer diesen einen
   Wert — der Downlink `34 00`.
2. **Ein ueberlebendes `AT+TDC=1200000` beweist nichts.** 20 min ist zugleich
   der Compile-Default; nach einem Werksreset steht derselbe Wert da.
3. **Der GPS-Ring ueberlebt `DATA_CLEAR`**, er liegt in `eeprom2`. Nur die
   Zeiger in `eeprom0` werden genullt: `AT+PDTA` zeigt dann alte Fixes, waehrend
   `datalog count` bei 0 steht. Diese Altbestaende werden nie gesendet.
4. **`AT+PNACKMD=1` kostet Sendezeit.** Es schaltet auf bestaetigte Uplinks um
   und laesst jeden ungehoerten Rahmen bis zu achtmal wiederholen. Der
   Bewegungs-Stand in app1 braucht das nicht — er erkennt an den leeren
   Empfangsfenstern, dass niemand zugehoert hat, und laeuft deshalb mit
   `PNACKMD=0`.
