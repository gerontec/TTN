# Per-Kanal-Syncword für den SX1302 (Dragino DLOS8N, 10.9.0.9)

Gibt dem Rohkanal `chan_Lora_std` ein **eigenes LoRa-Syncword**, während die
8 LoRaWAN-Kanäle unverändert auf 0x34 bleiben — gleichzeitig, ohne Umschalten.

## Was die Hardware kann und was nicht

Der SX1302 hat genau **vier** RX-Syncword-Registerpaare:

| Registerpaar | Adressen | gilt für |
|---|---|---|
| `SF5_PEAK1/2` | `0x588A/0x588B` | alle 8 MultiSF-Kanäle, nur SF5 |
| `SF6_PEAK1/2` | `0x588C/0x588D` | alle 8 MultiSF-Kanäle, nur SF6 |
| `SF7TO12_PEAK1/2` | `0x588E/0x588F` | alle 8 MultiSF-Kanäle, SF7–12 |
| `LORA_SERVICE_PEAK1/2` | `0x5B2E/0x5B2F` | **nur** `chan_Lora_std` |

Ein Register **pro IF-Kanal existiert nicht**. Die 8 MultiSF-Kanäle teilen sich
einen Demodulator-Block, dessen Syncword nur nach Spreading Factor aufgeteilt
ist. **Einer von diesen 8 kann daher kein eigenes Syncword bekommen** — das ist
eine Eigenschaft des Chips, keine Softwaregrenze. `chan_Lora_std` kann es, und
ist deshalb der Kanal für einen privaten Link neben dem LoRaWAN-Betrieb.

### Wertebereich

Ein Syncword `0xHL` steckt in den zwei Sync-Symbolen der Präambel. Der SX1302
speichert je Symbol `symbolwert/4`, also **`peak_pos = nibble * 2`**. Das Feld
ist 5 Bit breit und `lgw_com_rmw()` maskiert **vorzeichenlos** — damit ist der
volle Bereich `0x00..0xFF` erreichbar. Die Beschränkung auf 0x12/0x34 ist reine
Softwarekonvention (`lorawan_public`), keine Chip-Limitierung.

Beispiel: `peak2 = 16` (unteres Nibble 8) liegt über dem Maximum eines
*vorzeichenbehafteten* 5-Bit-Feldes und wurde im Test trotzdem korrekt gesetzt
— der Beweis, dass unsigned maskiert wird und damit alle 256 Werte gehen.

## Warum Interposition statt Lib-Austausch

Dragino hat den SX1302-Chipreset **in die HAL verlegt** (`libsx1302hal.so` linkt
gegen `libgpio.so`; `/etc/init.d/lora_gw` ruft für sx1302 kein Reset-Skript).
Ein Upstream-Build als Drop-in würde diesen Reset verlieren. Der Shim ersetzt
per `LD_PRELOAD` genau **eine** Funktion, `sx1302_lora_syncword(bool, uint8_t)`
— eine Signatur ohne Structs, also **ABI-neutral**. Draginos `fwd_sx1302` und
der Rest der HAL bleiben unangetastet.

Die Register werden über `lgw_com_rmw()` **adressbasiert** geschrieben, nicht
über Registertabellen-IDs. Damit ist der Shim unabhängig davon, ob Draginos
Registertabelle mit Upstream übereinstimmt.

MIPS löst GOT-Einträge beim Laden **eager** auf. Eine Preload-Lib mit
undefiniertem Symbol scheitert deshalb mit `symbol not found`, bevor die HAL
geladen ist. Der Shim trägt darum ein `DT_NEEDED` auf `libsx1302hal.so`
(erzeugt über `stub_libsx1302hal.c`, der nur zum Linken dient und nie
ausgeliefert wird).

## Bauen und Ausrollen

Toolchain: OpenWrt-18.06-SDK, `ar71xx/generic`, `mips_24kc`, big-endian, musl.

```sh
make SDK=/pfad/zu/openwrt-sdk-18.06.9-ar71xx-generic_gcc-7.3.0_musl.Linux-x86_64
make install GW=root@10.9.0.9
```

`install` legt `libsx1302syncword.so` nach `/usr/lib/` und `syncword.conf` nach
`/etc/lora/`. Aktiv wird der Shim erst über `LD_PRELOAD` (siehe unten).

Das Gateway läuft mit altem Dropbear — SSH braucht:
`-o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa`

## Konfiguration

`/etc/lora/syncword.conf`, gelesen bei jedem `lgw_start()` (also bei jedem
Neustart des Packet Forwarders):

```
sf5     = auto      # auto = Stock-Verhalten aus lorawan_public
sf6     = auto
sf7to12 = auto      # 0x34 bei lorawan_public=true -> für LoRaWAN so lassen
service = 0x55      # chan_Lora_std allein (Ebyte E22/E90)
ldro    = 1         # LDRO des Service-Modems erzwingen, siehe unten
```

Fehlt die Datei oder steht alles auf `auto`, schreibt der Shim **bitgenau
dieselben Register wie Upstream**.

