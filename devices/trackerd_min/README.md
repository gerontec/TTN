# TrackerD: minimaler Fork auf Draginos Werksstand

Grundlage ist Draginos Tag **v1.4.8** (`repo148`; der Quelltext dort meldet
sich als `v1.4.6`, weil v1.4.6/v1.4.7/v1.4.8/V1.4.9 auf denselben Commit
`a66935b` zeigen und der Versionsstring nie nachgezogen wurde).

**Der Grundsatz dieses Verzeichnisses: so nah am Werksstand wie moeglich.**
Enthalten ist ausschliesslich, was in `patches/` steht. Alles andere ist
unveraendert Dragino.

Der Vorgaenger [../trackerd_fork148/](../trackerd_fork148/) hatte deutlich mehr
geaendert, darunter den Alarmzyklus. Am 31.08.2026 zeigte sich am Geraet: die
Werksfirmware behandelte den Alarmknopf richtig, der Fork nicht -- bei
unveraendertem EEPROM, also lag es am Code. Bei einem Geraet, das im Ernstfall
funktionieren muss, faellt so etwas erst auf, wenn es zaehlt. Deshalb hier ein
neuer Anfang mit einer kurzen, begruendeten Liste.

## Was drin ist

| Patch | wirkt auf | warum |
|---|---|---|
| `fix_holds.py` | `src/TrackerD.ino` | **Bauvoraussetzung, keine Funktion.** Ohne dieses Loesen der RTC-Pad-Holds bootet ein selbstgebautes Image genau einmal und haengt danach in `ASSERT(0)`, `oslmic.c:53`. |
| `fix_defaults_on.py` | `src/TrackerD.ino` | Sport-Mode (`AT+INTWK=1`) und Datalog (`AT+PNACKMD=1`) ab Werk an; Ringzeiger genullt. |
| `fix_alarm_autostop.py` | `src/TrackerD.ino` | Der Alarm endet von selbst, wenn er nichts Neues mehr meldet. |
| `fix_aes_len.py` | `lib/arduino-lmic` | **Bibliotheksfehler.** `os_aes()` prueft die Restlaenge in 8 statt 16 Bit; Rahmen ab 128 Byte gingen unverschluesselt und ohne gueltigen MIC hinaus. Gemeldet als [mcci-catena/arduino-lmic#1071](https://github.com/mcci-catena/arduino-lmic/issues/1071), Korrektur als [#1072](https://github.com/mcci-catena/arduino-lmic/pull/1072). |

Jedes Skript prueft seinen Anker selbst und bricht ab, statt daneben zu
patchen. Die ausfuehrliche Begruendung steht jeweils im Docstring.

## Das Alarm-Selbstende

Draginos Alarm endet **nie** von allein: `sys.alarm_count` wird in `setup()`
bei jedem Aufwachen genullt und erreicht die 60 nicht, gegen die `sys_sleep()`
prueft. Der einzige Ausstieg sind zehn schnelle Klicks. Am 31.08.2026 lief ein
versehentlich ausgeloester Alarm ueber eine Stunde und erzeugte 338 Uplinks.

Zwei Abbruchgruende, beide heissen "es gibt nichts Neues zu melden":

* **mehr als drei Positionsrahmen hintereinander ohne Fix**
* **dreimal hintereinander derselbe Ort** -- naeher als **40 m** zum vorigen Fix

Ein Fix, der weiter entfernt liegt, setzt beide Zaehler zurueck; die Bedingung
verlangt ununterbrochene Folgen. Verglichen wird gegen den letzten Fix, nicht
gegen den ersten, damit langsames Driften nicht als Stillstand durchgeht.

40 m sind nicht willkuerlich: ein still liegendes Geraet streute an diesem Tag
ueber die Alarmrahmen hinweg rund 22 m in der Breite und 45 m in der Laenge.
Auf Gleichheit zu pruefen hiesse, nie abzubrechen -- ein Einheitsschritt sind
1e-6 Grad, also gut 11 cm.

Beendet wird mit genau denselben Zuweisungen wie beim Zehnfach-Klick: es gibt
nur einen Ausstiegsweg im Verhalten, zwei Ausloeser dafuer. Der ausloesende
Rahmen geht noch mit gesetztem Alarmbit hinaus; erst der naechste zeigt
`ALARM=0`.

## Stand des Geraets (31.08.2026)

| Slot | Inhalt | meldet |
|---|---|---|
| app0 | Draginos Werksimage aus dem 4-MB-Vollbackup vom 15.08. | `v1.4.8` |
| app1 | dieser Bau, **Bootpartition** | `v1.4.6` |

Die Versionsstrings unterscheiden sich absichtlich: ein Wechsel zwischen den
Slots loest damit `DATA_CLEAR` aus, und der Bau hier setzt seine Vorgaben
(INTWK, PNACKMD) genau dort. Der Rueckweg auf den reinen Werksstand ist
`../trackerd_p2p/switch_app.py app0` -- danach sind Sport-Mode und Datalog
wieder aus, denn Draginos Vorgaben sind `Intwk = 0` und `PNACKmd = 0`.

Nachgeprueft am Geraet: Statusrahmen `13014601ff0fa24007` -- Byte 8 = 0x07,
also INTWK, LON und PNACKMD gesetzt -- und jeder Uplink kommt mit
`confirmed = 1` an, was `PNACKMD=1` bewirkt.

## Decoder

`../trackerd.js` passt zu diesem Stand: kein Zweig fuer fPort 9 mehr (den
Konfigrahmen sendet diese Firmware nicht), aber weiterhin die Korrekturen an
fPort 4 (`Longitude` und `FixTime` fehlten im Werks-Decoder) und an `PNACKMD`
(zugewiesen wurde `panackmd`, ausgegeben `pnackmd`).
