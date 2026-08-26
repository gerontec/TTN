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
    cd fork148 && ~/.platformio/penv/bin/pio run

Ergebnis: `.pio/build/trackerd148/firmware.bin`. Geflasht wird vom Notebook
aus, wo das Geraet haengt:

    ./switch_app.py flash --bin firmware.bin     # app1, Bootpartition mit

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

## Stand des Geraets (26.08.2026)

| Slot | Inhalt |
|---|---|
| app0 | Draginos offizielles Release `v1.5.6/EU868.bin` — als Referenz, Knopf defekt |
| app1 | Werks-**v1.4.8** aus dem Vollbackup, bootet, `AT+INTWK=1`, `AT+MTDC=180000` |
