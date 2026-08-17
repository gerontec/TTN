# Relaisstelle Brauneck

Der Pico auf dem Brauneck verbindet das Lenggrieser Tal mit dem Feld und mit
dem Nachbartal Bad Heilbrunn. Firmware: `repeater.py` auf Basis von
`lora_p2p.py`.

```
   dell 192.168.5.23
        │ UDP 1702
        ▼
   DLOS8N Lenggries ──868.125 SF11 BW500──►┐
                                           │
   E22 / Feld       ──868.125 SF11 BW500──►│  Relais Brauneck (~1550 m)
                                           │  ein Kanal, ein Modul
                                           └──868.125 SF11 BW500──► DLOS8N Lenggries
```

## Ein Kanal, nicht zwei — und was das kostet

Hier stand bis zum 17.08.2026 ein Entwurf mit **zwei** Kanälen: Eingang auf
868.125, Ausgang auf 869.525 mit SF12. Der Reiz lag nicht in der Trennung an
sich, sondern im Frequenzband:

| | 868.0–868.6 (h1.3) | 869.4–869.65 (h1.7) |
|---|---|---|
| Sendeleistung | 25 mW / 14 dBm | **500 mW / bis 22 dBm** |
| Sendezeit | 1 % | **10 %** |

Zusammen rund +8 dB Leistung und das zehnfache Zeitbudget.

**Verworfen, weil er mit Ebyte nicht baubar ist.** Ein E90-DTU hat ein
Funkmodul und genau einen Kanal in `REG2`; die Luftrate legt SF und Bandbreite
gemeinsam fest. Ein Zweikanalrelais bräuchte ein zweites Modul. Im Code stand
er ohnehin nie: `out_freq` und `out_sf` lagen in `relais.json`, wurden aber von
keiner Zeile gelesen — nur `out_power` ist echt.

**Der Preis ist das Sendezeitbudget, und er ist messbar.** Bei SF11/BW500
dauert ein 16-Byte-Rahmen 144 ms; die 1-%-Regel sperrt danach rund 14 s. Ein
Lauf vom 17.08.2026 mit vier Broadcasts im Abstand von 3,5 s:

```
weiter: Ebyte, unveraendert  RSSI -23 SNR 8.3  144 ms
  verworfen: Sendezeitbudget, noch 11.0 s gesperrt
  verworfen: Sendezeitbudget, noch  7.5 s gesperrt
  verworfen: Sendezeitbudget, noch  4.0 s gesperrt
Bilanz: 4 gehoert, 1 weitergegeben, 3 unterdrueckt
```

Drei von vier fielen also nicht am Funk aus, sondern an der Rechtslage. Mit dem
früheren SF7/BW125 waren es 72 ms und rund 7 s Sperre — der Umstieg auf das
Ebyte-Profil hat das verdoppelt. **Wer den Krisenkanal auf Durchsatz auslegt,
muss hier ansetzen**, nicht an der Empfindlichkeit: Nutzlasten kürzen, seltener
senden, oder doch ein zweites Modul für 869.4–869.65.

## Eigenecho: zwei Richtungen, zwei Mechanismen

Der Pico hat **nur ein Funkmodul** und kann immer nur auf einem Kanal lauschen.
Das prägt den ganzen Entwurf.

**Talwärts (→ Bad Heilbrunn) physikalisch.** Ausgang und Eingang unterscheiden
sich in Frequenz *und* Spreizfaktor. Der Repeater ist für diese Aussendung
strukturell taub — es gibt keine Logik, die versagen könnte.

**Bergwärts (→ Lenggries) per Marker.** Dieser Uplink geht zwangsläufig auf
demselben Kanal hinaus, auf dem gelauscht wird. Während des Sendens ist der
Empfänger ohnehin taub; gegen Umwege über eine zweite Relaisstelle trägt jedes
weitergegebene Paket den Marker `R<sprung>>`. Was den Marker schon hat, wird
nicht erneut weitergegeben. Ein Dublettenspeicher hält denselben Inhalt
zusätzlich fünf Minuten zurück.

