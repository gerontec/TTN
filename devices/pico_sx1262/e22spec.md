# E22 — gemessene Spezifikation

Alles hier ist an der Luft gemessen, nicht aus einem Handbuch übernommen; wo
das Handbuch der Grund für eine Aussage ist, steht es dabei. Stand 19.08.2026.

Beteiligte Geräte: E22-900T am Notebook (`/dev/ttyUSB0`, Adresse `FFFF`),
zweites E22 (`/dev/ttyUSB1`, Adresse `2200`), Pico mit Waveshare SX1262
(`/dev/ttyACM0`, Adresse `0C2B`), DLOS8N-Gateway (`10.9.0.9`), dell-3660 mit
`lora_raw.py`.

---

## 1 Rahmenformat

```
 2c   KK   XX   YY   NN   ZH ZL   LL   Nutzlast …
 │    │    │    │    │    │       │    └─ jedes Byte XOR 0x12
 │    │    │    │    │    │       └────── Länge der Nutzlast
 │    │    │    │    │    └────────────── Zieladresse (nicht Absender!)
 │    │    │    │    └─────────────────── NETID
 │    │    │    └──────────────────────── YY = XX ^ 0xA1
 │    │    └───────────────────────────── XX = XOR(Nutzlast) ^ 0xA0
 │    └────────────────────────────────── Kanal (0x12 = 18 → 868.125 MHz)
 └─────────────────────────────────────── Magic
```

**Gegen den gesamten Bestand geprüft: 492 Rahmen, null Verstöße** — Magic,
Prüfpaar, Prüfsumme und Länge gehen jedes Mal auf:

```sql
SELECT COUNT(*) FROM lorachat WHERE rahmenformat='ebyte';
-- Prüfung siehe unten, Abschnitt 7
```

Daraus folgt zweierlei:

* **Es gibt keine versteckte CRC.** Die Gesamtlänge ist exakt `8 + LL`, kein
  Rahmen trägt einen Anhang. Geprüft wird nur das Prüfbytepaar — und die
  CRC der LoRa-PHY, die die Hardware macht.
* **Die Prüfsumme ist keine Sequenznummer.** Gleiche Nutzlast ergibt Byte für
  Byte denselben Rahmen; zwei Rahmen mit identischem Hex sind entweder eine
  Wiederholung oder eine Weitergabe, nie zwei verschiedene Nachrichten.

Die Adresse in Byte 5–6 ist das **Ziel**. Ein Absender steht nirgends im
Rahmen. Dass sie wie eine Absenderkennung wirkt, liegt daran, dass ein Modul
im Transparentmodus seine eigene Adresse ins Zielfeld schreibt — belegt an
`/dev/ttyUSB0` (Adresse `FFFF`, sendet `ziel=FFFF`) gegen `/dev/ttyUSB1`
(Adresse `2200`, sendet `ziel=2200`).

## 2 Funkprofil

| Größe | Wert | Woher |
|---|---|---|
| Frequenz | 868.125 MHz (Kanal 18) | 850.125 + CH, Handbuch 900SL |
| Modulation | SF11 / BW500 | gemessen, Luftrate „2.4k" |
| Coderate | 4/5 | gemessen |
| **LDRO** | **1** | gemessen — mit 0 rastet der Header ein, jede Nutzlast kommt mit CRC-Fehler |
| **Syncword** | **0x55** | gemessen; SX126x-Register 0x0740 liest `54 54` |
| CRC | an | gemessen |
| Header | explizit | gemessen |
| IQ | normal, nicht invertiert | gemessen |

Zum Syncword: `EBYTE_E90.md` nennt 0x58, aber dort war nur das obere Nibble
bestimmt — ein SX126x-Empfänger wertet nur das erste Registerbyte aus, der
Sweep traf deshalb auf 0x58…0x5F. Der SX1302 prüft **beide** Peak-Positionen
streng; ein Sweep über peak2 lieferte Pakete ausschließlich bei peak2 = 10,
also 0x55.

## 3 Quarzversatz

Der Frequenzversatz trennt die Sender zuverlässiger als jede Kennung im
Rahmen — er steht als `foff_hz` in der Datenbank:

| Sender | foff | Rahmen im Bestand |
|---|---|---|
| E22 A (`ttyUSB0`) | ≈ −32 000 Hz | 102 |
| E22 B (`ttyUSB1`) | ≈ −28 000 Hz | 78 |
| E90-Relais | ≈ 0 Hz | 179 |
| Pico SX1262 | ≈ +4 000 Hz | 30 |

