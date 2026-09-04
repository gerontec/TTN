# TrackerD: sauberer Fork auf Draginos Werksstand v1.4.8

Grundlage ist Draginos Tag **v1.4.8** (`repo148`; der Quelltext dort meldet
sich als `v1.4.6`, weil v1.4.6/v1.4.7/v1.4.8/V1.4.9 auf denselben Commit
`a66935b` zeigen und der Versionsstring nie nachgezogen wurde).

**Werksverhalten bis auf zwei Vorgaben:** Sport-Mode und Datalog sind ab Werk
an. Dazu zwei Patches, die keine Funktion aendern, sondern Fehler beheben -- die
Pad-Holds beim Start und die Restlaengenpruefung in arduino-lmic.

Dazu ein Alarm-Selbstende nach 99 gueltigen Positionen.

`fix_gps_after_motion.py` gegen die im Bewegungstakt uebersprungene GPS-Suche
war zeitweise drin und ist wieder entfernt; ein frueheres Selbstende zaehlte
Uplinks statt Positionen und ist durch die jetzige Fassung ersetzt.

## Warum Positionen und nicht Uplinks

Am 31.08.2026 gingen 26 Alarmrahmen hintereinander mit `Latitude=0` hinaus, im
Takt von 246 s. Das ist `ATDC` (60 s) plus `FTIME` (180 s): die Suche lief
jedes Mal in den Zeitablauf, statt uebersprungen zu werden. Ein Uplink-Zaehler
haette den Alarm nach 99 solchen Fehlversuchen beendet, ohne dass je eine
Position uebermittelt worden waere.

Der Preis ist die Kehrseite davon und bewusst in Kauf genommen: ohne Empfang
endet der Alarm nie von selbst, dann helfen nur die zehn Klicks.

## Warum so streng

Die Vorgaengerforks hatten mehr geaendert, und am 31.08.2026 kam heraus, was
das kostet. Die Werksfirmware lieferte im 20-Minuten-Takt Positionen, der
Eigenbau nicht: dort hatte nur der erste Rahmen nach jedem Neustart einen Fix,
alle weiteren kamen mit `Latitude=0`. Fuenf Tage lang, vom 27.08. bis zum
31.08., stand in der Datenbank kein einziger brauchbarer Zyklus-Fix -- 0 von
64, 0 von 108, 0 von 104. Nach dem Rueckschalten auf die Werksfirmware in app0
lief es sofort wieder (16:14:44, 16:35:01, 16:55:16 -- exakt im TDC-Raster).

Ein Geraet, dem man im Ernstfall vertrauen koennen muss, darf solche
Ueberraschungen nicht tragen. Deshalb hier ein Anfang, dem man ansieht, was er
tut.

## Was drin ist