## Richtungsentscheidung

Gateway und TrackerD senden beide auf 868.125 SF7 — der Inhalt muss also sagen,
wohin es geht:

| Nutzlast beginnt mit | Bedeutung | Weitergabe |
|---|---|---|
| `L>` | kommt aus dem Tal Lenggries | 869.525 SF12, 22 dBm |
| `R<n>>` | schon weitergegeben | verworfen |
| alles Übrige | Uplink aus dem Feld (TrackerD) | 868.125 SF7, 14 dBm |

Praktisch heisst das: `lora_raw.py --send "L>…"` für Rundsprüche ins Nachbartal,
alles ohne Präfix wird nach Lenggries geleitet.

## Sendezeitbudget

Nach jeder Aussendung sperrt sich das jeweilige Band für
`Luftzeit × (100/Prozent − 1)` — die übliche konservative Auslegung. Bei SF12
und 30 B sind das 1647 ms Luftzeit und damit **14,8 s Sperre**; auf dem
Eingangsband bei SF7 und 1 % sind es 67 ms und **6,6 s**.

## Verifiziert

**Uplink, TrackerD → Lenggries.** Vollständig über die Luft, alles in einem Log
des Gateways:

```
11:32:40  Gateway sendet         "TRACKERD-POS 47.67 11.57"
11:32:41  Original, RSSI  -15    "TRACKERD-POS 47.67 11.57"
11:32:41  Relay,    RSSI -101    "R1>TRACKERD-POS 47.67 11.57"   <- vom Pico
```

Der Pico meldete dazu `1 gehoert, 1 weitergegeben, 0 unterdrueckt` — das
relayte Paket erscheint genau einmal, keine Schleife.

**Downlink, Lenggries → Bad Heilbrunn.**

```
11:34:01  Gateway sendet         "L>ALLE TALSPERRE OFFEN"
11:34:04  Quittung, RSSI -103    "R9>BRAUNECK 1/1 rssi-100"
```

Pico-Log: `weiter: -> Bad Heilbrunn ... 869.525 MHz SF12 22 dBm, 1483 ms`.
Die Quittung wird nur gesendet, wenn die SF12-Aussendung TxDone gemeldet hat —
sie ist damit der Nachweis, dass der lange Sprung tatsächlich hinausging. Das
DLOS8N kann 869.525 selbst nicht mithören (radio_1 sitzt auf 868.5 und reicht
±400 kHz), deshalb überhaupt die Quittung.

**Noch nicht verifiziert:** der Empfang in Bad Heilbrunn — dort steht noch kein
Gerät. Und der TrackerD stand bei diesen Messungen nicht zur Verfügung, seine
Rolle spielte das Gateway mit einem unmarkierten Paket.

## Gefundener Fehler: starre Sendezeitschranke

`send()` hatte eine fest verdrahtete `SetTx`-Schranke von 976 ms. Ein
SF12-Paket dauert 1483 ms — der Chip brach also **mitten im Senden** ab und
meldete Timeout. Bei SF7 (46 ms) war das nie aufgefallen.

Behoben: die Schranke wird jetzt aus der Luftzeit abgeleitet (`airtime × 3`),
wofür `set_modulation()` den aktuellen Spreizfaktor mitführt. Merksatz: jede
feste Zeitkonstante in einem LoRa-Treiber ist verdächtig, sobald der
Spreizfaktor variabel wird — zwischen SF7 und SF12 liegt Faktor 32.

## Zur Frage nach 30 dBm

Ebytes „10 km kein Problem" stimmt, aber die Begründung liegt nicht bei der
Leistung. Streckenrechnung für 10 km auf 869 MHz:

| Posten | Wert |
|---|---|
| 22 dBm + 2 dBi | +24 dBm |
| Freiraumdämpfung 10 km | −111 dB |
| Empfangsantenne | +2 dBi |
| **Empfangspegel** | **−85 dBm** |
| Empfindlichkeit SF12/BW125 | −137 dBm |
| **Reserve** | **≈ 52 dB** |