Damit lässt sich ein Original von seiner Weitergabe unterscheiden, auch wenn
beide byteweise identisch sind: am 18.08. um 17:38:41 steht derselbe Rahmen
zweimal in der Tabelle, 221 ms auseinander, einmal mit −32 108 Hz und einmal
mit −177 Hz. Das ist eine Relaiskopie, keine zweite Nachricht.

## 4 Empfangsverhalten des E22 — offene Baustelle

Der E22 sendet zuverlässig (Pico hört ihn 3/3, das Gateway schreibt ihn seit
Tagen mit). **Umgekehrt kommt nur etwa jeder fünfte Rahmen an**, und zwar
unabhängig von allem, was sich am Sender einstellen lässt.

### Präambel (Pico → E22, 868.125 MHz, RSSI ≈ −42 dBm)

| Symbole | Dauer | Treffer |
|---|---|---|
| 8 | 33 ms | 3 / 30 |
| 12 | 49 ms | 0 / 4 |
| 16 | 66 ms | 2 / 9 |
| 20 | 82 ms | 5 / 30 |
| 24 | 98 ms | 5 / 27 |
| 32 | 131 ms | 0 / 5 |
| 48 | 197 ms | 1 / 5 |
| 64 | 262 ms | 0 / 2 |
| 128 | 524 ms | 0 / 2 |
| 600 | 2 460 ms | 0 / 2 |

Belastbar ist daran nur das Ende: **ab 64 Symbolen kommt gar nichts mehr an.**
Das deckt sich mit dem Befund vom 18.08., dass eine Präambel von 64 Symbolen
die Ebyte-Empfänger verstummen ließ. Der Unterschied zwischen 8 und 16–24
(10 % gegen 18 %) ist bei diesen Stückzahlen kein Beweis.

### Frequenz — kein Effekt

Verschränkt gemessen, je 10 Sendungen im Wechsel:

| Frequenz | Treffer |
|---|---|
| 868.106 MHz (−19 kHz, in Richtung des E22-Quarzversatzes) | 2 / 10 |
| 868.125 MHz (Nennfrequenz) | 3 / 10 |

Die Vermutung, man müsse den Quarzversatz des E22 vorhalten, ist damit
**widerlegt**. Bei BW500 ist der Empfänger gegen 30 kHz gleichgültig.

### Was ausgeschlossen ist

* **Versteckte CRC** — 492 Rahmen prüfen sauber durch, und unsere eigenen
  Rahmen sind mehrfach angekommen. Das Format wird akzeptiert.
* **Adressfilter** — gesendet wird NETID 00 an Rundruf `FFFF`; der Empfänger
  steht selbst auf `FFFF` (Monitoradresse, nimmt alles auf dem Kanal).
* **Verschlüsselung** (CRYPT_H/L) — bei gesetztem Schlüssel wären auch die
  eigenen Sendungen des Moduls unlesbar; sie dekodieren aber sauber mit
  XOR 0x12.
* **WOR-Weckzyklus** — ein Vorspann von 2,46 s, länger als der maximale
  WOR-Zyklus von 2 s, kommt **gar nicht** an (0/2). Wäre der Empfänger
  getaktet, müsste genau das durchgehen.

### Nächster Schritt

Die Register des Moduls lesen. Das ging bisher nicht, weil in
`e22_group_setup.py` die falsche Modus-Kombination steht:

| Modus | M1 | M0 | Bedeutung |
|---|---|---|---|
| 0 | 0 | 0 | Normal, UART und Funk offen, transparent |
| 1 | 0 | 1 | WOR |
| **2** | **1** | **0** | **Konfiguration — Register lesen und schreiben** |
| 3 | 1 | 1 | Deep Sleep |

Quelle: E22-900T30S User Manual, Abschnitt 6. Im Docstring von
`e22_group_setup.py` steht „M0 = 1, M1 = 1" für den Konfigurationsmodus —
das ist **Deep Sleep**. Deshalb kam über USB nie eine Registerantwort: das
Modul stand im Sendemodus und hat den Befehl `C1 00 09` stattdessen
**gefunkt** (nachgewiesen, 19.08. 07:13:17, als Rahmen
`2c1268c900ffff03d3121b` im Journal).

Mit `M1 = 1, M0 = 0` ließen sich WOR-Zustand, LBT, RSSI-Byte, Luftrate,
Adresse und Schlüssel auslesen — und damit vermutlich die 80 % Verlust
erklären.

## 5 Sendeseite des Gateways

Das DLOS8N kann das Ebyte-Profil senden, aber nur über die gepatchte HAL in
`/etc/lora/syncword.conf`:

