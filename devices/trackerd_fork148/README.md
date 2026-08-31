# TrackerD-Fork: Grundlage v1.4.8

Fork-Grundlage ist Draginos **v1.4.8**, nicht 1.5.x. Der Grund steht weiter
unten und ist an diesem Geraet am 26.08.2026 durchgemessen worden.

## Bauen

Build-Server ist **192.168.5.23** (PlatformIO 6.1.19). Das Notebook taugt
nicht als Referenz: dort sind die pico32-Pins global in den Framework-Dateien
gepatcht, und ein Fork kann eine Aenderung am System des Bauenden nicht
mitnehmen.

    ssh gh@192.168.5.23
    cd ~/trackerd_build
    git clone --branch v1.4.8 --depth 1 https://github.com/dragino/TrackerD.git repo148
    # Quelltext und Bibliothek in die Bauumgebung
    cp -a repo148/Example/LoRaWAN/examples/TrackerD/. fork148/src/
    cp -a repo148/Library/arduino-lmic/arduino-lmic fork148/lib/arduino-lmic
    # Aenderungen anwenden, Reihenfolge egal - jede prueft ihren Anker selbst
    for f in patches/fix_*.py; do python3 "$f" fork148/src; done
    python3 patches/fix_aes_len.py fork148/lib/arduino-lmic
    cd fork148 && ~/.platformio/penv/bin/pio run

Ergebnis: `.pio/build/trackerd148/firmware.bin`. Geflasht wird vom Notebook
aus, wo das Geraet haengt:

    ~/bin/esptool --port /dev/ttyACM0 --baud 921600 write_flash 0x10000 firmware.bin
    ./switch_app.py app0                    # Bootwahl auf app0

Seit 26.08.2026 (nachmittags) liegt der Fork in **app0**; die
Werksfirmware v1.4.8 wurde dort ersetzt.

## Zwei Dinge, ohne die es nicht baut

1. **Projekteigene Board-Variante.** Der TrackerD ist auf SCK 5 / MISO 19 /
   MOSI 27 / NSS 18 verdrahtet, die `pico32`-Vorgabe des Frameworks trifft das
   nicht. LMICs `hal_spi_init()` ruft `SPI.begin()` **ohne Argumente**, nimmt
   also die Pins der Variante; stimmen sie nicht, antwortet der SX1276 nicht,
   `radio_init()` scheitert und `os_init()` bleibt in `ASSERT(0)` stehen —
   sichtbar als

       FAILURE
       lib/arduino-lmic/src/lmic/oslmic.c:53
       Guru Meditation Error: Core 1 panic'ed (Interrupt wdt timeout on CPU1)

   Dragino loest das mit einem Patch an `variants/pico32/pins_arduino.h`, also
   an einer geteilten Framework-Datei. Hier steht die Variante stattdessen im
   Projekt:

       board_build.variants_dir = variants
       board_build.variant = trackerd

2. **Der LMIC-Pfad ist im 1.4.8-Repo eine Ebene tiefer** verschachtelt:
   `Library/arduino-lmic/arduino-lmic/`. Wer nur `Library/arduino-lmic`
   kopiert, bekommt `fatal error: lmic.h: No such file or directory`.

## Warum nicht 1.5.x

**Der Alarmknopf ist dort tot**, und das ist keine Vermutung: Draginos
offizielles Release-Image `v1.5.6/EU868.bin` wurde auf dieses Geraet geflasht
und zeigt den Fehler genauso.

    AT+DADDR=?
    260b63fe
    Static=260beb96        <- sys.cdevaddr = 638.562.198

`button_loop()` in `common.cpp` (1.5.x) waehlt die Hardwarevariante an der
**Groesse der DevAddr**: alles ueber 25.692.040 gilt als TrackerD-LS. Eine
TTN-Adresse aus `260B0000/16` sind 638 Millionen — die Entscheidung faellt
also immer falsch aus, getickt wird `button1` auf **GPIO 25 (GPS_RESET)**
statt der Alarmknopf auf **GPIO 0**. Der Knopf reagiert nicht mehr, und die
Scheinereignisse des GPS-Pins halten ueber `sleep_flag` den Schlaf auf —
womit auch die regulaeren Uplinks ausbleiben. Ein Fehler, zwei Symptome.

