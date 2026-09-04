# TrackerD: den Datalog einschalten

Am 23.08.2026 fehlten 8 h 38 min Fahrt in der Datenbank — zwischen 09:27 und
18:05 kam kein einziger Uplink an, und nachgeliefert wurde nichts. Der Grund
ist keine fehlende Funktion, sondern eine Werkseinstellung.

## Der Datalog ist da, er ist nur aus

Die Firmware puffert Positionen, die nicht rausgehen — aber nur, wenn
`PNACKMD` eingeschaltet ist. Ab Werk steht es auf 0 (`common.h`:
`uint8_t PNACKmd = 0;`), und das Geraet sagt es auch selbst: im Status-Uplink
auf **fPort 5** ist das letzte Byte `FLAG = ((PNACKmd<<2) | (lon<<1) | Intwk)`.

    13 01 48 01 ff 0f a2 40 02
                            ^^ FLAG 0x02 -> PNACKmd 0, lon 1, Intwk 0

(Davor: `sensor_type 0x13`, `firm_ver 0x0148` = v1.4.8, Band EU868,
`battrey 0x0fa2` = 4002 mV, `SMODE 0x40` = GPS-Modus.)

## Einschalten

Serielle Konsole, 115200 Baud:

    AT+PNACKMD=1      -> OK
    AT+PNACKMD=?      -> 1

Beides — `PNACKmd` **und** das davon abgeleitete `frame_flag` — wird von
`config_Write()` ins EEPROM geschrieben (`common.cpp` Zeile 827/878), der
AT-Parser ruft das nach jedem erfolgreichen `=`-Befehl selbst auf. Die
Einstellung ueberlebt also Neustart und Stromausfall.

**Achtung, ein Wechsel der Firmware-Version loescht die Einstellung.** Die
Firmware vergleicht beim Kaltstart `fire_version` mit dem im EEPROM
abgelegten Wert; sind sie verschieden, ruft sie `DATA_CLEAR()` und startet
neu — `PNACKMD` steht dann wieder auf 0. app0 meldet 1.4.6, app1 meldet 1.4.8;
jeder Wechsel zwischen den Slots kostet also einmal die Einstellungen.
Erkennbar ist es an der Farbfolge Blau-Rot-Gruen beim Start, siehe
[LEDS.md](LEDS.md).

**Achtung, jede serielle Sitzung kostet einen Join.** Das Oeffnen des Ports
zieht ueber DTR/RTS einen Power-on-Reset; damit ist der RTC-Speicher weg,
`RTC_LMIC.seqnoUp = 0`, und das Geraet macht ein neues OTAA-Join. Danach
setzt `EV_JOINED` ausserdem `os_JOINED_flag = 1`, woraus `sys_sleep()`
`sys.tdc = 1000` macht — ein Zyklus im Sekundentakt, bei dem die gruene LED
pro `EV_TXSTART` 200 ms blitzt und deshalb wie Dauerlicht aussieht. Das legt
sich nach dem naechsten Zyklus von selbst.

## Was sich damit aendert

**Alle Uplinks werden bestaetigt.** `AT+PNACKMD=1` setzt `frame_flag = 1`.
Das Netz muss also auf jeden Uplink ein Downlink-Fenster bedienen. Kontrolle
in der Datenbank:

    SELECT ts, f_port, confirmed FROM loradevice
     WHERE dev_eui='a840414f1188076c' AND event='up' ORDER BY ts DESC LIMIT 5;

`confirmed = 1` heisst: der Datalog ist scharf.

**Ungehoerte Uplinks werden wiederholt.** `EV_TXSTART` setzt bei `PNACKMD=1`
`LMIC.txCnt = 8` — bis zu acht Versuche je Uplink, bevor der Fix in den
Puffer geht. Im Funkloch kostet das Sendezeit und Batterie. Waehrend der
Nachlieferung sind es 3 Versuche, danach geht der Lesekopf einen Datensatz
zurueck.

**Der Puffer fasst 273 Fixes.** 4 KB im NVS, 15 Byte je Datensatz
(`lat4 lon4 jahr2 mon tag std min sek`), geschrieben bis `addr_gps_write`
4095 erreicht: 4095 / 15 = **273**. Bei `sensor_type 22` sind es 17 Byte und
eine Grenze von 4080, also 240 Datensaetze.

