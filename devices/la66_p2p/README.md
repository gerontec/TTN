# LA66 USB-Stick auf LoRa P2P umbauen

Der Dragino **LA66 USB LoRaWAN Adapter** (am Notebook `/dev/ttyUSB0`,
CP2102) soll rohes LoRa sprechen statt LoRaWAN — für den Krisenkanal ohne
Gateway und ohne Netzserver. Dafür muss die Firmware getauscht werden: die
LoRaWAN-AT-Firmware kann kein P2P.

Stand **15.08.2026**.

## Woher die Firmware kommt

Nicht von GitHub. [github.com/dragino/LA66](https://github.com/dragino/LA66)
enthält nur den Quellcode der LoRaWAN-AT-Firmware
(`Projects/Applications/DRAGINO-LRWAN-AT`) plus Python-Beispiele — kein P2P,
kein fertiges Binary. Die P2P-Images liegen ausschließlich in Draginos
Dropbox:

* P2P-Ordner: <https://www.dropbox.com/sh/dq03kkfdrqnhy66/AACpHIcKYMa4o1IySKtVoeENa>
* Sammelordner LA66 (LoRaWAN + P2P + LBT): <https://www.dropbox.com/sh/g99v0fxcltn9r1y/AABJQUWNgt61Z567OcUf-sIya/LA66%20LoRaWAN%20module/Firmware>
* Anleitung: <https://wiki.dragino.com/docs/LoRaWAN-General-Configuration/instruction-for-la66-peer-to-peer-firmware/>

Beides liegt hier unter [`firmware/`](firmware/) gespiegelt, inklusive der
LoRaWAN-Firmware **v1.3 EU868 mit Bootloader** als Rückweg.

| Datei | Adresse | Inhalt |
|---|---|---|
| `LA66_P2P_v1.2.4_application_withbootloder.bin` | `0x08000000` | Bootloader **und** P2P-App — das Image der Wahl |
| `LA66_P2P_v1.2.4_application.bin` | `0x0800D000` | nur die App, setzt vorhandenen Bootloader voraus |
| `LA66_LoRaWAN_v1.3_EU868_with_bootloader.bin` | `0x08000000` | zurück auf LoRaWAN |

Das Flash-Layout steckt im Kombi-Image: die App beginnt exakt bei Offset
`0xD000`, der Bootloader belegt also `0x08000000`–`0x0800CFFF`.

## Der Stolperstein: BOOT muss auf RX

Der Stick trägt einen **Dragino-OTA-Bootloader** (meldet sich nach `ATZ` mit
`Dragino OTA bootloader EU868 v1.3`). Der ist für Updates über LoRaWAN-Downlink
da und springt sofort weiter in die Anwendung — er nimmt über UART **kein**
Firmware-Image an. Gemessen: zwischen Bootloader-Banner und `Dragino LA66
Device` liegt kein Sync-Fenster, egal bei welcher Baudrate.

`tremo_loader.py` von Dragino wackelt in `hw_reset()` an DTR (BOOT) und RTS
(RESET). **Beim USB-Adapter sind diese Leitungen nicht verdrahtet** — Pulse auf
DTR und RTS lösen nachweislich keinen Reset aus (kein Banner). Der Loader läuft
deshalb in `Connect failed: Read response header timeout`.

Bleibt der ROM-Bootloader des ASR6601, und der wird nur über den BOOT-Pin
betreten:

1. **BOOT-Pad mit dem RX-Pad brücken** (Jumper-Kappe oder Dupont-Draht).
   RX liegt im Ruhezustand auf High, zieht BOOT also mit hoch.
2. Stick **einstecken** (bei Varianten mit Reset-Taster: stecken, dann RESET
   drücken). Er ist jetzt im Brennmodus und meldet sich nicht mehr mit `AT`.
3. Flashen (siehe unten).
4. Brücke **entfernen**, Stick aus- und wieder einstecken.

## Flashen unter Linux

Kein Tremo Programmer nötig, der ist Windows-only.
[`la66_flash.py`](la66_flash.py) sucht den ROM-Bootloader selbstständig bei
921600, 9600 und 115200 Baud, wählt die Flash-Adresse anhand des Dateinamens
und prüft am Ende per CRC32:

```bash
./la66_flash.py firmware/LA66_P2P_v1.2.4_application_withbootloder.bin
./la66_flash.py -p /dev/ttyUSB0 -a 0x0800D000 firmware/LA66_P2P_v1.2.4_application.bin
```

Zurück auf LoRaWAN:

```bash
./la66_flash.py firmware/LA66_LoRaWAN_v1.3_EU868_with_bootloader.bin
```

`tremo_loader.py` liegt unverändert daneben, `la66_flash.py` benutzt es als
Bibliothek.

Die LoRaWAN-Konfiguration des Sticks vor dem Umbau steht in
[`la66_lorawan_v1.3_cfg.txt`](la66_lorawan_v1.3_cfg.txt) — Keys entfernt,
DevEUI `A8 40 41 17 F1 89 62 E0`, ABP, DevAddr `018962E0`, Class C.
Flashen löscht die Keys, für den Rückweg müssen sie aus ChirpStack neu
gesetzt werden.

## AT-Befehle der P2P-Firmware

Nach dem Flashen spricht der Stick weiter 9600 Baud, aber ein anderes
Kommando-Set:

| Befehl | Bedeutung | Beispiel |
|---|---|---|
| `AT+FRE` | TX-/RX-Frequenz in MHz | `AT+FRE=868.125,868.125` |
| `AT+SF` | Spreading Factor TX,RX (5–12) | `AT+SF=10,10` |
| `AT+BW` | Bandbreite TX,RX (0 = 125 kHz) | `AT+BW=0,0` |
| `AT+CR` | Coding Rate (1 = 4/5 … 4 = 4/8) | `AT+CR=1,1` |
| `AT+POWER` | Sendeleistung 0–22 dBm | `AT+POWER=22` |
| `AT+CRC` | CRC aus/ein | `AT+CRC=1,1` |
| `AT+HEADER` | 0 = explizit, 1 = implizit | `AT+HEADER=0,0` |
| `AT+IQ` | 0 = normal, 1 = invertiert | `AT+IQ=0,0` |
| `AT+PREAMBLE` | Präambel-Länge | `AT+PREAMBLE=8,8` |
| `AT+SYNCWORD` | 0 = privat, 1 = öffentlich | `AT+SYNCWORD=0` |
| `AT+GROUPMOD` | Gruppen-Byte TX,RX (0 = alles annehmen) | `AT+GROUPMOD=0,0` |
| `AT+RXMOD` | RX-Fenster in s, Antwortmodus | `AT+RXMOD=65535,0` |
| `AT+SEND` | Senden: Format, Daten, ACK, Wiederholungen | `AT+SEND=1,hallo,0,1` |
| `AT+RECV` | letzte Nachricht zeigen (0 = hex, 1 = Text) | `AT+RECV=1` |
| `AT+RXDAFORM` | Ausgabeformat empfangener Daten | `AT+RXDAFORM=1` |
| `AT+CFG` | alles anzeigen | `AT+CFG` |

`AT+RXMOD=65535,0` ist das Dauerlauschen ohne Auto-ACK. Jedes P2P-Paket trägt
ein führendes Gruppen-Byte, die Nutzlast passt bei SF12 in 59, bei SF9 in 123
und bei SF7 in 230 Byte.

## Gegenstelle EByte E22

Am zweiten Port (`/dev/ttyUSB1`, CH340) hängt ein **E22-900T22U** (per
`AT+DEVTYPE=?` ausgelesen, Firmware `7434-2-11`; Frequenz = 850.125 MHz +
Kanal). Für den Test gegen den LA66 mit
[`../../laptop/e22.py`](../../laptop/e22.py) gesetzt:

```bash
./e22.py --port /dev/ttyUSB1 --channel 18 --air-rate 2.4k --baud-rate 9600 \
         --parity 8N1 --power 22dBm --fixed-transmission 0 \
         --relay-function 0 --lbt-enable 0 --rssi-enable 1
```

Ergebnis `FF FF 00 62 E2 12 00 00 00` — **868.125 MHz**, 2.4 kbps, transparent,
22 dBm, LBT aus. Auf der LA66-Seite entspricht das `AT+FRE=868.125,868.125`.

Zwei Punkte, die den Test noch kosten können:

* Der E22 antwortet auf `C1`-Kommandos nur im **Konfigurationsmodus**. Der
  T22U-Stick schaltet den Modus über seinen **Taster**: länger als 1,5 s
  drücken, loslassen. Die LED sagt, wo er steht — **rot = Konfiguration,
  grün = Übertragung** (grün blinkend: Daten laufen). Per Kommando geht das
  bei Firmware `7434-2-11` nicht: `AT+SWITCH` und `AT+MODE` gibt es erst ab
  `7453-0-2x`, dieser Stand antwortet darauf mit `FF FF FF`.
* **Finger weg von `AT+IAP`** — auch von `AT+IAP=?`. Das Kommando kennt keine
  Abfrageform, es wirft den Stick sofort in den Firmware-Update-Modus, in dem
  er nur noch Müll antwortet. Ein USB-Reset holt ihn da nicht heraus, nur
  Ausstecken und wieder Einstecken.
* EByte gibt statt SF/BW nur eine „Air Rate" her. 2.4k ist nach Datenblatt-Lesart
  SF10/BW125, verbürgt ist das nicht. Wenn nichts ankommt: auf der LA66-Seite
  `AT+SF` von 12 abwärts durchprobieren, der Rest der Parameter
  (BW 125 kHz, CR 4/5, explizit, CRC an, Präambel 8, Syncword privat) passt
  zur EByte-Voreinstellung.