Ausgeloest wird es durch jeden Werksreset: `cdevaddr` wird beim Kaltstart aus
der aktuellen Sitzungsadresse neu gesetzt, und die kommt bei OTAA vom Netz.

**In v1.4.8 gibt es diese Konstruktion nicht.** Weder `button_loop()` noch
`device_strcmp()` noch eine `extiButtonLS.cpp` existieren dort;
`TrackerD.ino:1301` ruft `button_attach_loop()` direkt auf, mit genau einem
`OneButton button(BUTTON_PIN, ...)` auf GPIO 0. Die Variantenraterei kam mit
1.5.x.

## Fallstricke, die bleiben

* **Am USB-Kabel ist der Knopf nicht beurteilbar.** DTR haelt GPIO 0 unten,
  die Firmware sieht einen Dauerdruck: gruene LED an, `sleep_flag = 1`, kein
  Schlaf, keine Uplinks. Knopftests immer mit gezogenem Kabel.
* **Jeder Wechsel der Versionsnummer loescht die Einstellungen** (`DATA_CLEAR`
  + Neustart, Blau-Rot-Gruen). Zwischen app0 und app1 hin und her zu booten
  kostet also jedes Mal TDC, INTWK und alles andere.
* **Draginos Tags sind unzuverlaessig.** v1.4.6, v1.4.7 und v1.4.8 zeigen auf
  denselben Commit, und dessen `Pro_version` sagt `v1.4.6`. Das Werksimage auf
  dem Geraet meldet dagegen `v1.4.8`. Fuer den Fork gehoert ein eigener
  Versionsstring gesetzt, dann ist der `DATA_CLEAR` beim Wechsel vorhersehbar.
* Ebenso springen die Tags von v1.5.3 auf v1.5.5/v1.5.6 — ein **v1.5.4 gibt es
  nicht**.

## Stand des Geraets (31.08.2026, beide Slots ausgelesen)

| Slot | Inhalt | meldet |
|---|---|---|
| app0 | dieser Bau, **Bootpartition** | `TrackerD ,v1.4.8` |
| app1 | dasselbe Image als Rueckweg | `TrackerD ,v1.4.8` |

Beide Slots tragen dasselbe Bauwerk, also auch denselben Versionsstring — ein
Wechsel kostet damit keinen `DATA_CLEAR`. Welcher Slot laeuft, sagt das Feld
`app` im Konfigrahmen (fPort 9).

Nichts aus 1.5.x liegt mehr auf dem Geraet. Geprueft wurde nicht am
Versionsstring, sondern am Flash: `esptool read-flash 0x1F0000 0x1E0000` und
`0x10000`, danach der Image-Kopf und die Zeichenkette `TrackerD ,v`.

## Warum die Werksfirmware nichts rettet

Der Datalog ist vorhanden und funktioniert — er wird nur nie ausgeloest. Alles
haengt an `AT+PNACKMD=1`:

* Erst damit sendet der TrackerD **bestaetigte** Uplinks. Bleibt das ACK aus,
  schreibt `EV_TXCOMPLETE` den Rahmen ueber `gps_data_Weite()` ins NVS.
* Auf dem Geraet in Lenggries steht `PNACKMD` auf 0 — im Gateway-Log stehen
  ausschliesslich `UNCONF_UP`. Damit ist die Kette tot, jeder ungehoerte Fix
  ist verloren.

## Die Aenderung

**86 Zeilen in `TrackerD.ino`, zwei in `common.h`.** Kein neues Speicherformat,
kein neuer Port, keine neue Bibliothek — es wird ausschliesslich die vorhandene
Werksmechanik ausgeloest.

**Der Beleg.** Auch ein unbestaetigter Uplink verraet, ob ihn jemand gehoert
hat: `LMIC.txrxFlags & (TXRX_DNW1|TXRX_DNW2|TXRX_ACK)`. Wurde RX1 oder RX2
bedient, war das Netz da. Blieben beide leer, ist der Fix nirgends angekommen.

