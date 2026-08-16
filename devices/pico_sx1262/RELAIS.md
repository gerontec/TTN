# Relaisstelle Brauneck

Der Pico auf dem Brauneck verbindet das Lenggrieser Tal mit dem Feld und mit
dem Nachbartal Bad Heilbrunn. Firmware: `repeater.py` auf Basis von
`lora_p2p.py`.

```
   dell 192.168.5.23
        │ UDP 1702
        ▼
   DLOS8N Lenggries ──868.125 SF7 14dBm──►┐
                                          │
   TrackerD / Feld  ──868.125 SF7────────►│  Pico Brauneck (~1550 m)
                                          │  hört nur 868.125 SF7
                                          ├──868.125 SF7  14dBm──► DLOS8N Lenggries
                                          └──869.525 SF12 22dBm──► Bad Heilbrunn
```

## Warum getrennte Kanäle

Ein Relais braucht Ein- und Ausgangstrennung — wie jede Relaisfunkstelle, die
mit Ablage arbeitet. Bei LoRa gibt es dafür eine zweite, schärfere Achse:
**Spreizfaktoren sind quasi-orthogonal**, ein SF7-Empfänger demoduliert SF12
gar nicht.

Dazu der rechtliche Hebel, der bei gleicher Frequenz verschenkt wäre:

| | Eingang 868.125 | Ausgang 869.525 |
|---|---|---|
| Band | 868.0–868.6 (h1.3) | **869.4–869.65 (h1.7)** |
| Sendeleistung | 25 mW / 14 dBm | **500 mW / bis 22 dBm** |
| Sendezeit | 1 % | **10 %** |
| Spreizfaktor | SF7 | SF12 (≈14 dB empfindlicher) |

Zusammen rund **+8 dB Leistung, +14 dB Empfindlichkeit, zehnfaches
Zeitbudget**.

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

## Betrieb

```python
import repeater
repeater.run()                    # Dauerbetrieb
repeater.run(dauer_s=60)          # befristet, mit Bilanz
repeater.run(telemetrie=False)    # ohne Quittung ans Gateway
```

Für den unbeaufsichtigten Betrieb auf dem Berg gehört ein `main.py` auf das
Board, das `repeater.run()` aufruft — dann startet das Relais nach jedem
Stromausfall von selbst.