### LDRO

Der HAL leitet LDRO aus `SET_PPM_ON(bw, dr)` ab — wahr nur bei BW125 mit
SF11/SF12 und BW250 mit SF12, bei **BW500 also nie**. Ebyte-Module senden BW500
mit LDRO 1. Bei falschem LDRO rastet der Header ein und `HeaderValid` feuert,
aber *jede* Nutzlast kommt mit CRC-Fehler — es sieht aus wie „fast richtig".
`ldro = 1` überschreibt das Register `0x5B22` (Bits 4–5). Der Override ist
zulässig, weil `sx1302_lora_service_modem_configure()` in `loragw_hal.c:976`
läuft, der Hook aber erst in `:993`.

## sx1302_poke — Register im laufenden Betrieb

`sx1302_poke` liest und schreibt einzelne SX1302-Register über
`/dev/spidev1.0`, **während der Forwarder läuft**. Das ist gefahrlos, weil der
SX1302 kein Page-Register hat (anders als der SX1301): ein Zugriff ist durch
seine Adresse vollständig beschrieben, und jeder Zugriff ist ein einzelnes
`ioctl(SPI_IOC_MESSAGE)`, das der Kernel gegen die Transfers des Forwarders
serialisiert.

```sh
sx1302_poke 0x5B2E              # lesen
sx1302_poke 0x5B2F 10           # schreiben
sx1302_poke syncword 0x55       # Service-Syncword komplett setzen
```

Damit wird aus einer Suche über 16 Kandidaten mit 16 Forwarder-Neustarts ein
einziges kurzes Messfenster — genau so wurde 0x55 gefunden.


## Verifizierte Tests (17.08.2026)

### 1. Eigenes Syncword, Gegenprobe mit dem Pico

`chan_Lora_std` auf SF7/BW125, `service = 0x58`, `sf7to12 = auto` (0x34):

| Pico sendet | Gateway | Ergebnis |
|---|---|---|
| 0x58 | `chan 8`, 868.125 MHz, `rxnb 6 / rxok 6 / rxfw 6` | `EBYTE58-*` empfangen |
| 0x34 | **nicht** auf chan 8, sondern `chan 0` (868.100, `foff −25 kHz`) | Gegenprobe hält |

Beide Blöcke laufen gleichzeitig — Service auf 0x58, MultiSF auf 0x34.

Nebenbefund: der Rohkanal auf 868.125 überlappt `chan_multiSF_0` auf 868.100 bei
125 kHz Bandbreite um 25 kHz, weshalb P2P-Verkehr mit 0x34 in den LoRaWAN-Kanal
leckt. Ein abweichendes Syncword schneidet das sauber ab.

### 2. Ebyte E22 auf dem Rohkanal

E22-900T (USB, CH340), Werkskonfiguration: Air Rate 2.4k, Kanal 18. Laut
`devices/pico_sx1262/EBYTE_E90.md` heißt das **SF11/BW500/LDRO 1**, nicht
SF11/BW125 — die Luftraten-Etiketten von Ebyte sind nominal.

Gateway entsprechend auf `spread_factor 11`, `bandwidth 500000`, `service = 0x55`,
`ldro = 1`:

```json
{"chan":8,"freq":868.125000,"datr":"SF11BW500","rssi":-63,"stat":1,
 "size":15,"data":"LBKHJgD//wdCQF1WPyIh"}
```

Dekodiert: `2C 12 87 26 00 FF FF 07 | Nutzlast XOR 0x12` → **`PROD-03`**.
Byte 1 ist die Kanalnummer *und* zugleich der XOR-Schlüssel.

**Das Syncword ist 0x55, nicht 0x58.** `EBYTE_E90.md` nannte 0x58, aber das war
nur das obere Nibble: ein SX126x-Empfänger wertet allein das erste
Syncword-Registerbyte aus, weshalb dort alle acht Werte 0x58–0x5F trafen. Der
SX1302 prüft beide Peak-Positionen streng; ein Live-Sweep von `peak2` mit
`sx1302_poke` lieferte Pakete ausschließlich bei `peak2 = 10` — also 0x55.

### 3. LoRaWAN-Regression

LA66-USB (EU868 v1.3, DevEUI `A840 4117 F189 62E0`, bereits gejoint), Uplink auf
868.500 MHz DR0:

```json
{"chan":2,"freq":868.500000,"datr":"SF12BW125","rssi":-85,"stat":1,
 "data":"QOBiiQEAAAACTE9SQVdOCtSQ9g=="}
```

Frame sauber: MHDR `0x40` (Unconfirmed Data Up), DevAddr `0x018962E0`, FCnt 0,
FPort 2, Nutzlast `LORAWN`. **Die LoRaWAN-Kette ist vom Eingriff nachweislich
nicht betroffen.**

## Zeitmultiplex — gemessen und verworfen

Gemessen auf dem Gateway (`SYNCWORD_BENCH=200`, SPI 2 MHz):

```
294,8 µs pro Umschaltung des MultiSF-Paares (2 RMW = 4 SPI-Transfers)
589,6 µs hin und zurück
```