**Sichern.** Kein Empfangsfenster bedient und der Uplink war der Positionsrahmen
(fPort 2/3) mit echtem Fix — dann `sys.gps_data_Weite()`, also derselbe
4-KB-Bereich und dasselbe 15-Byte-Format wie beim Werksverfahren:
**240 Fixes, rund vier Stunden im Minutentakt.** Danach dreht der Ring und
ueberschreibt den aeltesten Teil.

**Nachliefern.** Kommt wieder ein Downlink an und liegt etwas im Puffer, setzt
der Zweig `sys.loggpsdata_send = 1` — ab da uebernimmt die Werksfirmware
unveraendert: ein Datensatz je Uplink auf **fPort 4**, und `setup()` verkuerzt
den Takt dabei selbst auf **10 s**. Vier Stunden Rueckstand sind so in rund
40 Minuten heraus. Bleibt ein Nachliefer-Uplink ungehoert, geht der Lesekopf
einen Datensatz zurueck und die Nachlieferung pausiert, bis das Netz wieder
antwortet.

**Verbindungsprobe.** Solange etwas im Puffer liegt, geht jeder zehnte Uplink
bestaetigt raus. Ohne das wuerde die Rueckkehr des Netzes nur auffallen,
solange der Krisen-Rundruf Downlinks schickt — das Nachliefern haenge dann an
einem fremden Dienst.

Der ganze Block laeuft nur bei `PNACKMD=0`. Wer das Werksverfahren einschaltet,
bekommt es unveraendert; die beiden kommen sich nie in die Quere.

Waehrend der Nachlieferung schaltet die Werksfirmware das GPS ab — in diesen
40 Minuten kommen also keine neuen Positionen dazu. Das ist Draginos Verhalten,
nicht unseres.

### Bekannte Grenze

Nach dem Ueberlauf (mehr als vier Stunden Funkloch) kommen die Datensaetze
nicht in zeitlicher Reihenfolge: der Ring beginnt vorne, die juengsten Fixes
stehen dann vor den aelteren. Jeder Datensatz traegt seine GPS-Zeit im Rumpf,
sortiert wird also serverseitig ueber `dev_time` — nie ueber `ts`.

## Der eine noetige Patch: Pad-Holds beim Start loesen

`patches/TrackerD.ino.patch` — vier Zeilen ganz am Anfang von `setup()`.

Ohne ihn bootet das selbstgebaute Image **genau einmal** und stuerzt danach bei
jedem Start ab:

    TrackerD ,v1.4.6
    FAILURE
    lib/arduino-lmic/src/lmic/oslmic.c:53
    Guru Meditation Error: Core 1 panic'ed (Interrupt wdt timeout on CPU1)

In dieser LMIC-Fassung kann `os_init_ex()` nur an einer Stelle scheitern: an
`radio_init()`, das die Versionskennung des SX1276 ueber SPI liest. Der Funk
antwortet also nicht mehr — und zwar, weil **MOSI abgeklemmt bleibt**.

Vor dem Deep Sleep isoliert die Firmware MOSI (`rtc_gpio_isolate(GPIO_NUM_27)`)
und haelt GPIO 12 (`gpio_hold_en` + `gpio_deep_sleep_hold_en`). Aufgeraeumt
wird das erst im Kaltstartzweig von `print_wakeup_reason()` — und der bricht
auf dem Werksreset-Weg vorher ab:

    if(sys.FDR_flag == 1) { sys.DATA_CLEAR(); ESP.restart(); }   // <- hier raus
    ...
    gpio_hold_dis((gpio_num_t)12);      // <- kommt nie dran
    gpio_deep_sleep_hold_dis();

Ein Software-Reset raeumt RTC-Pad-Holds nicht auf. Deshalb loest der Patch sie
ganz vorn in `setup()`, bevor irgendetwas den Bus benutzt:

    gpio_deep_sleep_hold_dis();
    gpio_hold_dis((gpio_num_t)12);
    rtc_gpio_hold_dis(GPIO_NUM_27);
    rtc_gpio_deinit(GPIO_NUM_27);

Warum das Werksbinary nicht betroffen ist, ist damit nicht geklaert — es
ueberlebt denselben Werksreset. Fuer den Fork zaehlt, dass die Ursache
verstanden und die Behandlung an der richtigen Stelle ist.

