# Raspberry Pi Pico + Waveshare Pico-LoRa-SX1262

Rohes LoRa auf dem Rohkanal des DLOS8N. Gegenstelle ist `dell/lora_raw.py`,
Kanalaufbau steht in [gateway/RAWKANAL.md](../../gateway/RAWKANAL.md).

| | |
|---|---|
| Board | Raspberry Pi Pico (RP2040), MicroPython **1.28.0** (20260406) |
| Serial | `e6626005a75d0c2b`, `/dev/ttyACM0` (USB-ID `2e8a:0005`) |
| Funkmodul | Waveshare Pico-LoRa-SX1262, Semtech SX1262 mit TCXO |
| Kanal | 868.125 MHz, SF7, BW125, CR 4/5, Preamble 8, CRC an, Syncword **0x34** |

## Verdrahtung

| Signal | Pico |
|---|---|
| SCK | GP10 |
| MOSI | GP11 |
| MISO | GP12 |
| NSS / CS | GP3 |
| BUSY | GP2 |
| RESET | GP15 |
| DIO1 | GP20 |

Nur **SPI1** kann diese Pins bedienen, SPI0 nicht.

## Vier Fallen, alle nachgemessen

**1. SPI-Mode 0, nicht 3.** Das auf dem Board vorgefundene `readlorarf` benutzte
`polarity=1, phase=1`. Der SX1262 will CPOL 0 / CPHA 0. (Dasselbe Skript schob
die Nutzlast ausserdem ohne `WriteBuffer`-Opcode und ohne `SetTx` auf den Bus,
konnte also nie gesendet haben.)

**2. TCXO an DIO3.** Ohne `SetDIO3AsTCXOCtrl` meldet `GetDeviceErrors` **0x0020**
(XOSC_START_ERR), der Oszillator läuft nicht. Gemessen über alle acht
Spannungsstufen — jede ab 1.6 V räumt den Fehler ab, genommen wird der
Semtech-Referenzwert **1.8 V** mit 5 ms Anlaufzeit.

```
TCXO 1.6V (0x00): DeviceErrors 0x0000  OK
...
TCXO 3.3V (0x07): DeviceErrors 0x0000  OK
```

**3. DIO2 steuert den Antennenschalter.** Ohne `SetDIO2AsRfSwitchCtrl(1)`
sendet der Chip zwar und meldet TxDone, aber nichts erreicht die Antenne.

**4. Das Syncword steht als 0x3444 in den Registern.** `0x34` wird nicht als
`34 00` geschrieben, sondern die Nibbles werden auf `0x34,0x44` gespreizt
(privat `0x12` entsprechend `0x14,0x24` — das ist der Werkswert, den die
Register nach dem Reset zeigen). Kontrolle:

```python
r.rdreg(0x0740, 2)   # -> 34 44
```

Das ist der Punkt, an dem der Gateway-Empfang hängt: der SX1302 kennt nur ein
Syncword für den ganzen Chip (`lorawan_public: true` = 0x34). Ein Node auf dem
Werkswert 0x12 wird nicht gehört.

## Antwortpuffer richtig indizieren

`cmd()` schneidet die gesendeten Bytes ab, die Antwort beginnt also bei Index 0
des Rückgabewerts. Für `GetRxBufferStatus` heisst das `st[0]` = Länge,
`st[1]` = Startzeiger — nicht `st[1]`/`st[2]`. Gegenprobe: `GetRssiInst` liefert
mit derselben Indizierung einen plausiblen Rauschflur von −113 dBm, was für
BW125 (thermisch ≈ −117 dBm) stimmt.

## Benutzung

```python
import lora_p2p
lora_p2p.send("hallo")        # einmal senden
lora_p2p.beacon()             # alle 30 s ein Paket
lora_p2p.listen()             # empfangen
lora_p2p.airtime_ms(20)       # 56.6 ms bei SF7/BW125
```

Duty Cycle: 868.0–868.6 MHz erlaubt **1 %** bei 25 mW ERP (14 dBm). Bei ~57 ms
Luftzeit wären 6 s Abstand das Minimum; `beacon()` nimmt 30 s.

Vom Rechner aus:

```sh
mpremote connect /dev/ttyACM0 cp lora_p2p.py :lora_p2p.py
mpremote connect /dev/ttyACM0 exec "import lora_p2p; lora_p2p.beacon()"
```

## Welcher Frequenzbereich? Nicht auslesbar — nur messbar

**Es gibt kein Register, das den Frequenzbereich meldet.** Der SX126x-Chip
selbst deckt 150–960 MHz ab; was den nutzbaren Bereich real begrenzt, sind
Anpassnetzwerk, PA-Filter und Antenne des Moduls — Hardware, die über SPI nicht
sichtbar ist. Drei Messungen kommen der Frage am nächsten:

**Chip-Kennung, Register 0x0320 (16 Byte):**

```
53 58 31 32 36 31 20 56 32 44 20 32 44 30 32 00   ->  "SX1261 V2D 2D02"
```

Das Board wird als SX1262 verkauft, das Register sagt SX1261. Aufgelöst durch
Messung: derselbe Sollwert von 14 dBm einmal mit HP-PA (`deviceSel=0x00`,
`paDutyCycle=0x02`, `hpMax=0x02`) und einmal mit LP-PA (`deviceSel=0x01`,
`paDutyCycle=0x04`, `hpMax=0x00`) gesendet.

