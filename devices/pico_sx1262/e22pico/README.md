# e22pico — ein SX1262, zwei Welten: roher Ebyte-Kanal und LoRaWAN

Der Waveshare Pico-LoRa (SX1262 am RP2040) läuft mit **einer** Firmware in
zwei Betriebsarten, umschaltbar zur Laufzeit und über die Luft:

| | `MODUS_LORA` (roher Kanal) | `MODUS_LORAWAN` |
|---|---|---|
| Funkprofil | 868.125 MHz, SF11/BW500, CR4/5, LDRO 1, Sync **0x55** | EU868, 867.1–868.5, SF7–12/BW125, Sync **0x34** |
| Rahmen | Ebyte (Magic `2c 12`, Prüfbytes, Adresse, XOR `0x12`) | LoRaWAN 1.0.3 Class A, OTAA |
| Gegenstelle | E22-Module, E90-Relais, `lora_raw.py` auf dem dell (UDP 1702) | ChirpStack auf dem dell (über den DLOS8N, UDP 1700) |
| Verschlüsselung | keine | AES-128 (AppKey/Sitzungsschlüssel) |
| Parameter | [`src/loraparms.h`](src/loraparms.h) | [`src/lorawanparms.h`](src/lorawanparms.h) |

Beides hört dasselbe Gateway gleichzeitig: die acht MultiSF-Kanäle des DLOS8N
stehen unverändert auf 0x34, `chan_Lora_std` dank des Syncword-Shims auf 0x55
(siehe [`../../../gateway/RAWKANAL.md`](../../../gateway/RAWKANAL.md) und
[`../../../gateway/sx1302_syncword/`](../../../gateway/sx1302_syncword/)). Am
Gateway ist für die Umschaltung **nichts** zu tun.

