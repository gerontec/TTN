# TrackerD: LoRa P2P als Zweitfirmware, LoRaWAN bleibt liegen

Der **Dragino TrackerD** (ESP32-PICO-D4 + RFM95W/SX1276, CH9102-USB) soll
rohes LoRa sprechen — ohne die LoRaWAN-Firmware und ihre Keys zu verlieren.
Anders als beim [LA66](../la66_p2p/) braucht es dafür keinen BOOT-Pin und
kein Gehäuseöffnen: esptool kommt über DTR/RTS von selbst in den Bootloader.

Stand **15.08.2026**.

## Es gibt keine fertige P2P-Firmware

Für den TrackerD liefert Dragino kein P2P-Binary. Die
[Releases](https://github.com/dragino/TrackerD/releases) (bis v1.5.6) sind
ausschließlich LoRaWAN. P2P steht nur als Quelltext da, als
Arduino-Beispielpaar:

* `Example/None LoRaWAN/pingpong/LoRaSender` und `.../LoRaReceiver`
* dazu `lib/arduino-LoRa` — Sandeep Mistrys SX127x-Bibliothek, in Draginos
  Kopie schon auf NSS 18 / RST 23 / DIO0 26 vorbelegt

Beide Sketches sind auf `915E6` fest verdrahtet und können nichts außer
„hello *n*" senden bzw. empfangen. Für EU868 und für einen brauchbaren
Krisenkanal ist das der Rohstoff, nicht das Ergebnis.

Nützlich ist dagegen, dass **die komplette LoRaWAN-Anwendung im Klartext
vorliegt** (`Example/LoRaWAN/examples/TrackerD/`, u. a. `TrackerD.ino` mit
78 KB und der AT-Parser in `at.cpp`). Das Gerät ist damit vollständig
nachbaubar.

## Der Trick: app1 ist frei

Das Flash-Backup zeigt eine OTA-Partitionstabelle mit zwei gleich großen
App-Slots — und der zweite ist leer:

| Partition | Typ | Offset | Größe | Inhalt |
|---|---|---|---|---|
| `nvs` | data | `0x009000` | 20 KB | Keys, DevEUI, AT-Einstellungen |
| `otadata` | data | `0x00E000` | 8 KB | welcher Slot bootet |
| `app0` | app, ota_0 | `0x010000` | 1920 KB | Dragino LoRaWAN **v1.4.8**, 1314 KB belegt |
| `app1` | app, ota_1 | `0x1F0000` | 1920 KB | **komplett 0xFF — frei** |
| `spiffs` | data | `0x3D0000` | 192 KB | |

P2P muss LoRaWAN also gar nicht verdrängen. Die neue Firmware geht nach
`app1`, umgeschaltet wird über `otadata`. Bootloader, Partitionstabelle,
`app0` und `nvs` werden nie angefasst — die LoRaWAN-Keys bleiben, wo sie
sind.

`otadata` sind zwei 4-KB-Sektoren mit je einem 32-Byte-Eintrag: `ota_seq`
(u32), `seq_label[20]`, `ota_state` (u32), `crc` (u32). Der Bootloader nimmt
den höchsten gültigen `ota_seq`, der Slot ist `(ota_seq - 1) % 2`. Die
Prüfsumme ist `zlib.crc32(ota_seq_le, 0xFFFFFFFF)` — gegen die echte
`otadata` des Geräts verifiziert (`ota_seq=1` → `0x4743989A`).

## Ablauf

**Erst sichern.** Ein voller 4-MB-Dump ist der Rückweg für alles, auch für
das NVS mit den Keys:

```bash
esptool --port /dev/ttyACM0 --baud 921600 read-flash 0 0x400000 trackerd_full_4MB.bin
```

Bauen und nach `app1` flashen:

```bash
cd p2p && pio run
cd .. && ./switch_app.py flash
```

Umschalten, jederzeit, in beide Richtungen:

```bash
./switch_app.py lorawan     # bootet wieder app0
./switch_app.py p2p         # bootet app1
./switch_app.py status      # wer bootet gerade
```

Aus der P2P-Firmware heraus geht es auch ohne PC zurück: `AT+LORAWAN`.
Der umgekehrte Weg braucht `switch_app.py`, weil die Dragino-Firmware
nichts von `app1` weiß.

`pio run -t upload` ist **verboten** — das würde Partitionstabelle und
`app0` überschreiben. Deshalb flasht ausschließlich `switch_app.py`, und
zwar nur `0x1F0000` und `0xE000`.

Verifiziert: `app1` bootet mit `TrackerD-P2P v1.0`, `AT+LORAWAN` bringt
`TrackerD ,v1.4.8 / EU868 / EV_JOINING / TXMODE, freq=868300000, len=23,
SF=7, BW=125, CR=4/5` zurück, `./switch_app.py p2p` wieder P2P. Keys und
Konfiguration überstehen den Wechsel unbeschadet.

## Die P2P-Firmware

[`p2p/src/main.cpp`](p2p/src/main.cpp), 312 KB Image, 16 % von `app1`.
Konsole 115200 Baud. Die Konfiguration liegt **nur im RAM** und steht nach
jedem Start wieder auf den Defaults — bewusst so, damit diese Firmware
niemals ins NVS schreibt, in dem die LoRaWAN-Keys liegen.

| Befehl | Bedeutung | Default |
|---|---|---|
| `AT+FRE=868.125` | Frequenz in MHz (oder Hz) | 868125000 |
| `AT+SF=7` | Spreading Factor 6–12 | 7 |
| `AT+BW=125` | Bandbreite in kHz oder Hz | 125000 |
| `AT+CR=1` | Coding Rate 1–4 = 4/5–4/8 | 4/5 |
| `AT+POWER=17` | Sendeleistung dBm (PA_BOOST) | 17 |
| `AT+SYNCWORD=0x12` | 0x12 privat, 0x34 LoRaWAN | 0x12 |
| `AT+PREAMBLE=8` | Präambel-Symbole | 8 |
| `AT+CRC=1` | Payload-CRC | 1 |
| `AT+RX=1` | Dauerempfang an/aus | 1 |
| `AT+HEX=1` | Empfang zusätzlich als Hex | 0 |
| `AT+SEND=text` | Text senden | |
| `AT+SENDB=48656C6C6F` | Hex senden | |
| `AT+CFG` | alles zeigen | |
| `AT+LORAWAN` | zurück nach app0 und neu starten | |
| `ATZ` | Neustart | |

Empfang meldet sich als
`+RX: len=13 rssi=-42 snr=9.5 "E22TOTRACKERD"`. Ohne Argument liefert jeder
Setzbefehl den aktuellen Wert (`AT+SF=` → `7`).

Pinbelegung aus dem Dragino-Pinmapping: SCK 5, MISO 19, MOSI 27, NSS 18,
RST 23, DIO0 26; LEDs rot 15, blau 2, grün 13 (blau blinkt beim Senden,
grün beim Empfang).

## Offen: die Gegenstelle E22 schweigt

[`p2p_sweep.py`](p2p_sweep.py) dreht auf der TrackerD-Seite alle 18
Kombinationen aus SF 7–12 und BW 125/250/500 kHz durch und probiert beide
Richtungen gegen den EByte **E22-900T22U** auf Kanal 18 (868.125 MHz,
Air Rate 2.4k, transparent, Syncword 0x12). EByte gibt keine SF/BW heraus,
sondern nur eine „Air Rate" — im Handbuch steht dazu allein die Fußnote
„2.4kbps@SF11", ohne Bandbreite. Deshalb der Sweep statt einer Rechnung.

**Ergebnis: kein einziger Treffer, in keiner Richtung.** Derselbe E22 blieb
schon beim LA66 über alle sechs LoRaWAN-Datenraten stumm. Zwei
unterschiedliche Funkgegenstellen, gleiches Bild — der Verdacht liegt beim
E22, nicht beim TrackerD.

Was am TrackerD dagegen belegt ist: `LoRa.begin()` liest das
SX1276-Versionsregister erfolgreich, `endPacket()` kehrt zurück (TxDone
kommt also), und die LoRaWAN-Firmware in `app0` sendet auf derselben
Hardware sichtbar Join-Requests. Sender und SPI-Strecke arbeiten.

Nächster Schritt ist deshalb der E22: Taster länger als 1,5 s drücken, bis
die LED **rot** leuchtet (Konfigurationsmodus), dann

```bash
../../laptop/e22.py --port /dev/ttyUSB1 --read-product-info
```

Damit klärt sich, ob Kanal, Air Rate und serielle Rate die
[`AT+IAP`-Episode](../la66_p2p/README.md#gegenstelle-ebyte-e22) überlebt
haben. Solange das Modul im Übertragungsmodus steht, ist es nicht
auslesbar und der Sweep bleibt ohne Aussagekraft über die Luft.

## Ebyte-tauglich: gesendet wird auf beiden Profilen

Ab **v1.7** ist der TrackerD zugleich Knoten des Krisennetzes und Ebyte-Gerät.
Die beiden Netze lassen sich nicht vereinen, deshalb geht jede Nachricht
zweimal raus:

| | Rohkanal (DLOS8N, Brauneck) | Ebyte E90-DTU(900SL33) |
|---|---|---|
| Frequenz | 868.125 MHz | 868.125 MHz |
| SF / BW | SF7 / 125 kHz | **SF11 / 500 kHz** |
| LDRO | automatisch (0) | **1, erzwungen** |
| Syncword | 0x34 | **0x58** |
| Rahmen | `IIII>` + Nutzlast | Ebyte-Rahmen, siehe [EBYTE_E90.md](../pico_sx1262/EBYTE_E90.md) |

**Warum nicht ein gemeinsames Profil?** SF und Bandbreite ließen sich am
Gateway nachziehen (`chan_Lora_std` hat beides als Parameter), das **Syncword
nicht**: der SX1302 kennt nur einen Wert für den ganzen Chip, und dort nur 0x34
oder 0x12 — nie die 0x58, auf denen Ebyte ab Werk liegt
([RAWKANAL.md](../../gateway/RAWKANAL.md)). Doppelt senden ist deshalb kein
Umweg, sondern der einzige Weg, beide Gegenstellen zu erreichen.

```
AT+EBYTE=0    nur Rohkanal
AT+EBYTE=1    nur Ebyte
AT+EBYTE=2    beides (Vorgabe)
```

**Empfangen wird immer nur auf einem Profil** — der Funk kann zu einer Zeit nur
ein SF/BW/Syncword. Ab Werk lauscht er auf dem Ebyte-Profil.

## Der Alarmknopf

Bis v1.4 tat der Knopf in dieser Firmware **nichts**: es gab kein
`digitalRead`, gesendet wurde nur auf serielles Kommando. Seit v1.5 löst ein
Druck von **2 s** einen Alarm aus (`076C>ALARM`).

Pin und Polarität stammen aus Draginos `extiButtonLS`:

```c
#define BUTTON_PIN1 25
OneButton button1(BUTTON_PIN1, false, false);   // activeLow=false!
```

**GPIO 25, active high** — wer die übliche Active-Low-Taste annimmt, baut die
Logik verkehrt herum ein. Die 2000 ms sind Draginos `sys.exit_alarm_time`,
damit sich der Knopf in beiden Firmwares gleich anfühlt.

`AT+ALARM` löst denselben Alarm ohne Knopf aus, für Tests.