Selbst mit 14 dBm blieben 44 dB, selbst bei SF7 noch 38 dB. Die 8 dB, die
30 dBm zusätzlich brächten, sind gegenüber 52 dB Reserve bedeutungslos.
Entscheidend ist die **Sichtverbindung**, und die liefert der Bergstandort:
Brauneck ~1550 m gegen Lenggries ~680 m und Bad Heilbrunn ~640 m. Kritisch sind
Geländeabschattung, Antennenmontage und Polarisation — nicht das Watt.

Nebenbei: 30 dBm = 1 W wären in EU868 ohnehin nicht zulässig. Das Maximum ist
500 mW ERP im Band 869.4–869.65, und der SX1262 kann mit 22 dBm ≈ 158 mW
darunter bleiben.

## Stromversorgung: reiner Solarbetrieb

**Die Station hat keine Pufferbatterie.** Der Victron-Laderegler schaltet den
Verbraucher morgens schlagartig zu und abends wieder ab. Das prägt den Betrieb
stärker als jede Funkeinstellung:

**Jeder Morgen ist ein Kaltstart, und niemand ist oben.** Deshalb liegt ein
`main.py` auf dem Board, das `repeater.run()` startet, bei einem Fehler
wiederholt und notfalls `machine.reset()` auslöst, statt in den REPL zu fallen.
Ein Absturz darf die Station nicht bis zum nächsten Morgen stilllegen.

**Konfiguration wird sofort gesichert, nicht erst auf `SAVE`.** Eine per Funk
gesetzte Sendeleistung wäre sonst am nächsten Morgen wieder weg. `POWER`, `SF`,
`FREQ`, `RELAY` und `TELEM` schreiben deshalb unmittelbar nach `/relais.json`.
Nachgemessen: nach `C>POWER 17` steht dort
`{"relay_aktiv": true, "out_sf": 12, "out_freq": 869525000, "out_power": 17,
"telemetrie": true}`.

**Harte Abschaltung kann einen Flash-Schreibvorgang treffen.**
`fernwirk.konf_laden()` fängt eine beschädigte `/relais.json` ab und fällt auf
die Vorgaben zurück — die Station kommt dann mit Standardwerten hoch, aber sie
kommt hoch.

**Nachts ist die Kette unterbrochen.** Von Sonnenuntergang bis Sonnenaufgang
gibt es kein Relais und damit keine Verbindung ins Nachbartal. Das ist eine
Eigenschaft des Aufbaus, keine Störung — wer nachts Reichweite braucht, braucht
einen Akku.

Stromhunger als Anhaltspunkt: der RP2040 zieht bei 125 MHz rund 25 mA, der
SX1262 im Dauerempfang etwa 5 mA, im Sendemoment bei 22 dBm rund 118 mA. Der
Sendeanteil ist wegen des Sendezeitbudgets klein; **die Dauerlast bestimmt der
Prozessor** — deshalb der reduzierte Systemtakt.

### Systemtakt 48 MHz

125 MHz sind für diese Aufgabe sinnlos: Modulation, Timing und Preamble macht
der SX1262 selbst, der RP2040 schreibt nur Konfigurationsbytes über SPI und
wartet auf BUSY. Weniger Takt heißt weniger Strom, und weniger Strom heißt bei
einer Versorgung ohne Puffer weniger Spannungseinbruch unter Last — also eine
niedrigere Schwelle, ab der die Station überhaupt stabil läuft.

Abgetastet, jeweils mit Registerprobe und echter Aussendung:

| Takt | Ergebnis |
|---|---|
| 125 / 96 / 64 / 48 / 32 / 24 MHz | sauber, `DevErr 0x0000`, Syncword `3444`, TX ok |
| **18 MHz** | **SPI liefert Müll** — Syncword liest `a2a2`, TX schlägt fehl |
| 12 MHz | `machine.freq()` lehnt ab |