**Nachgewiesen am Geraet, 26.08.2026:** drei Neustarts hintereinander ohne
Absturz, Join auf TTN sensorsa, Statusrahmen `1301 46 01ff0fa240 03` —
`firm_ver 0x0146` (der Fork) und FLAG `03`, also `Intwk = 1`.


## Stand 26.08.2026 (nachmittags)

* **Alarmzyklus:** Der Timer-Wecker macht den Zaehlzweig je Aufwachen wieder
  scharf (`AT+ATDC`-Takt, ab Werk 60 s); `alarm_count` wird in `setup()` nur
  noch zurueckgesetzt, wenn kein Alarm laeuft - sonst waere Runde 60
  (Alarm-Ende) nie erreichbar und der Alarm liefe endlos.
* **GPS-Spurpuffer bei PNACKMD=0:** Blieben beide RX-Fenster leer, ist der
  Rahmen nirgends angekommen. Der Fix kommt dann in den 4-KB-Ring (Alarm und
  Bewegungsspur) und wird ueber fPort 4 nachgeliefert, sobald das Netz wieder
  antwortet. Verbindungsprobe: jeder zehnte Uplink geht bestaetigt raus.
* **Alarm-Ende** (Runde 60 oder Knopf): Liegt etwas im Puffer, startet die
  Nachlieferung der Alarmliste sofort.
* **Ab Werk** (nach Werksreset): Sport-Mode an (`AT+INTWK=1`, Beschleunigungs-
  sensor als Trigger), Positionstakt in Bewegung 180 s (`AT+MTDC=180000`).
* **Pad-Holds** (MOSI/GPS-Power) werden schon beim Start geloest, bevor LMIC
  das Funkmodul anspricht - sonst ASSERT(0)-Bootschleife nach Software-Reset.


## Spurpuffer-Kapazitaet

Der Ring fasst 4095 Byte / 15 Byte je Datensatz (sensor_type 13) =
**273 Records** (sensor_type 22: 17 Byte je Satz = 240 Records). Gefuellt
wird er nur mit Fixes, die niemand gehoert hat (beide RX-Fenster leer);
gehoerte Fixes gehen live raus. Dieselbe Flaeche dient Alarm und
Bewegungsspur.

* **Sport-Mode** (MTDC 180 s, ein Record je Zyklus): 273 x 3 min =
  819 min ≈ **13,7 h** — eine Fahrt im 3-Minuten-Takt kommt also rund
  12-14 h weit. Stop-and-Go mit zusaetzlichen Bewegungswickeln verkuerzt
  das entsprechend (bei 1 Fix/min waeren es nur ~4,5 h).
* **Alarm** (ATDC 60 s): 273 min ≈ **4,5 h**.

Nach dem Ueberlauf ringt der Speicher: der aelteste Fix wird ueberschrieben,
die juengsten stehen dann vorn. Sortierung serverseitig deshalb immer ueber
die GPS-Zeit im Datensatz (`FixTime`), nie ueber die Ankunftszeit (`ts`).

## Serverseite

* `TTN/devices/trackerd.js` (und die Kopie neben `cs_trackerd.py`): fPort 4
  liefert jetzt auch `Longitude` — das fehlte im Werks-Decoder ausgerechnet in
  dem Zweig, der die nachgelieferte Spur bringt — und `FixTime`, die GPS-Zeit
  des Fixes als sortierbares ISO-8601.
* `cs_trackerd.py` zieht den Decoder bei einem zweiten Lauf im vorhandenen
  ChirpStack-Profil nach.
* `lora_log.py` schreibt jeden nachgelieferten Fix zusaetzlich als eigene Zeile
  mit `event='up-log'` und `dev_time` = Zeit des Fixes.

## Weiter hier

* [ATcmdTrackerD.md](ATcmdTrackerD.md) — die AT-Befehle, gegen Quelltext und Geraet geprueft
* [DATALOG.md](DATALOG.md) — den Werks-Datalog einschalten
* [LEDS.md](LEDS.md) — was die drei LEDs bedeuten
* [attic-tracklog/](attic-tracklog/) — der erste Anlauf: eigener Ringpuffer im
  spiffs-Bereich (192 KB, 9792 Fixes), mit Testrahmen ohne Geraet. Funktioniert,
  war fuer die Aufgabe aber zu gross.