Stand **21.08.2026**, auf der Hardware verifiziert (Abschnitt „Was gemessen
ist").

## Umschalten — vier Wege

| Weg | Befehl | wo brauchbar |
|---|---|---|
| über die Luft, roher Kanal | `C>MODUS LORAWAN [min]` | der eigentliche Fall: Knoten ohne WLAN, nur Funk |
| über die Luft, LoRaWAN | Downlink FPort 10, Byte 0 = `0x00` [+ 2 Byte Minuten] | Rückweg, wenn der Knoten schon im LoRaWAN ist |
| USB / UART | `modus lora` \| `modus lorawan` oder `AT+LORAWAN=0|1[,min]` | am Schreibtisch |
| von selbst | die Minutenangabe oben | Rückfahrkarte, s. u. |

**Die Rückfahrkarte.** Beide Luftbefehle nehmen optional Minuten:
`C>MODUS LORAWAN 30` schaltet um und kommt nach 30 Minuten von allein auf den
rohen Kanal zurück. Damit ist ein Fehlversuch nicht tödlich — wenn im LoRaWAN
niemand antwortet, ist der Knoten eine halbe Stunde später wieder da, wo man
ihn erreicht. Die Vormerkung steht **nur im RAM**: ein Stromausfall in der
Zwischenzeit lässt den Knoten in der zuletzt *gesicherten* Betriebsart
aufwachen.

Ein per Funk ausgelöster Wechsel wird erst ausgeführt, wenn die Antwort darauf
gesendet ist — sonst risse der Neuaufbau des Funkchips die Quittung weg.

## AT-Kommandos

Der Knoten spricht zusätzlich das Kommando-Set der Dragino-Geräte, damit er
sich wie ein LA66-Stick einbinden lässt. Vorlage ist der `AT+CFG`-Abzug des
eigenen LA66 ([`../../la66_p2p/la66_lorawan_v1.3_cfg.txt`](../../la66_p2p/la66_lorawan_v1.3_cfg.txt));
Draginos Firmware dazu liegt offen ([github.com/dragino/LA66](https://github.com/dragino/LA66),
ASR6601-SDK).

Zwei gleichwertige Schnittstellen: die **USB-Konsole** (115200) und eine echte
**UART auf GP0 (TX) / GP1 (RX)**, 9600 Baud wie beim LA66 ab Werk. Die UART ist
der eigentliche Zweck — ein Host ohne USB-Stack (ESP, SPS, Pi ohne freien Port)
hängt sich mit zwei Drähten an den Knoten. Betriebsmeldungen gehen an beide,
Antworten nur an den Fragesteller.

Abfrage mit `=?`, Antwort ist der nackte Wert, dann `OK`; Fehler sind
`AT_ERROR`, `AT_PARAM_ERROR`, `AT_NO_NETWORK_JOINED`.

| Kommando | Wirkung | Beispiel/Antwort |
|---|---|---|
| `AT` | Lebenszeichen | `OK` |
| `AT?` | Kommandoliste | |
| `ATZ` | Neustart | |
| `AT+CFG` | alles anzeigen, Zeilen im LA66-Format | `AT+DEUI=50 49 43 4F 00 00 0E 22` … |
| `AT+VER=?` / `AT+VERSION=?` | Firmwarestand | `EU868 v2.0.0 pico-e22 LoRa+LoRaWAN 0E22` |
| `AT+LORAWAN=?` | Betriebsart | `0` = roher Kanal, `1` = LoRaWAN |
| `AT+LORAWAN=1,30` | umschalten, Rückkehr nach 30 min | dieselbe Sprache wie beim TrackerD |
| `AT+SEND=<cfm>,<port>,<len>,<text>` | senden | LoRaWAN-Uplink **oder** Ebyte-Rahmen — je nach Betriebsart |
| `AT+SENDB=<cfm>,<port>,<len>,<hex>` | dasselbe binär | `AT+SENDB=0,2,2,00ff` |
| `AT+RECV=?` / `AT+RECVB=?` | letzter Empfang als Text bzw. Hex | `0:PONG 1 N00 …` |
| `AT+JOIN` | OTAA-Join auslösen | nur im LoRaWAN-Betrieb |
| `AT+NJS=?` | 1 = Sitzung aktiv | |
| `AT+DEUI=?` `AT+APPEUI=?` `AT+DADDR=?` `AT+FCU=?` | Kennungen und Zähler | |
| `AT+ADR=0|1` `AT+DR=<0-5>` | ADR und Datenrate | |
| `AT+RELAY=0|1` | Relais des rohen Kanals | |
| `AT+ID=?` `AT+RSSI=?` `AT+SNR=?` | Stationskennung, letzter Empfang | |
| `AT+FRE=?` `AT+SF=?` `AT+BW=?` `AT+CR=?` `AT+POWER=?` `AT+SYNCWORD=?` `AT+PREAMBLE=?` | Parameter des rohen Kanals | **nur lesbar**, s. u. |

Bewusste Abweichungen vom LA66:

* **`AT+APPKEY` antwortet `<im Geraet>`.** Der Schlüssel kommt weder über die
  Konsole heraus noch in den eingebetteten Quelltext (`src`).
* **Die Parameter des rohen Kanals sind nur lesbar.** Sie stehen in
  `loraparms.h` und gelten nach jedem Start unverändert — Frequenz oder
  Spreizfaktor per Funk zu verstellen macht eine Station unerreichbar, genau
  wie bei `fernwirk.py` an der Relaisstelle Brauneck. Ein Schreibversuch
  antwortet `AT_ERROR`.
* **Empfänge werden unaufgefordert gemeldet**, im LA66-Format
  `AT+RECVB=<Port>:<Hex>` (abschaltbar über `AT_RECV_MELDEN` in
  [`src/atparms.h`](src/atparms.h)). Reine MAC-Downlinks (FPort 0, keine
  Nutzlast) werden nicht gemeldet.

Ein Host darf sein Echo nicht zurückschicken: der Knoten beantwortet jede Zeile,
die mit `AT` beginnt — auch die eigene. (Am Linux-Terminal deshalb
`stty -F /dev/ttyACM0 115200 raw -echo`, sonst schaukelt sich das auf.)

Der LA66 selbst kann **nicht** per AT zwischen LoRaWAN und P2P wechseln: dort
ist es ein Firmware-Tausch, siehe [`../../la66_p2p/README.md`](../../la66_p2p/README.md)
und `la66_mode.py`. Der Pico kann es, weil beide Stacks in einem Binary liegen.

## Kurze Klartext-Kommandos (wie bisher)

`diag` · `tx` · `relais [on|off]` · `modus [lora|lorawan]` · `lwstat` ·
`lwsend <text>` · `lwreset` · `src` · `boot`

`src` gibt den eigenen Quelltext aus — er liegt mit im Flash, erzeugt von
`quelltext_einbetten.py` vor jedem Bau, inzwischen über **alle** Dateien in
`src/` außer `lorawan_geheim.h`. `lwreset` verwirft Sitzung und DevNonce
(danach muss auch der Netzwerkserver zurückgesetzt werden, sonst weist er den
wiederholten DevNonce als Replay ab).

## Fernwirken über den rohen Kanal

Sprache wie an der Relaisstelle Brauneck ([`../fernwirk.py`](../fernwirk.py)):
Befehl `C>NAME [wert]`, Antwort `A><Kennung>>text`. Die Kennung ist
**vierstellig hex und zugleich die Geräteadresse**: die letzten vier Stellen
der DevEUI, hier `0E22` — so wie der TrackerD seine `076C` aus
`a840414f1188076c` ableitet.

| Befehl | Wirkung |
|---|---|
| `C>MODUS` | Betriebsart abfragen |
| `C>MODUS LORAWAN [min]` / `C>MODUS LORA [min]` | umschalten, optional befristet |
| `C>STATUS` | Kennung, Betriebsart, Zähler, Laufzeit, Relais, Uplinks |
| `C>RELAY 0\|1` | Relais schalten |
| `C>ID` | Kennung lesen (nicht setzbar — sie ist die Geräteadresse) |
| `C>PING` | Lebenszeichen |

Vom dell aus: `./lora_cmd.py MODUS LORAWAN 5`. Bewusst **ohne
Authentisierung**, dieselbe Abwägung wie bei `fernwirk.py`: wer in
Funkreichweite ist, kann den Knoten umstellen. Für ein Krisensystem ist der
Funk der Weg, der trägt, wenn sonst nichts mehr geht.

Befehle (`C>`) und Antworten (`A>`) werden **nie** weitergeleitet, wie bei
`repeater.py`. Ein über ein Relais gelaufener Befehl (`RC>…`) gilt trotzdem —
sonst wäre hinter einem Relais niemand zu erreichen.

## LoRaWAN-Seite

**Anmeldung im ChirpStack** (auf dem dell, 192.168.5.23):
[`../../../dell/cs_pico.py`](../../../dell/cs_pico.py) legt Anwendung,
Geräteprofil (EU868, **LoRaWAN 1.0.3**, Class A, OTAA) und Gerät an und trägt
den AppKey ein:

```bash
APPKEY=<32 Hex> /home/gh/.venv-chirpstack/bin/python cs_pico.py
```

1.0.3 und nicht 1.1, weil die Firmware RadioLib nur den AppKey übergibt
(`nwkKey = NULL`); mit einem zweiten Schlüssel stellte RadioLib auf 1.1 um und
der Join scheiterte am Profil.

**Uplink**, FPort 1, 8 Byte groß-endian, alle 15 Minuten (Duty Cycle wird
zusätzlich von RadioLib erzwungen):

| Byte | Inhalt |
|---|---|
| 0–1 | Laufzeit in Minuten |
| 2–3 | empfangene Rahmen des rohen Kanals |
| 4–5 | beantwortete Rahmen |
| 6 | RSSI des letzten rohen Pakets (dBm, signed) |
| 7 | SNR (dB, signed) |

Der Decoder dafür steckt im Geräteprofil (`cs_pico.py`, `CODEC`).

**Downlink-Steuerport 10**, einzureihen mit
[`../../../dell/cs_pico_modus.py`](../../../dell/cs_pico_modus.py):

| Bytes | Wirkung |
|---|---|
| `00` [`HH LL`] | zurück auf den rohen Kanal, optional Rückkehr nach `HHLL` Minuten |
| `01` | im LoRaWAN bleiben, vorgemerkte Rückkehr löschen |
| `02 00\|01` | Relais aus/ein |

```bash
./cs_pico_modus.py lora 30      # 30 Minuten roher Kanal, dann von selbst zurück
./cs_pico_modus.py lorawan
```

Class A: der Befehl wartet in der Warteschlange, bis der Knoten das nächste Mal
sendet. Wer nicht warten will, stößt einen Uplink an (`lwsend x` oder
`AT+SEND=0,1,1,x`).

## Was den Stromausfall überlebt

[`src/speicher.h`](src/speicher.h) / [`src/speicher.cpp`](src/speicher.cpp):
Betriebsart, DevNonce und LoRaWAN-Sitzung liegen in den **letzten vier
Flash-Sektoren**, reihum beschrieben mit hochzählender Folgenummer und CRC32.
Gelesen wird der jüngste gültige Sektor; ein Stromausfall mitten im Schreiben
macht nur den neuen Sektor ungültig, der alte gilt weiter. Reihum, weil ein
Sektor rund 100 000 Löschungen aushält und die Sitzung im Betrieb regelmäßig
neu geschrieben wird.

Warum überhaupt: ein OTAA-DevNonce darf sich nie wiederholen (der
Netzwerkserver wertete das als Replay), und ohne gesicherte Sitzung wäre jeder
Neustart ein neuer Join. Gesichert wird bei jedem Wechsel der Betriebsart, nach
jedem Join und alle `LW_SITZUNG_ALLE` Uplinks (Vorgabe 8).

**Beim Verlassen des LoRaWAN-Betriebs wird die Sitzung ausdrücklich gesichert.**
Ohne das fiel der Uplink-Zähler beim Zurückschalten auf den letzten gesicherten
Stand zurück, und ChirpStack verwarf die nächsten Uplinks stillschweigend als
Wiederholung — am 21.08. genau so gemessen.

## Bauen und Flashen (fernsteuerbar, ohne Taste)

```bash
pio run -d ~/e22pico                     # → .pio/build/pico/firmware.uf2
printf "boot\n" > /dev/ttyACM0           # Firmware-Kommando „boot“ → BOOTSEL
sleep 2
DEV=$(lsblk -lnp -o NAME,LABEL | awk '$2=="RPI-RP2"{print $1}')
udisksctl mount -b "$DEV"                # oder: sudo mount -t vfat -o uid=gh …
cp ~/e22pico/.pio/build/pico/firmware.uf2 /media/$USER/RPI-RP2/
sync && sleep 2                          # Laufwerk verschwindet, Pico rebootet
```

Der AppKey steht in `src/lorawan_geheim.h` — **nicht im Git**, Vorlage ist
[`src/lorawan_geheim.h.vorlage`](src/lorawan_geheim.h.vorlage). Ohne die Datei
baut die Firmware trotzdem, joint dann aber nicht (Platzhalter aus Nullen).
Erst den Schlüssel anlegen, dann bauen: ein Bau davor flasht den Platzhalter,
und der Netzwerkserver meldet nur ein dürres `Invalid MIC` — am 21.08. genau in
diese Falle getappt.

## Warum nicht pico-lorawan

[Sandeep Mistrys pico-lorawan](https://github.com/sandeepmistry/pico-lorawan)
ist die naheliegende Referenz, war hier aber der falsche Weg — geprüft, nicht
vermutet:

* Die Glue-Schicht des Projekts ist **SX1276-only**: `src/lorawan.c` bindet
  `sx1276-board.h` ein, spricht `SX1276.Spi`, `SX1276.DIO0/DIO1` und bricht in
  `lorawan_init()` mit `SX1276Read(REG_LR_VERSION) != 0x12` ab. Das
  CMakeLists.txt zieht genau `radio/sx1276/sx1276.c` und
  `src/boards/rp2040/sx1276-board.c`. Der SX126x-Treiber liegt zwar im
  LoRaMac-node-Submodul, aber ohne rp2040-Board-Schicht (BUSY, DIO1, TCXO über
  DIO3, Antennenschalter über DIO2) nützt er nichts — die wäre neu zu
  schreiben.
* Es ist ein reines **pico-sdk/CMake**-Projekt. Diese Firmware ist ein
  Arduino/PlatformIO-Binary, in dem der rohe Kanal seit Monaten läuft. Für die
  Umschaltung zur Laufzeit müssen beide Stacks in *einem* Binary stecken;
  zwei Build-Systeme und zwei Radio-Treiber auf demselben Chip wären ein
  Rückschritt gegenüber dem, was schon funktioniert.

Genommen wurde stattdessen der LoRaWAN-Stack von **RadioLib 7.7.1** — dieselbe
Bibliothek, die den rohen Kanal schon fährt. Beide Betriebsarten teilen sich
ein `Module`, der LoRaWAN-Stack stellt Frequenz, SF, Syncword, Präambel und IQ
vor jedem Uplink selbst.

Eine Falle dabei: der rohe Kanal erzwingt `forceLDRO(1)` (Ebyte-Werkswert).
LoRaWAN braucht die Automatik, sonst stünde bei DR5 (SF7/BW125) ein LDRO-Bit,
das das Gateway nicht erwartet. Beim Wechsel wird deshalb ausdrücklich
`autoLDRO()` gesetzt — und beim Rückweg wieder `forceLDRO`.

## Was gemessen ist (21.08.2026)

* **Join und Uplink**: `Uplink received f_type=JoinRequest` →
  `DevAddr 00E68B81`, danach Uplinks mit LinkADRReq/DevStatusReq als Downlink
  zurück. Gateway `a84041ffff27e318`, DR3.
* **Downlink schaltet um**: `cs_pico_modus.py lora 3` → beim nächsten Uplink
  `Downlink FPort 10, 3 B: 00 00 03` → `Betriebsart: roher Kanal`, Rückkehr
  vorgemerkt.
* **Luftbefehl schaltet um**: vom dell `./lora_cmd.py MODUS LORAWAN 5` →
  Antwort `A>0E22>MODUS LORAWAN, Rueckkehr in 5 min` (RSSI −81, SNR 7,8) →
  Wechsel, Sitzung aus dem Flash fortgesetzt, kein neuer Join.
* **AT über USB**: `AT` → `OK`; `AT+CFG` liefert den vollen Abzug;
  `AT+SEND=0,1,5,hallo` im rohen Betrieb kommt am Gateway als
  `868.125 MHz SF11BW500 RSSI −84 … 5B "hallo"` an, der LoRaWAN-Uplink
  desselben Knotens als `867.900 MHz SF9BW125 … 21B`.
* **Flash**: Folgenummern zählen über alle Wechsel hoch, nach dem Neustart
  steht die Betriebsart und die Sitzung wieder da (`Sitzung fortgesetzt`).

## Inhalt

```
platformio.ini              PlattformIO-Projekt (board=pico, framework=arduino)
src/loraparms.h             Parameter und Pins des rohen Kanals
src/lorawanparms.h          LoRaWAN-Parameter, DevEUI, Startbetriebsart
src/lorawan_geheim.h        AppKey — nicht im Git (Vorlage: *.vorlage)
src/atparms.h               AT-Schnittstelle: UART-Pins/Baud, Version, Melden
src/speicher.h/.cpp         Flash-Ringspeicher für Betriebsart und Sitzung
src/main.cpp                Firmware
quelltext_einbetten.py      bettet src/ vor jedem Bau in die Firmware ein
pico_c_pingpong.py          Testskript: E22 sendet „A n“, zählt PONGs
```

Gegenstücke auf dem dell:
[`cs_pico.py`](../../../dell/cs_pico.py) (im ChirpStack anlegen),
[`cs_pico_modus.py`](../../../dell/cs_pico_modus.py) (Downlink-Steuerbefehl),
[`lora_cmd.py`](../../../dell/lora_cmd.py) (Funkbefehl auf dem rohen Kanal).