| PA-Konfiguration | am Gateway angekommen |
|---|---|
| SX1262 / HP-PA | **3 von 3** (RSSI −90, −102, −94) |
| SX1261 / LP-PA | **0 von 3** |

Das Modul ist also real ein SX1262; die Zeichenkette benennt die IP-Kernfamilie,
nicht die Verkaufsbezeichnung. `deviceSel=0x00` bleibt richtig.

**PLL-Rastbereich — untauglich als Bandindikator.** `SetFs` gefolgt von
`GetDeviceErrors` meldet über 100 bis 1100 MHz in 25-MHz-Schritten durchgehend
`0x0000`, also nie `PLL_LOCK_ERR`. Der Test grenzt nichts ein.

**Rauschflur über der Frequenz (RX-only, 28 Stützstellen).** Wo Anpassung und
Filter durchlassen, kommt mehr Umgebungsrauschen an:

```
  434 MHz  -116        700 MHz  -111        868 MHz  -106 (Max -97)
  470 MHz  -117        750 MHz   -94        875 MHz  -102
  550 MHz  -116        800 MHz   -85        928 MHz   -99
  600 MHz  -116        830 MHz  -103        950 MHz  -111
```

Deutlich zu sehen: unterhalb ~700 MHz sitzt alles auf dem Rauschflur (434 und
470 MHz bei −116/−117 dBm), ab 750 MHz kommt kräftig etwas durch. Das passt zu
einem auf 860–930 MHz abgestimmten Frontend.

**Aber Vorsicht bei der Deutung:** die Spitzen sind Umgebungssender, nicht die
Filterkurve. −85 dBm bei 800 MHz ist LTE-Band 20 (791–821 MHz), 750 MHz das
700er-Band, 928 MHz der GSM-900-Downlink. Gemessen wird also das Produkt aus
Frontend-Durchlass **und** dem, was zufällig in der Luft liegt — eine echte
Durchlasskurve bräuchte einen Wobbelsender. Belastbar ist nur die Aussage: unter
700 MHz kommt nichts durch, im 860-MHz-Band arbeitet das Modul nachweislich.

## Stand: läuft, Antenne war die Ursache

Verifiziert:

- Chip antwortet, Register-Roundtrip (`0xA5` geschrieben und gelesen)
- `GetDeviceErrors` nach `begin()` = **0x0000**
- Syncword-Register = **34 44**
- `SetPacketType` liest als LoRa (`01`) zurück
- Senden meldet **TxDone**, Luftzeit rechnerisch 46 ms für 13 Byte
- Empfänger auf dem Rauschflur bei **−113 dBm**, also kalibriert und lebendig

**Die Strecke steht.** Nach dem Anschrauben der Antenne kommen die Pakete am
Gateway an und laufen durch die ganze Kette bis `lora_raw.py` auf dell:

```
868.125 MHz  SF7BW125  ch8  RSSI -94  SNR 12.2  CRC ok  12B  "PICO-MP128-0"
```

Verbindungsgüte, gemessen mit acht Paketen im Abstand von 7 s:
**7 von 8 angekommen**, RSSI überwiegend −94 dBm bei SNR ~12, einzelne
Ausreisser bis −106 dBm / SNR 5. Für einen Krisenkanal heisst das: die Strecke
trägt, hat aber keine üppige Reserve — Wiederholungen einplanen.

### Vorher: wie die fehlende Antenne gefunden wurde

Der Fehler war von der Konfiguration nicht zu unterscheiden — der Chip meldete
brav TxDone, nur kam nichts an. Entschieden hat eine Messung: der Pico blieb
30 s auf Dauerempfang und pollte `GetRssiInst`, während das Gateway dreimal mit
14 dBm auf exakt 868.125 MHz sendete. Ergebnis: **1444 Proben, min −114,0 /
max −112,0 dBm** — brettflach, keine Auslenkung. Ein Sender dieser Stärke im
selben Gebäude müsste den Pegel um Dutzende dB hochreissen.

Dass der Kanal selbst trug, war getrennt bewiesen: das Gateway empfing seine
eigene Aussendung auf dem Rohkanal mit RSSI −16 und CRC ok. Damit blieb nur die
mechanische Erklärung.

Merksatz: bei stiller Strecke zuerst `GetRssiInst` im RX-Dauerbetrieb gegen
einen bekannten Sender halten. Das trennt Antenne/Frontend von Demodulation in
einer Messung, während TxDone darüber nichts aussagt.

## MicroPython aktualisieren

Stand 16.08.2026 ist **v1.28.0** (`RPI_PICO-20260406-v1.28.0.uf2`) aktuell.

```sh
mpremote connect /dev/ttyACM0 cp :lora_p2p.py ./sicherung.py    # erst sichern
mpremote connect /dev/ttyACM0 exec "import machine; machine.bootloader()"
# Board meldet sich als Massenspeicher RPI-RP2 und mountet automatisch
cp RPI_PICO-20260406-v1.28.0.uf2 /media/$USER/RPI-RP2/ && sync
```

Der `machine.bootloader()`-Aufruf bricht mpremote mit `OSError: [Errno 5]` ab —
das ist erwartet, das Gerät trennt sich mitten im Befehl. Der BOOTSEL-Knopf wird
nicht gebraucht.

**Das Dateisystem überlebt den Flash**: nach dem Sprung von 1.21.0 auf 1.28.0
lagen `lora_p2p.py` und `readlorarf` unverändert da (`_mpy` wechselt von 4358 auf
4870). Trotzdem vorher sichern — die Flash-Aufteilung ist keine Zusage.