24 MHz lief in einer Nachprobe 6 von 6 sauber, liegt aber dicht an der Kante.
Gewählt sind **48 MHz** — reichlich Abstand zur Ausfallgrenze bei immer noch
gut halbiertem Prozessorstrom. Bei einer Station, an die man nur mit einer
Bergtour kommt, ist der Abstand mehr wert als die letzten Milliampere.

Der Takt wird **vor** dem Aufsetzen des Funkchips gestellt: `clk_peri` hängt am
Systemtakt, ein vorher erzeugtes SPI-Objekt hätte die falsche Teilung. Deshalb
setzt `run()` die Frequenz und verwirft ein bestehendes Radio-Objekt.

Der Takt ist bewusst **nicht** per Fernwirken änderbar — ein falscher Wert
würde die Station bis zum nächsten Sonnenaufgang unerreichbar machen.

Was die Taktsenkung kostet: die Software-Zeit um eine Aussendung herum wächst
von 47 ms bei 125 MHz auf 54 ms bei 48 MHz (gemessen, bei ~46 ms reiner
Luftzeit). Das ist Overhead im Bereich einzelner Millisekunden und für den
Betrieb bedeutungslos.

Nachgemessen bei 48 MHz, Fernwirken über die Luft:

```
gesendet: C>POWER 20
Antwort: POWER 20 dBm   (RSSI -90, SNR 14.0)
gesendet: C>STATUS
Antwort: auf0 ab0 unt0 31s an SF12 20dBm 869.525 tel1   (RSSI -89, SNR 13.2)
```

## Betrieb

```python
import repeater
repeater.run()                    # Dauerbetrieb (macht main.py automatisch)
repeater.run(dauer_s=60)          # befristet, mit Bilanz
repeater.run(telemetrie=False)    # ohne Quittung ans Gateway
```

## Fernwirken von 192.168.5.23 aus

Der Pico hat **kein WLAN** — es ist ein RP2040, kein Pico W; das Modul
`network` existiert nicht. Auf dem Berg gibt es also weder SSH noch OTA. Der
einzige Rückkanal ist der Funk, auf dem das Relais ohnehin arbeitet. Für ein
Krisensystem ist das der richtige Weg: er trägt genau dann, wenn alles andere
ausgefallen ist.

Bewusst **ohne Authentisierung** — wer in Funkreichweite ist, könnte das Relais
umstellen. Abwägung zugunsten der Einfachheit.

```sh
python3 /home/gh/python/lora_cmd.py POWER 17     # der Kernbefehl
python3 /home/gh/python/lora_cmd.py STATUS
python3 /home/gh/python/lora_cmd.py SF 9
python3 /home/gh/python/lora_cmd.py RELAY 0
python3 /home/gh/python/lora_cmd.py REBOOT
```

| Befehl | Wirkung |
|---|---|
| `POWER <2..22>` | Sendeleistung talwärts in dBm |
| `SF <7..12>` | Spreizfaktor talwärts |
| `FREQ <MHz>` | Sendefrequenz talwärts, 863…870 |
| `STATUS` | Zähler, Laufzeit, Konfiguration |
| `RELAY 0\|1` | Weitergabe aus/ein |
| `TELEM 0\|1` | Quittungen aus/ein |
| `SAVE` | Stand ausdrücklich sichern |
| `REBOOT` | Neustart des Boards |
| `PING` | lebt die Station? |

Rahmenformat ist schlichter Text: Befehl `C>POWER 20`, Antwort `A>POWER 20 dBm`.
Beides wird nie weitergegeben — Befehle werden verbraucht, Antworten ignoriert.

`lora-raw.service` hält UDP 1702 dauerhaft und kann als einziger senden. Er hat
deshalb einen **Steuereingang auf 127.0.0.1:1703**: was dort ankommt, wird beim
nächsten `PULL_DATA` des Gateways gefunkt. `lora_cmd.py` schickt den Befehl
dorthin und wartet über MQTT `lora/raw` auf die Antwort.

Nachgemessen von dell aus:

```
gesendet: C>POWER 17
Antwort: POWER 17 dBm   (RSSI -101, SNR 8.8)
```
