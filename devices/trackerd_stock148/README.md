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
| `fix_defaults_on.py` | `src/TrackerD.ino` | Sport-Mode (`AT+INTWK=1`) und Datalog (`AT+PNACKMD=1`) ab Werk an, statt Draginos `0`/`0`. `frame_flag` wird mitgesetzt, weil `PNACKmd` ohne bestaetigte Uplinks wirkungslos bleibt. Greift im `FDR_flag == 0`-Zweig, also nach `DATA_CLEAR` -- Werksreset oder Wechsel des Versionsstrings. |
| `fix_alarm_gpsfix_stop.py` | `src/TrackerD.ino` | Ein Alarm endet nach 99 **gueltigen Positionen** -- Rahmen mit `Latitude=0` und die Unterspannungsmarke `-1` zaehlen nicht mit. Zaehler in `RTC_DATA_ATTR`, also nur im Speicher; `sys.alarm_count` bleibt unbenutzt, der ginge ins NVRAM. Beendet wird mit denselben Zuweisungen wie der Zehnfach-Klick. |
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
