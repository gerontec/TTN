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
| `LA66_P2P_v1.2.4_application.bin` | `0x0800D000` | nur die App — **das Image der Wahl**, solange der Bootloader schon drauf ist |
| `LA66_P2P_v1.2.4_application_withbootloder.bin` | `0x08000000` | Bootloader **und** P2P-App, nur für den Tremo-Weg |
| `LA66_LoRaWAN_v1.3_EU868_with_bootloader.bin` | `0x08000000` | zurück auf LoRaWAN |

Das Flash-Layout steckt im Kombi-Image: die App beginnt exakt bei Offset
`0xD000`, der Bootloader belegt also `0x08000000`–`0x0800CFFF`.

## Zwei Flash-Wege — und welcher hier gilt

Draginos Wiki trennt in Abschnitt 1.10 sauber zwischen zwei Fällen, was man
leicht überliest:

* **1.10.2, Stick *ohne* Bootloader** — Tremo Programmer bzw. `tremo_loader.py`,
  BOOT-Pad auf RX brücken, RESET. Schreibt nach `0x08000000`. Der Weg dient
  ausdrücklich dazu, überhaupt erst einen Bootloader aufzuspielen.
* **1.10.1, Stick *mit* Bootloader** — **unser Fall**. Update läuft über die
  normale AT-UART, ohne jede Brücke, mit dem *Dragino Sensor Manager Utility*
  (Menüpunkt „UART Update Firmware"). Ziel ist `0x0800D000`, also die
  Applikation **ohne** Bootloader.

Erkennungsmerkmal laut Doku: „If a device has a bootloader, it will output
bootloader info to UART when boot." Unser Stick meldet bei jedem Boot
`Dragino OTA bootloader EU868 v1.3` — er hat also einen, und die BOOT↔RX-Brücke
ist der falsche Weg.

Gemessen am laufenden Gerät: Banner bei t≈0,2 s, dann **Stille bis t≈2,5 s**,
dann startet die Anwendung. In diesem Fenster wartet der Bootloader auf das
Utility. Auf rohe Tremo-Sync-Pakete (`0xFE 01 …`) antwortet er bei 9600, 115200
und 921600 Baud **nicht**, ebensowenig auf ASCII-Trigger wie CR/LF, `1`, `C`,
`0x7F`, `0x55` oder `0x18`. Deshalb läuft `tremo_loader.py` hier zwangsläufig in
`Connect failed: Read response header timeout`.

## Flashen unter Linux

Das Utility ist Windows-only, aber ein PyInstaller-Build (Python 3.7 + PyQt5).
Aus der dekompilierten Klasse `ThreadSerial1` lässt sich der UART-Weg exakt
ablesen; [`la66_uart_flash.py`](la66_uart_flash.py) ist die 1:1-Portierung
davon. Der Ablauf:

1. Port mit **9600 Baud** öffnen.
2. Abwechselnd **`123456\r\n`** und **`ATZ\r\n`** senden, dabei die Baudrate
   zwischen 9600 und 921600 wechseln, bis `Dragino OTA bootloader` im Banner
   auftaucht. Der Trigger `123456` ist der Punkt, den man ohne Blick in das
   Utility nicht errät.
3. **`AT+MOD=1`** — Sprung in den Programmiermodus, quittiert mit `OK`.
4. Auf **921600** wechseln, dann Sync.
5. Alle Tremo-Kommandos (`SYNC`/`ERASE`/`FLASH`/`VERIFY`/`REBOOT`) gehen **nicht**
   als Binärframes raus, sondern als ASCII-Hex in
   **`AT+TX=<len>,<HEXUPPER>\r\n`**, jeweils mit der festen UUID
   `6666666666666666`. Quittung ist das UUID-Echo in der Antwortzeile.
6. Nutzlast **224 Byte** je Paket, Ziel **`0x0800D000`**, am Ende CRC32-Verify
   und Reboot.

```bash
./la66_uart_flash.py firmware/LA66_P2P_v1.2.4_application.bin
```

Weder Brücke noch Reset-Taster noch Windows nötig. Realer Lauf:

```
Bootloader gefangen (2 Versuche)
Programmiermodus aktiv (AT+MOD=1)
Sync ok
Datei: LA66_P2P_v1.2.4_application.bin (37640 Bytes, CRC32 03F2777D)
Erase 0x0800D000 ...
Flash: 37640 / 37640 (100.0%)   Dauer: 5.0 s
Verify ok
```

Das Skript weigert sich, ein `*_withbootloder.bin` nach `0x0800D000` zu
schreiben — dieses Image gehört nach `0x08000000` und damit auf den
Tremo-Weg.

[`la66_flash.py`](la66_flash.py) und `tremo_loader.py` bleiben für genau diesen
Fall liegen: Stick ohne Bootloader oder Bootloader selbst erneuern, dann mit
BOOT↔RX-Brücke.

[`at.py`](at.py) ist die kleine AT-Konsole für beide Seiten
(LA66 9600, TrackerD 115200).

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
  Abfrageform; das `=?` wird als Kommando ausgeführt, quittiert mit `AT+IAP=OK`
  und wirft den Stick in den Firmware-Update-Modus. Schlimm ist das nicht:
  dort **schaltet er auf 115200 Baud um**, gibt Log aus und verlässt den Modus
  von selbst wieder. Wer weiter bei 9600 mitliest, sieht nur Zeichensalat und
  hält das Modul für tot. Das Datenblatt sagt dazu klar: „Do not use the
  `AT+IAP` command."
* EByte gibt statt SF/BW nur eine „Air Rate" her. 2.4k ist nach Datenblatt-Lesart
  SF10/BW125, verbürgt ist das nicht. Wenn nichts ankommt: auf der LA66-Seite
  `AT+SF` von 12 abwärts durchprobieren, der Rest der Parameter
  (BW 125 kHz, CR 4/5, explizit, CRC an, Präambel 8, Syncword privat) passt
  zur EByte-Voreinstellung.

## Gegenstelle TrackerD: Hörtest

[`hear_trackerd.py`](hear_trackerd.py) gleicht beide Seiten ab und lässt den
TrackerD senden, während die LA66-Konsole mitgeschrieben wird.

Eine Falle beim Abgleich: `AT+BW` nimmt beim LA66 nur einen **Index**
(`0` = 125 kHz), krumme Werte wie 62500 Hz gibt es dort nicht. Der TrackerD
kennt dagegen Hertz. Also zieht der TrackerD auf 125000 nach, nicht umgekehrt.
Und das LA66-Syncword `1` meldet sich als `0x3444 for Public Network` — das ist
die 16-Bit-Schreibweise des SX126x für LoRa-Syncword `0x34`, passt also zum
TrackerD.

Gemeinsame Einstellung: 868.125 MHz, SF7, BW 125 kHz, CR 4/5, Präambel 8,
CRC an, Syncword öffentlich.

```bash
./hear_trackerd.py --txtest 10
```

Ergebnis auf dem Tisch (beide Geräte nebeneinander):

```
+  8.61s  Data: (HEX:) 54 52 41 43 4b 45 52 44 54 52 41 43 4b 45 52 44 ...
+  8.61s  Rssi= -21
Ergebnis: GEHOERT
```

`54 52 41 43 4b 45 52 44` ist `TRACKERD`, das 32-Byte-Muster aus `AT+TXTEST`.
RSSI −21 bis −22 dBm über wenige Zentimeter, ein Paket rund alle 200 ms.