Das ist schnell genug — das SF7-Sync-Fenster ist 2050 µs. Trotzdem funktioniert
Multiplexing nicht, aus einem strukturellen Grund: **Es gibt keinen Trigger.**
Die Paketerkennung *ist* der Syncword-Vergleich. Wenn ein Paket auffällt, sind
die Sync-Symbole längst ausgewertet und das Paket verworfen. Man kann nicht
„umschalten, wenn gesendet wird" — man weiß es erst danach.

Bliebe blindes Duty-Cycling. Das ist ein Nullsummenspiel: bei Anteil *f* auf dem
privaten Syncword gehen ~*f* der LoRaWAN-Uplinks verloren und ~(1−*f*) der
privaten. `chan_Lora_std` liefert das private Syncword dauerhaft parallel bei
**null** LoRaWAN-Verlust. Sinnvoll wäre TDM nur bei *geplantem* Sendeverkehr
(TDMA-Slots), nicht bei spontanem Krisenfunk.

Sync-Fenster zum Vergleich (BW 125 kHz, `Ts = 2^SF / BW`, 8 Symbole Präambel):

| SF | Symbolzeit | Präambel | Sync-Fenster (2 Symbole) |
|---|---|---|---|
| SF7 | 1,024 ms | 8,19 ms | 2,05 ms, ab 8,19 ms |
| SF9 | 4,096 ms | 32,8 ms | 8,19 ms, ab 32,8 ms |
| SF12 | 32,77 ms | 262 ms | 65,5 ms, ab 262 ms |

**Beim Senden ist die Frage gegenstandslos:** `sx1302_send()` schreibt
`TX_TOP_A/B_FRAME_SYNCH` ohnehin **pro Paket** direkt vor dem Tasten, indiziert
nach `rf_chain`. Ein Downlink mit abweichendem Syncword braucht kein Multiplex.

## Persistenz: die Vorlage ist maßgeblich

`/etc/lora/global_conf.json` zu editieren ist wirkungslos.
`init_board()` in `/etc/init.d/lora_gw` ruft bei **jedem** Start
`/usr/bin/generate-config.sh`, und das kopiert
`/etc/lora/cfg-302/EU-global_conf.json` über die Datei. Zu ändern ist also die
**Vorlage**. Siehe auch `../RAWKANAL.md`, wo diese Falle schon steht.

Der `LD_PRELOAD` des Shims wiederum gehört in `/usr/bin/fwd_syncword`, nicht in
`procd_set_param env`: procd setzt für die Zeilenpufferung selbst
`LD_PRELOAD=/lib/libsetlbf.so` und überschreibt einen per `env` gesetzten Wert.
Der Wrapper hängt den Shim deshalb *nach* procd an, mit `:` getrennt.

## Kanalkommentare im global_conf.json

Das `desc`-Feld je Kanal ist **reiner Kommentar**. `fwd_sx1302` parst nur den
Gateway-`desc` aus `local_conf.json` für das `stat`-JSON; ein kanalbezogenes
`desc` kommt im Binary nicht vor. Es wird also nicht validiert und kann
unbemerkt von `radio`/`if`/`spread_factor` abweichen — nachrechnen mit
`freq = radio[n].freq + if`.

## Dateien

| Datei | Zweck |
|---|---|
| `sx1302_syncword_preload.c` | der Shim, ersetzt `sx1302_lora_syncword()` |
| `stub_libsx1302hal.c` | Link-Stub für das `DT_NEEDED`, wird nicht ausgeliefert |
| `syncword.conf` | Konfiguration, nach `/etc/lora/` |
| `Makefile` | Cross-Build + `install` |
| `0001-per-demod-syncword.patch` | dieselbe Logik als Patch gegen `Lora-net/sx1302_hal` V2.1.0, für einen vollständigen eigenen HAL-Build (siehe unten) |

## Alternative: vollständiger eigener HAL

`0001-per-demod-syncword.patch` implementiert dasselbe direkt in
`libloragw/src/loragw_sx1302.c` von `Lora-net/sx1302_hal` V2.1.0, plus die neue
API `lgw_syncword_override(sf5, sf6, sf7to12, service)` in `loragw_sx1302.h`.
Der Patch cross-kompiliert sauber für `mips_24kc`.

Für einen **Austausch** der Lib auf diesem Gateway fehlen aber zwei Dinge:

1. Draginos GPIO-Chipreset müsste nachgebaut werden (Pin unbekannt, steckt in
   `libsx1302hal.so` über `libgpio.so`).
2. Die Struct-ABI zwischen Draginos `fwd_sx1302` und Upstream V2.1.0 ist nicht
   verifiziert. Alle 30 von `fwd` gezogenen Symbole sind Stock-V2.1.0-API, was
   dafür spricht — bewiesen ist es nicht. Bei abweichendem Layout (z. B.
   `lgw_pkt_rx_s`) gäbe es stille Speicherfehler.

Deshalb ist im Produktivbetrieb der Shim der belastbarere Weg.
