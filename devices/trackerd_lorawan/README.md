# TrackerD: GPS-Spur ueberlebt das Funkloch

Am 23.08.2026 lag zwischen 09:27 und 18:05 nichts vom TrackerD in der
Datenbank — 8 h 38 min ohne einen einzigen Uplink, und danach war die Fahrt
nicht etwa nachgeliefert, sondern weg.

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

## Bauen und flashen

Der Sketch ist 2.x-Code; mit dem aktuellen Core 3.x uebersetzt er nicht.
Deshalb ist `espressif32@6.5.0` (arduino-esp32 2.0.14) gepinnt.

    pio run
    ../trackerd_p2p/switch_app.py flash --bin .pio/build/trackerd_lorawan/firmware.bin

Geflasht wird **ausschliesslich app1** (0x1F0000). `app0` behaelt die
Werksfirmware v1.4.8, `nvs` mit den Schluesseln wird nicht angefasst. Zurueck
geht es jederzeit mit `../trackerd_p2p/switch_app.py lorawan`.

Achtung: app1 hielt bisher die P2P-Firmware — die wird ueberschrieben. Der
Quelltext dafuer liegt unveraendert in `../trackerd_p2p/p2p/`.

Zweite Warnung: die Quelle ist v1.5.3, auf dem Geraet lief v1.4.8. Ob die
EEPROM-Belegung beider Staende identisch ist, ist ungeprueft — den AppKey
bereithalten, falls DevEUI/Keys neu gesetzt werden muessen (`AT+DEUI`,
`AT+APPKEY`). Das 4-MB-Vollbackup liegt ausserhalb des Repos, auf dem Notebook unter
`lora/trackerd/backup/`.

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

* [DATALOG.md](DATALOG.md) — den Werks-Datalog einschalten (das ist der Weg,
  der auf dem Geraet in Lenggries laeuft)
* [LEDS.md](LEDS.md) — was die drei LEDs bedeuten, und warum ein
  Versionswechsel die Einstellungen loescht

## Lizenz

`../../../repo/` (nicht im Repo) ist Draginos Quelltext **ohne Lizenzangabe** — quelloffen, aber nicht
Open Source. `src/` ist eine Arbeitskopie davon; was hier veroeffentlicht
werden soll, gehoert als Patch gegen `repo/` verteilt, nicht als Kopie.
TinyGPS++ im Baum ist LGPL-2.1+, OneButton BSD, arduino-lmic MIT.

## attic-tracklog/

Der erste Anlauf: ein eigener Ringpuffer im ungenutzten spiffs-Bereich
(192 KB, 9792 Fixes ≈ 6,8 Tage), gebuendelte Nachlieferung auf einem eigenen
Port, dazu ein Testrahmen, der die Ringlogik ohne Geraet prueft (`test/`).
Funktioniert und ist durchgetestet, war fuer die Aufgabe aber zu gross.
Liegt hier, falls vier Stunden irgendwann nicht mehr reichen.