**Ein Datensatz je ungehoertem Zyklus — aber nur mit gueltiger Position.**
Der Schreibaufruf steht hinter `else if(sensor.latitude !=0 && sensor.longitude
!=0)`; ein Zyklus ohne Fix legt **nichts** ab. (Hier stand frueher das
Gegenteil; am 04.09.2026 am Quelltext nachgesehen und korrigiert.) Das ist auch
richtig so: ein Null-Datensatz traegt keine Ortsangabe und kostet einen der 273
Plaetze — im Tunnel waere der Puffer sonst voll, bevor die erste brauchbare
Position darinsteht.

**Geloggt wird nach Ereignis, nicht nach Zeit.** Die Aufzeichnungsdichte ist die
Zyklusdichte, also `TDC` (im Alarm `ATDC`) plus Suchzeit. `FTIME` begrenzt nur
die Suche je Zyklus, nicht den Logtakt.

Wie lange das reicht, folgt daraus unmittelbar:

| `AT+TDC` | Zyklus | Puffer voll nach |
|---|---|---|
| 60000 (1 min) | 68 s (am 23.08.2026 gemessen) | rund 5 Stunden |
| 300000 (5 min) | ~5,2 min | rund 1 Tag |
| **1200000 (20 min)** | ~20,2 min | **rund 3,8 Tage** |

In Lenggries steht TDC auf 1200000. Braucht das GPS unterwegs jedes Mal die
vollen `FTIME` 180 s, streckt sich der Zyklus und der Puffer haelt eher
4,4 Tage — die zusaetzlichen Plaetze tragen dann aber leere Datensaetze.

**Wiederholt wird nicht.** In `EV_TXSTART` setzt die Firmware bei `PNACKMD=1`
ausserhalb der Nachlieferung `LMIC.txCnt = 8`, und LMIC wiederholt nur
`while (txCnt < TXCONF_ATTEMPTS)` mit `TXCONF_ATTEMPTS = 8`. Der Zaehler
steht also schon am Anschlag: ein ungehoerter Uplink wird **einmal** gesendet
und dann gepuffert, statt Sendezeit in acht Versuche zu stecken. Nur waehrend
der Nachlieferung sind es `txCnt = 3`, also bis zu fuenf Versuche je
Datensatz.

**Beim Ueberlauf** dreht der Ring und ueberschreibt den aeltesten Teil: die
juengsten 273 Fixes bleiben, die Fahrt davor ist weg.

**Nachgeliefert wird auf fPort 4**, ein Datensatz je Uplink — dafuer
verkuerzt `setup()` den Takt waehrend der Nachlieferung selbst auf **10 s**.
Ein voller Puffer ist damit in rund 45 Minuten heraus (273 Datensaetze zu
10 s), unabhaengig davon, ueber welchen Zeitraum er sich gefuellt hat. In dieser Zeit
bleibt das GPS aus (`gps_start == 2 && loggpsdata_send == 0`), es kommen also
keine neuen Positionen dazu.

**Von Hand nachsehen:** `AT+PDTA=<n>` liest die naechsten *n* Datensaetze aus
dem Puffer und gibt sie als Hex auf der Konsole aus.

## Reihenfolge nach einem Ueberlauf

Nach mehr als vier Stunden Funkloch stehen die Datensaetze nicht in
zeitlicher Reihenfolge — der Ring faengt vorne an. Jeder Datensatz traegt
seine GPS-Zeit im Rumpf, sortiert wird deshalb serverseitig ueber `dev_time`,
**nie ueber `ts`**.

## Serverseite

* `trackerd.js` (ChirpStack-Decoder): fPort 4 liefert jetzt auch `Longitude`
  — das fehlte im Werks-Decoder ausgerechnet in dem Zweig, der die
  nachgelieferte Spur bringt — und `FixTime`, die GPS-Zeit als ISO-8601.
* `cs_trackerd.py` zieht den Decoder bei einem zweiten Lauf im vorhandenen
  Geraeteprofil nach.
* `lora_log.py` schreibt jeden nachgelieferten Fix zusaetzlich als eigene
  Zeile mit `event='up-log'` und `dev_time` = Zeit des Fixes.

## Stand der Partitionen

| Slot | Inhalt |
|---|---|
| app0 | Dragino v1.4.8, **Datalog eingeschaltet**, bootet |
| app1 | P2P-Firmware (Krisenkanal), `../trackerd_p2p/switch_app.py p2p` |

`./` (dieses Verzeichnis) enthaelt eine Alternative: dieselbe Werksmechanik, aber ausgeloest
ueber die Empfangsfenster RX1/RX2 statt ueber ausbleibende ACKs — damit ohne
bestaetigte Uplinks und ohne die acht Wiederholungen. Gebaut und getestet,
zurzeit nicht geflasht.