| Patch | wirkt auf | warum |
|---|---|---|
| `fix_holds.py` | `src/TrackerD.ino` | **Bauvoraussetzung, keine Funktion.** Loest `gpio_hold`/`rtc_gpio_hold` ganz vorn in `setup()`, vor `os_init()`. Der Werksstand loest sie erst im Kaltstartzweig -- den der `DATA_CLEAR`-Weg mit `ESP.restart()` vorher verlaesst. MOSI (GPIO 27) bleibt dann abgeklemmt, `radio_init()` sieht den SX1276 nicht, `os_init()` endet in `ASSERT(0)`, `oslmic.c:53`. |
| `fix_defaults_on.py` | `src/TrackerD.ino` | Datalog (`AT+PNACKMD=1`) ab Werk an; Sport (`AT+INTWK`) bleibt ausdruecklich auf 0. Beides zusammen lieferte in diesem Bau keine Positionen mehr -- Sport allein 340 Rahmen mit 100 % Fixquote, Datalog allein 96 %, zusammen 2 %. `frame_flag` wird mitgesetzt, weil `PNACKmd` ohne bestaetigte Uplinks wirkungslos bleibt. Greift im `FDR_flag == 0`-Zweig, also nach `DATA_CLEAR` -- Werksreset oder Wechsel des Versionsstrings. |
| `fix_alarm_gpsfix_stop.py` | `src/TrackerD.ino` | Ein Alarm endet nach 99 **gueltigen Positionen** -- Rahmen mit `Latitude=0` und die Unterspannungsmarke `-1` zaehlen nicht mit. Zaehler in `RTC_DATA_ATTR`, also nur im Speicher; `sys.alarm_count` bleibt unbenutzt, der ginge ins NVRAM. Beendet wird mit denselben Zuweisungen wie der Zehnfach-Klick. |
| `fix_datalog_sensitive.py` | `src/TrackerD.ino` | Datalog empfindlicher: der `TXRX_NACK`-Zweig **loescht** ab Werk den ganzen Spurpuffer, wenn `0 < addr_gps_write < 14` -- also im Zustand zwischen zwei Datensaetzen. Bleibt nur noch das Anhaengen. Dazu wird auch bei `EV_JOIN_FAILED` und `EV_REJOIN_FAILED` gepuffert: ohne Join wird nie ein ACK erwartet, der ausbleiben koennte, und der Werks-Datalog laesst die Position fallen. |
| `fix_aes_len.py` | `lib/arduino-lmic` | **Bibliotheksfehler, keine Verhaltensaenderung.** `os_aes()` prueft die Restlaenge in 8 statt 16 Bit; Rahmen ab 128 Byte gingen unverschluesselt und ohne gueltigen MIC ueber die Luft. Betrifft jede mitgelieferte Kopie der Bibliothek, auch Draginos. Gemeldet als [mcci-catena/arduino-lmic#1071](https://github.com/mcci-catena/arduino-lmic/issues/1071), Korrektur als [#1072](https://github.com/mcci-catena/arduino-lmic/pull/1072). Solange die nicht drin ist, bleibt der Patch hier. |

Jedes Skript prueft seinen Anker selbst und bricht ab, statt daneben zu
patchen. Die ausfuehrliche Begruendung steht jeweils im Docstring.

Warum die Vorgaben nicht per AT-Befehl gesetzt werden: `DATA_CLEAR` stellt sie
bei jedem Wechsel des Versionsstrings auf Draginos Werte zurueck. Am
31.08.2026 nachgemessen -- um 14:49 meldete der Statusrahmen `FLAG 0x07`
(beides an), nach dem Partitionswechsel um 14:50 `0x02` (beides aus). Was im
Quelltext steht, ueberlebt das; was in der Konsole gesetzt wurde, nicht.

## Der leere Spurpuffer fehlt

`fix_defaults_on.py` nullt die Ringzeiger des Spurpuffers **nicht** -- bestellt
waren nur die zwei Vorgaben. Die Folge ist gemessen: schaltet man den Datalog
ein, waehrend im Ring Reste eines anderen Firmwarestandes liegen, gehen sie als
Nachlieferung hinaus. Am 31.08.2026 waren das 22 Rahmen auf fPort 4 mit
Breitengrad -1360, Monat 215 und Jahr 55177; im GPX-Report ergab der Tagestrack
daraufhin eine Ausdehnung von 19.601 km. Bestaetigt gesendet, also mit bis zu
acht Versuchen je Rahmen. Die drei Zeilen dagegen stehen im Docstring des
Patches.

## Warum die Positionen fehlten: der Arduino-Core

Vom 27.08. bis zum 04.09.2026 lieferte jeder Eigenbau nur im ersten Suchlauf
nach einem Neustart eine Position und danach keine mehr -- im Alarmtakt
0 Positionen aus 39 Zyklen, waehrend die Werksfirmware am selben Platz jeden
Zyklus traf. Sechs Erklaerungsversuche waren falsch: floatende Pads im Schlaf,
ein doppeltes `SerialGPS.begin()`, von `AT+FDR` genullte `PDOP`/`FTIME`, der
`$GPGSA`-Talker, ein ueber den Schlaf durchlaufendes GNSS-Modul und der
Juni-2024-Quelltext als Grundlage.

Gemessen wurde es am 04.09.2026 an der seriellen Konsole, Port einmal geoeffnet,
`AT+SHOWID=1`, gleiche Hardware, gleicher Platz, wenige Minuten auseinander:

| Bau | NMEA nach `Start searching for GPS...` |
|---|---|
| app0 (Werk) | nach **2 s**, dutzende Saetze, `Fix Status` 0 -> 1 |
| Fork mit arduino-esp32 **2.0.14** | in **180 s keine einzige Zeile** |
| Fork mit arduino-esp32 **2.0.3** | nach **1 s**, wie app0; Fix nach 113 s |

**Der Fehler liegt im Bau, nicht im Quelltext.** Der GPS-UART haengt auf
GPIO 9/10 -- beim ESP32-PICO-D4 sind das SD_DATA_2/3, also Flash-Pads, in der
DIO-Betriebsart frei. Mit arduino-esp32 2.0.14 geht `HardwareSerial` ueber den
IDF-UART-Treiber (im Image stehen `uart_context`, `uart_event_task`,
`uart_set_rx_full_threshold`, `uart_set_rx_timeout`) und empfaengt auf diesen
Pins nichts. Draginos app0 traegt als einziges UART-Symbol
`uart_enable_intr_mask`, spricht den UART also direkt an.

Deshalb steht in `platformio.ini` `espressif32@4.4.0` (arduino-esp32 2.0.3):
der aelteste Core, der `EEPROMClass("eeprom0")` kennt -- 2.0.2 uebersetzt den
Quelltext nicht -- und der `uart_set_rx_timeout`/`setRxFIFOFull` noch nicht
benutzt; die kamen mit 2.0.5.

Auch die Binaergroesse passt: 1.383.808 Byte mit 2.0.3 gegen 1.603.504 mit
2.0.14, bei app0 sind es 1.347.584.

## Was app0 ist -- und wo es nicht liegt

Draginos ausgeliefertes app0 ist **nicht** der veroeffentlichte Quelltext, und
es gibt ihn nirgends:

| | `AT+CHS` / `AT+GF` | `AT+DEVICE` |
|---|---|---|
| a66935bc7 (03.08.2023, Tags v1.4.6-V1.4.9) | -- | -- |
| **app0 (Werk, meldet v1.4.8)** | **ja** | **nein** |
| 496b91718 (18.06.2024, Tags V1.5.0/v1.5.1) | ja | **ja** |

`AT+DEVICE` kam mit der Verschmelzung von TrackerD und TrackerD-LS. app0 liegt
also **zwischen** den beiden veroeffentlichten Commits. Draginos Tags helfen
nicht weiter: `v1.4.6`, `v1.4.7`, `v1.4.8` und `V1.4.9` zeigen alle auf
dasselbe Commit von 2023, und das Commit mit dem Text "v1.4.9" liegt als
`V1.5.0` da. Der Download-Server (`dragino.com/downloads/`) fuehrt gar keinen
TrackerD-Ordner.

Der Juni-2024-Stand ist als Grundlage unbrauchbar: er traegt die LS-Ver-
schmelzung, und auf dieser Hardware sind damit Alarmknopf und LEDs tot --
`button_event_init()` ist dort auskommentiert (`TrackerD.ino:1211`), und die
Knopfwahl haengt an `sys.cdevaddr` statt am Geraetetyp.

## Warum `fix_holds.py` dazugehoert

Ein Bau ohne diesen Patch wurde am 31.08.2026 geflasht und vermessen: das
Geraet startete, joint, sendete den Statusrahmen auf fPort 5 -- und begann von
vorn. In 40 Minuten kamen zwei Uplinks, beide fPort 5 mit `FCnt None`, also
reine Join-Folgen; **keine einzige Position**, obwohl bei TDC 20 min zwei
faellig gewesen waeren. Die serielle Mitschrift zeigte ohne aeusseren Reset ein
frisches `rst:0x1 (POWERON_RESET)` mit `Wakeup was not caused by deep sleep`.
Jeder dieser Kaltstarts spielt die Boot-LED-Folge Blau-Rot-Gruen ab, was am
Geraet wie ein Ampel-Zyklus aussieht.

Der Patch aendert kein Verhalten, er stellt nur her, was der Werksstand auf
dem `DATA_CLEAR`-Weg ueberspringt.

## Bauen

Der Werkzeugpfad steht im Kopf von `platformio.ini`. Draginos Quelltext liegt
**ohne Lizenzangabe** auf GitHub -- lesbar, aber nicht weitergabefrei. Deshalb
steht hier nur die Aenderung, nie eine Kopie.
