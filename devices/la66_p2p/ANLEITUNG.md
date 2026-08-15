# Anleitung: LA66 USB-Stick auf P2P flashen

Kurzfassung zum Nachmachen. Hintergrund und Messwerte stehen in der
[README](README.md).

## Vorher klären: hat der Stick einen Bootloader?

Davon hängt der ganze Rest ab. Stick einstecken, dann:

```bash
./at.py 'ATZ' -w 4
```

* **Antwort enthält `Dragino OTA bootloader …`** → Bootloader vorhanden,
  weiter mit [Weg A](#weg-a-stick-mit-bootloader-der-normalfall). Das ist der
  Auslieferungszustand.
* **Kein Banner, nur die Anwendung** → [Weg B](#weg-b-stick-ohne-bootloader).

Kommt auf `ATZ` ein `AT_ERROR`, einfach nochmal — der Befehl wird gelegentlich
abgelehnt, wenn der Stick gerade in einem Empfangsfenster steht.

## Weg A: Stick mit Bootloader (der Normalfall)

Keine Brücke, kein Reset-Taster, kein Windows. Nur einstecken und:

```bash
cd devices/la66_p2p
./la66_uart_flash.py firmware/LA66_P2P_v1.2.4_application.bin
```

Braucht `pyserial`. Standard-Port ist `/dev/ttyUSB0`, sonst `-p` setzen.
Der Lauf dauert rund 5 Sekunden und sieht so aus:

```
Port /dev/ttyUSB0, Ziel 0x0800D000
  Warte auf den Bootloader (Trigger 123456 / ATZ) ...
  Bootloader gefangen (2 Versuche)
  Programmiermodus aktiv (AT+MOD=1)
  Sync ok
  Datei: … (37640 Bytes, CRC32 03F2777D)
  Erase 0x0800D000 ...
  Flash:  37640 / 37640 (100.0%)
  Verify ok

Neustart -- Ausgabe der neuen Firmware:
  | LA66 P2P Firmware v1.2.4
  | Syncword: 0x3444 for Public Network
  | Frequency: 868.700 MHZ , 868.700 MHZ
  …
```

**Wichtig:** Über diesen Weg nur die Applikation **ohne** Bootloader flashen
(`…_application.bin`, Ziel `0x0800D000`). Ein `…_withbootloder.bin` gehört nach
`0x08000000` und würde den Bootloader überschreiben, auf dem dieser Weg
aufsetzt — das Skript lehnt es deshalb ab.

Zurück auf LoRaWAN geht über diesen Weg nicht: die LoRaWAN-Datei liegt hier nur
als Kombi-Image mit Bootloader vor, dafür Weg B.

## Weg B: Stick ohne Bootloader

Nur nötig, wenn kein Bootloader drauf ist oder der Bootloader selbst erneuert
werden soll. Hier greift der ROM-Bootloader des ASR6601, und der will den
BOOT-Pin high sehen:

1. **BOOT-Pad mit dem RX-Pad brücken** — Draht ist zuverlässiger als eine lose
   aufgelegte Jumper-Kappe. RX ruht auf High und zieht BOOT mit hoch.
2. Stick **einstecken**. Bei Varianten mit RST-Taster: stecken, dann RST
   drücken, Brücke dabei liegen lassen.
3. Verbindung prüfen — das ist der dokumentierte Test:

   ```bash
   python3 tremo_loader.py --port /dev/ttyUSB0 read_sn
   ```

   Kommt `Connect failed: Read response header timeout`, ist der Stick **nicht**
   im Brennmodus: Brücke sitzt nicht, oder der Stick hängt an einem USB-Hub
   (Dragino: „If upgrade via USB hub is not successful, try to connect to PC
   directly.").
4. Flashen:

   ```bash
   python3 tremo_loader.py --port /dev/ttyUSB0 flash 0x08000000 \
       firmware/LA66_P2P_v1.2.4_application_withbootloder.bin
   ```

   Alternativ [`la66_flash.py`](la66_flash.py), das die Adresse am Dateinamen
   erkennt und die Baudrate selbst sucht.
5. Brücke **entfernen**, Stick aus- und wieder einstecken.

Zurück auf LoRaWAN mit demselben Weg:

```bash
python3 tremo_loader.py --port /dev/ttyUSB0 flash 0x08000000 \
    firmware/LA66_LoRaWAN_v1.3_EU868_with_bootloader.bin
```

## Danach: Funkparameter setzen

Ab Werk steht die P2P-Firmware auf 868.700 MHz und SF12. Für die Gegenstelle
TrackerD:

```bash
./at.py 'AT+FRE=868.125,868.125' 'AT+SF=7,7' 'AT+BW=0,0' \
        'AT+CR=1,1' 'AT+PREAMBLE=8,8' 'AT+CRC=1,1'
./at.py 'ATZ' -w 4          # AT+BW greift erst nach Reset
```

`AT+BW` nimmt nur einen **Index** (`0` = 125 kHz) — krumme Werte wie 62500 Hz
gibt es hier nicht, die muss die Gegenstelle nachziehen. `AT+SYNCWORD=1` meldet
sich als `0x3444`, das ist die 16-Bit-Schreibweise für LoRa-Syncword `0x34`
(öffentlich); `0` wäre `0x12` (privat).

Prüfen und hören:

```bash
./at.py 'AT+CFG'
./hear_trackerd.py --txtest 10
```

## Wenn etwas klemmt

| Symptom | Ursache |
|---|---|
| `could not open port /dev/ttyUSB0` | Stick nicht erkannt, oder eine VM hat ihn gefangen (`VBoxManage list usbhost` → `Captured`). Nach dem Freigeben bindet der `cp210x`-Treiber nicht immer von selbst neu: einmal abziehen und einstecken. |
| `Bootloader hat sich nicht gemeldet` | Anderer Prozess hält den Port offen, oder der Stick sitzt an einem Hub. |
| `tremo_loader.py` läuft in `Connect failed` | Normal, wenn der Stick **nicht** im Brennmodus ist. Bei Sticks mit Bootloader ist das der falsche Weg — nimm Weg A. |
| `AT_ERROR` auf `ATZ` | Empfangsfenster aktiv, einfach wiederholen. |
| Nach dem Flashen kein `AT`-Echo | Die P2P-Firmware antwortet auf nacktes `AT` nicht; `AT+CFG` oder `AT?` benutzen. |