```
service = 0x55        # RX-Syncword des chan_Lora_std
ldro    = 1           # RX-LDRO
tx      = 0x55        # TX-Syncword
tx_freq = 868125000   # nur Downlinks in diesem Fenster (+/- 5 kHz)
tx_ldro = 1           # TX-LDRO
```

Der Grund für das Fenster: `sx1302_send()` leitet das TX-Syncword aus
`lorawan_public` ab und schreibt es **pro Paket** neu — ohne die Patches ginge
jeder Downlink mit 0x34 hinaus. Und `SET_PPM_ON` schaltet LDRO nur bei BW125
mit SF11/12 und BW250 mit SF12 ein, bei BW500 also nie. Beides lässt sich im
`txpk`-JSON des Semtech-Protokolls **nicht** ausdrücken — es gibt kein Feld
dafür. Das Fenster hält die LoRaWAN-Downlinks auf RX1/RX2 davon frei.

**Gefundener Fehler (19.08.2026):** `tx_freq` stand auf `868097000`, während
`lora_raw.py` auf 868.125 MHz sendet — 28 kHz daneben, das ±5-kHz-Fenster griff
also nie, und jeder Rohkanal-Downlink ging mit 0x34/LDRO 0 hinaus. Der Wert
sah nach vorgehaltenem Quarzversatz aus, war aber auch in sich widersprüchlich:
das Fenster 868.092–868.102 hätte stattdessen die LoRaWAN-Downlinks auf
868.100 erwischt. Korrigiert auf `868125000`, Sicherung liegt als
`syncword.conf.vor-txfreq-fix` daneben.

Beleg für die Wirkung, gemessen mit dem Pico als unabhängigem Empfänger:

| Pico hört auf | vor dem Fix | nach dem Fix |
|---|---|---|
| 0x55 / LDRO 1 (Ebyte) | 0 / 3 | 2 / 3 |
| 0x34 / LDRO 0 (stock) | 2 / 3 | — |

## 6 Software-Fehler, die dabei aufgefallen sind

**`lora_p2p.py`, `airtime_ms`** — die Signatur lautet
`def airtime_ms(payload_len, …, preamble=PREAMBLE)`. Der Vorgabewert wird beim
Import gebunden, also auf 8 festgezurrt. `send()` rechnet daraus die
SX1262-Sendeschranke; wer `lora_p2p.PREAMBLE` zur Laufzeit hochsetzt, bekommt
eine zu kurze Schranke, und die Hardware bricht mitten im Senden ab (`TX 0
TIMEOUT` bei 600 Symbolen). Richtig wäre `preamble=None` mit Auflösung im
Rumpf.

**`e22_group_setup.py`, Docstring** — Konfigurationsmodus ist M1 = 1, M0 = 0,
nicht M0 = 1 / M1 = 1. Siehe Abschnitt 4.

## 7 Was davon in der Datenbank steht

`wagodb.lorachat` führt die Low-Level-Parameter als **virtuelle Spalten** über
`meta`. Virtuell heißt: kein Speicher, kein Schreibpfad, rückwirkend für den
gesamten Bestand gültig, und `meta` bleibt der unveränderte Rohbeleg.

Empfangsseitig, aus `rxpk` des Konzentrators:

```
freq  datr  sf  bw_khz  codr  modu  chan  rfch  rssi  rssi_signal  snr  crc
foff_hz  tmst_us  phy_bytes  netid  netid_hex  ziel  absender
rahmenformat  sprung  selbstempfang  fuer_uns  phy_hex
```

Sendeseitig, aus `lora/tx` — die eigenen Downlinks des Gateways, die vorher
nirgends standen:

```
syncword  ldro  praeambel  power_dbm
```

`netid_hex` gibt es zusätzlich zu `netid`, weil letzteres dezimal ist: `187`
ist `0xBB`. Diese Stolperstelle hat mehrfach den Eindruck erweckt, im
Datensatz stünden nur Adressen und keine NETID.

Indizes: `(netid, ziel)`, `foff_hz`, `(freq, datr)`.

Die Prüfung aus Abschnitt 1 als Skript:

```python
cur.execute("SELECT id, phy_hex FROM lorachat WHERE rahmenformat='ebyte'")
for rid, hexs in cur.fetchall():
    r = bytes.fromhex(hexs)
    assert r[0] == 0x2C and r[3] == r[2] ^ 0xA1
    nutz = bytes(b ^ 0x12 for b in r[8:8 + r[7]])
    x = 0
    for b in nutz:
        x ^= b
    assert r[2] == (x ^ 0xA0) & 0xFF
    assert len(r) == 8 + r[7]           # kein Anhang, keine versteckte CRC
```
