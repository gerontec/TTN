# Raspberry Pi Pico + Waveshare Pico-LoRa-SX1262

Rohes LoRa auf dem Rohkanal des DLOS8N. Gegenstelle ist `dell/lora_raw.py`,
Kanalaufbau steht in [gateway/RAWKANAL.md](../../gateway/RAWKANAL.md).

| | |
|---|---|
| Board | Raspberry Pi Pico (RP2040), MicroPython 1.21.0 |
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

## Stand: Elektronik läuft, Antenne fehlt

Verifiziert:

- Chip antwortet, Register-Roundtrip (`0xA5` geschrieben und gelesen)
- `GetDeviceErrors` nach `begin()` = **0x0000**
- Syncword-Register = **34 44**
- `SetPacketType` liest als LoRa (`01`) zurück
- Senden meldet **TxDone**, Luftzeit rechnerisch 46 ms für 13 Byte
- Empfänger auf dem Rauschflur bei **−113 dBm**, also kalibriert und lebendig

**Aber es geht keine HF über die Luft.** Das Gateway hörte in einer Serie von
sechs Paketen nichts (`rxnb:0`), und umgekehrt sah der Pico bei 1444 RSSI-Proben
über 30 s einen bretteben flachen Rauschflur (min −114,0 / max −112,0 dBm),
während das Gateway dreimal mit 14 dBm auf exakt 868.125 MHz sendete. Ein
Sender dieser Stärke im selben Gebäude müsste den Pegel um Dutzende dB
hochreissen.

Dass der Kanal selbst funktioniert, ist getrennt bewiesen: das Gateway empfing
seine eigene Aussendung auf dem Rohkanal mit RSSI −16, CRC ok, Nutzlast
`"GATEWAY-AN-PICO"` — über die Luft, durch die ganze Kette bis `lora_raw.py`.

Damit bleibt genau eine Erklärung: **am SX1262-Modul hängt keine (oder keine
860-MHz-)Antenne.** Zu prüfen ist der SMA/IPEX-Anschluss auf dem HAT. Ohne
Antenne ist der Chip zudem beim Senden mit voller Leistung gefährdet.

Sobald die Antenne dran ist, genügt zum Nachweis:

```sh
mpremote connect /dev/ttyACM0 exec "import lora_p2p; lora_p2p.send('PICO-TEST')"
ssh gh@192.168.5.23 'journalctl -u lora-raw.service -f'
```
