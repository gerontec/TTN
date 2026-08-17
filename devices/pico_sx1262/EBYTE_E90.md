# Pico ↔ Ebyte E90-DTU

Stand **16.08.2026**. Es sind **zwei verschiedene Geräte** im Spiel, die man
nicht verwechseln darf:

| | E90-DTU(400SL30)E | E90-DTU(900SL33) |
|---|---|---|
| Band | 410.125–493.125 MHz | 850.125–930.125 MHz |
| Anschluss | Ethernet, `192.168.4.101` | RS-232 (DB-9) / RS-485 |
| Sendet auf | 433.125 MHz (Kanal 23) | **868.125 MHz** (Kanal 18) |
| Modulation | SF7/BW500, LDRO 1 | **SF11/BW500, LDRO 1** |
| Konfiguration | HTTP-JSON + UDP-AT | E22-Register über RS-232 |
| Empfang am Pico | −78 dBm | **−12 dBm** |
| Modul auf dem Pico | `ebyte433.py` | `ebyte868.py` |
| Stand | beide Richtungen verifiziert | **beide Richtungen verifiziert** |

Der 900er ist die interessantere Gegenstelle: er sitzt mit 868.125 MHz genau
dort, wo das Waveshare-Board angepasst ist. Der Unterschied ist drastisch —
−12 dBm gegenüber −78 dBm beim 400er, und das bei geringerer Sendeleistung.

Ein älteres Gerät derselben 900er-Reihe sprach statt der E22-Register das
**E32-Protokoll** (6-Byte-Rahmen, jede `C1`-Anfrage liefert dieselbe Antwort).
Beides kommt vor; siehe den Abschnitt zur RS-232-Seite.

Beide Strecken haben mit dem DLOS8N-Rohkanal nichts zu tun. Die
Brauneck-Firmware (`repeater.py`, 868.125 MHz, Syncword 0x34) bleibt unberührt
— auch wenn der 900er zufällig auf derselben Frequenz sitzt.

## Werks-Syncwords

Ebyte-Module lassen das LoRa-Syncword **nicht konfigurieren**; es ist ab Werk
festgelegt und taucht in keinem Handbuch auf. Beide Werte hier sind an der Luft
ausgemessen, indem der Empfänger den Syncword-Raum absucht und `HeaderValid`
als Kriterium nimmt.

| Gerät | Syncword | Register `0x0740` | Status |
|---|---|---|---|
| E90-DTU(400SL30)E | **0x55** | `54 54` | Empfang verifiziert |
| E90-DTU(900SL33) | **0x55** | `54 54` | Empfang verifiziert |
| E22-900T (USB) | **0x55** | `54 54` | am SX1302 ausgemessen, 17.08.2026 |

**Der Wert ist bei beiden Familien derselbe** — 400 MHz wie 868 MHz, zwei
verschiedene Gehäuse, zwei verschiedene Konfigurationsprotokolle. `0x55` ist
damit als Ebyte-Werkswert anzusehen und nicht als Eigenschaft eines Modells.

> **Korrektur 17.08.2026: 0x58 → 0x55.** Hier stand vorher 0x58. Das war nur
> das *obere* Nibble: ein SX126x-Empfänger wertet allein das erste
> Syncword-Registerbyte `0x54` aus, weshalb der Sweep unten auf allen acht
> Werten 0x58–0x5F traf und 0x58 stellvertretend notiert wurde. Das untere
> Nibble blieb damit offen.
>
> Der SX1302 im DLOS8N prüft **beide** Peak-Positionen streng und konnte es
> deshalb auflösen: ein Live-Sweep von `peak2` über `/dev/spidev1.0` bei
> laufendem Forwarder (`gateway/sx1302_syncword/sx1302_poke.c`) lieferte Pakete
> ausschließlich bei `peak2 = 10`, also **0x55**. Gegenprobe: bei 0x58
> (`peak2 = 16`) empfängt das Gateway nichts.
>
> Für den Pico ändert das nichts — er hört mit 0x58 wie mit 0x55, weil er das
> zweite Byte ohnehin ignoriert. Für jeden SX1302-Empfänger ändert es alles.

Weder `0x12` (privat) noch `0x34` (öffentlich) trifft zu — die naheliegende
Annahme ist falsch, und beide wurden gemessen ausgeschlossen.

**Eine Falle beim Absuchen.** `set_syncword(sw)` in `lora_p2p.py` spreizt ein
Byte auf zwei Register: `(sw & 0xF0) | 0x04` und `((sw & 0x0F) << 4) | 0x04`.
Beide Registerbytes haben damit immer das untere Nibble 4; ein Durchlauf über
`0x00`–`0xFF` trifft nur 256 der 65536 Kombinationen. Für `54 84` reicht das,
für einen Wert ausserhalb dieses Rasters müsste man `wrreg(0x0740, [a, b])`
direkt bespielen.

Beim Absuchen zaehlt **`HeaderValid`**, nicht `RxDone`: der Header entscheidet,
ob Syncword und Modulation stimmen, die Nutzlast kann danach immer noch an
falschem LDRO scheitern. Einzelne Treffer sind mit Vorsicht zu geniessen — ein
sehr starkes Signal loest gelegentlich einen falschen Header aus (gemessen bei
`0xED`, dort kam anschliessend kein einziges Paket).

## Gegenstelle

| | |
|---|---|
| Modell | Ebyte **E90-DTU(400SL30)E** |
| Firmware | `FW-9181-0-10`, SN `S4201874S` |
| MAC | `78-EE-4C-D7-EA-07` |
| Netz | `192.168.4.101`, statisch, Web auf 80 (`admin`/`admin`) |
| Datensockel | TCP **8886** — alles, was hier rein geht, geht auf die Luft |
| Funkband | 410.125–493.125 MHz, 84 Kanäle à 1 MHz |

## Das Band ist nicht verhandelbar

Das E90 ist ein **400er** Modul. Es erreicht die 868.125 MHz der
Brauneck-Strecke nicht — kein Konfigurationswert bringt es dorthin, weil
Anpassnetzwerk, 30-dBm-PA und Antenne auf 433 MHz gebaut sind. Getroffen wird
sich deshalb auf dem E90-Kanal 23:

```
410.125 MHz + 23 × 1 MHz = 433.125 MHz
```

Kanal 23 ist der Werkswert dieser Modulfamilie, deshalb stand er schon.

Der Preis steht in [README.md](README.md) unter „Welcher Frequenzbereich?":
der Rauschflur des Waveshare-Boards liegt bei 434 MHz mit −116/−117 dBm auf dem
thermischen Grund, bei 868 MHz dagegen bei −106 dBm. Das Board lässt bei 433 MHz
also kaum etwas durch, in beide Richtungen. Gemessen kam ein Signal des E90 mit
**30 dBm Sendeleistung im selben Raum** nur mit −77 dBm an. Für den Tisch reicht
das mit 15 dB SNR bequem, für eine Strecke über Land nicht.

## Funkparameter

| | Wert |
|---|---|
| Frequenz | **433.125 MHz** (E90-Kanal 23) |
| Spreizfaktor | **SF7** |
| Bandbreite | **BW 500 kHz** |
| LDRO | **1** — nicht 0, siehe Fallen |
| Coding Rate | 4/5 (für den Empfang belanglos, der Header trägt sie) |
| Syncword | **0x58** → Register `0x0740` = `54 84` |
| CRC | an, expliziter Header, IQ normal |
| Luftzeit | ~32 ms für 15 Byte Nutzlast |

Auf der E90-Seite entspricht das dem Luftraten-Index **5**, im Webinterface als
„19.2k" etikettiert.

## Rahmenformat

Das E90 packt die Nutzlast in einen eigenen 8-Byte-Kopf und verknüpft sie mit
`0x12`. **Das Format gilt für beide Gerätefamilien**, an zwei unabhängigen
Geräten gegengeprüft:

```
 2c AA XX YY NN HH LL SS │ Nutzlast XOR 0x12
 │  │  │  │  │  └─┬─┘ └── Länge der Klartext-Nutzlast
 │  │  │  │  │    └────── Adresse (HH LL)
 │  │  │  │  └─────────── NETID
 │  │  │  └────────────── XX ^ 0xA1
 │  │  └───────────────── XOR über die Klartext-Nutzlast, dann ^ 0xA0
 │  └──────────────────── geräteabhängig: 0x17 (400SL30) / 0x12 (900SL33)
 └─────────────────────── fest
```

Dass die Adressbytes wirklich die Adresse sind, zeigt der Vergleich: der 400er
stand auf 65535 und sendete `ff ff`, der 900er steht auf 0 und sendet `00 00`.

Beispiel, mitgeschnitten:

```
2c 17 f2 53 00 ff ff 0e 57 2b 22 3f 2c 42 5b 51 5d 32 22 23 21 18
                        └── XOR 0x12 ──> "E90->PICO 013\n"
```

XOR über `E90->PICO 013\n` ist `0x52`; `0x52 ^ 0xA0` = `0xF2` = XX. ✓
Gegenprobe am MAC-Beacon, das das E90 periodisch sendet: Nutzlast
`78 ee 4c d7 ea 07`, XOR `0xE0`, `0xE0 ^ 0xA0` = `0x40` — genau das
mitgeschnittene Byte. ✓

**Ein Frame mit falschem XX wird verworfen.** Das war der Schlüssel: ein
selbstgebauter Rahmen mit plausiblem, aber falschem XX blieb wirkungslos, ein
*wortgleicher Replay* eines echten Frames wurde dagegen angenommen. Damit war
klar, dass nur die beiden Prüfbytes fehlten und nicht das Format.

Beim Empfang hängt das E90 seinerseits ein **RSSI-Byte** an, was
`wlsdatarssienable` steuert: `b'Pico Nachricht 4\xae'` heißt −0xAE/2 = −87 dBm.

## Wie die Parameter gefunden wurden

Das Handbuch in `~/Dokumente/ebyte_E90DTU.pdf` gehört zum **900er** Modell und
passt weder in der Frequenz noch in der Ratentabelle. Alles unten ist gemessen.

**1. Sendet das Gerät überhaupt, und wo?** Ein RSSI-Sweep des Pico über
432.0–434.5 MHz in 125-kHz-Schritten, während das E90 im Sekundentakt sendet:

```
432.750 MHz  −112 dBm      433.125 MHz  −76 dBm   ← Maximum
432.875 MHz   −91 dBm      433.250 MHz  −86 dBm
433.000 MHz   −85 dBm      433.375 MHz  −91 dBm
                           433.500 MHz  −113 dBm
```

Sauberes Maximum auf 433.125 MHz. Die Schultern sind Filterdurchgriff des
starken Signals, keine echte Signalbreite.

**Vorsicht bei RSSI als Nachweis.** Eine Kontrollmessung mit *abgeschaltetem*
Sender lieferte dieselben Pegelspitzen (−87 dBm) — das 433er ISM-Band ist voll
von Fremdverkehr. Ein einzelner RSSI-Ausschlag beweist gar nichts; erst der
Sweep mit klarem Maximum und die Gegenprobe ohne Sender tragen.

**2. Welche Modulation?** Der SX1262 meldet `PreambleDetected` (IRQ-Bit 2)
schon **vor** der Syncword-Prüfung. Damit lässt sich die Modulation unabhängig
vom noch unbekannten Syncword einkreisen — 4 s Lauschen je Kombination:

| | BW125 | BW250 | BW500 |
|---|---|---|---|
| SF6 | 0 | **14** | 7 |
| SF7 | 1 | 0 | **21** |
| SF8 | 0 | 2 | 0 |
| SF9 | 0 | 0 | 0 |

SF7/BW500 und SF6/BW250 haben dieselbe Chirprate (BW/2^SF = 3906.25) und sind
für den Präambeldetektor nicht zu unterscheiden. Nur **SF7/BW500** rastet
danach auch auf den Header ein; SF6/BW250 und SF5/BW125 empfangen nichts.

**3. Welches Syncword?** Absuchen von `0x00`–`0x7F` bei SF7/BW500, je 1 s, mit
`HeaderValid` als Kriterium. Treffer bei **0x58–0x5F** — alle acht schreiben
dasselbe erste Registerbyte `0x54`, ausgewertet wird also nur dieses. Welcher
der acht Werte gesendet wird, lässt sich am SX126x deshalb **nicht** bestimmen;
das klärte erst der SX1302: **0x55** (siehe Korrektur oben).

**4. Warum trotzdem CRC-Fehler?** Siehe Fallen.

## Fallen

**1. LDRO muss 1 sein.** `set_modulation()` rechnet LDRO aus der Symboldauer
und kommt bei SF7/BW500 auf 0. Damit rastet der Header ein, `HeaderValid`
feuert — und *jede* Nutzlast kommt mit CRC-Fehler an. Das ist die böseste Falle
der Strecke, weil sie wie „fast richtig" aussieht:

```
ldro0 cr1 CRCFEHL len22 b'-\xa7\x15\xfcQ\xc43\x9b1j\xa4r\xe8D\xfd...'
ldro1 cr1 CRC-OK  len23 b',\x17\xc0a\x00\xff\xff\x0fW+"?,B[Q]2#""#\x18'
```

**2. Die Luftraten-Etiketten sind nominal.** Index 5 heißt „19.2k". Die gängige
Ebyte-Tabelle übersetzt das zu SF7/BW125 — gemessen ist es SF7/BW500. Nicht auf
die Tabelle verlassen, messen.

**3. `sock_mode` 2 ist der TCP-Server, nicht 0.** Die Modus-Tabelle in
`python/ebyte_e90_api.py` führt `0` als „TCP Server" und `2` als „TCP Client".
Nachgemessen lauscht das Gerät mit `0` auf **keinem** Port; mit `2` ist 8886
offen. Ein Test gegen ein nicht lauschendes Gerät sieht aus wie ein
Funkproblem und ist keines.

**4. `wlspower` 0 ist die höchste Stufe**, 3 die niedrigste. Werkseinstellung
war 3 — also die schwächste.

**5. Bildkalibrierung ist bandgebunden.** `set_frequency()` schrieb fest
`0xD7,0xDB` (863–870 MHz). Für 430–440 MHz will der SX1262 `0x6B,0x6F`
(Datenblatt Tab. 9-2). In `lora_p2p.py` wählt `kalibrierband()` das jetzt nach
Frequenz; für die 868er Strecke ändert sich dadurch nichts.

**6. `GetRssiInst` beginnt bei Index 0.** Byte 1 liefert konstant `0xFF`, also
scheinbar −127.5 dBm — kein Messwert, sondern ein Lesefehler. Gleiche
Indizierung wie bei `GetRxBufferStatus`, siehe [README.md](README.md).

**7. LBT kann das Senden aufhalten.** Im belegten 433er Band hält Listen Before
Talk das Modul zurück. Für die Messungen abgeschaltet.

## Benutzung

Auf dem Pico:

```python
import ebyte433
ebyte433.hoeren()                   # mitlesen, was das E90 funkt
ebyte433.senden("hallo")            # erscheint am E90 auf TCP 8886
ebyte433.rahmen(b"x")               # Frame bauen
ebyte433.entpacken(roh)             # Klartext aus einem Frame
```

Vom Rechner aus:

```sh
mpremote connect /dev/ttyACM0 cp ebyte433.py :
mpremote connect /dev/ttyACM0 exec "import ebyte433; ebyte433.hoeren()"
```

Gegenprobe am E90 — der Sockel ist ein roher Datenschlauch in beide Richtungen:

```sh
python3 -c "
import socket
s = socket.create_connection(('192.168.4.101', 8886))
s.send(b'vom E90 auf die Luft\n')   # -> kommt am Pico an
print(s.recv(4096))                  # <- was der Pico gefunkt hat
"
```

## Verifiziert

```
E90 → Pico:  RSSI −78 dBm  SNR 15.0 dB  CRC ok  b'E90->PICO 014\n'
Pico → E90:  EMPFANGEN b'Pico Nachricht 4\xae'
```

## Dateien

| Pfad | Inhalt |
|---|---|
| `devices/pico_sx1262/ebyte433.py` | Gegenstelle auf dem Pico, inkl. Rahmen-Codec |
| `devices/pico_sx1262/lora_p2p.py` | SX1262-Treiber; `kalibrierband()` neu |
| `python/e90_pico_setup.py` | stellt das E90 auf diesen Kanal (nicht in diesem Repo) |
| `python/e90_restore.py` | schreibt ein Backup zurück (nicht in diesem Repo) |
| `python/e90_backup/*.json` | Auslieferungszustand und funktionierender Stand |

## Offen

* **Antennenanpassung.** Das Board ist auf 868 MHz gebaut. Eine 433-MHz-Antenne
  am Pico würde den größten Teil der Fehlanpassung beheben; ohne sie ist die
  Strecke auf Sichtweite beschränkt.
* **Sendeleistung und LBT.** Für die Messungen steht das E90 auf 30 dBm mit
  abgeschaltetem LBT. Im 433er ISM-Band gelten 10 mW ERP — für Dauerbetrieb
  zurückdrehen (`wlspower`, `wlslbtenable` in `e90_pico_setup.py`).
* **Die Kopfbytes 2 und 3** sind als Prüfsumme verstanden und reproduzierbar,
  ihre Herkunft im Ebyte-Protokoll aber nicht belegt. Für den Betrieb reicht
  die Regel; für ein zweites Modul ist sie ungeprüft.

---

# E90-DTU(900SL33) über RS-232

Das zweite Gerät (E90-DTU(900SL33), 33 dBm). Es liegt mit 850.125–930.125 MHz **im gut angepassten Bereich
des Waveshare-Boards** und ist damit die interessantere Gegenstelle: gemessener
Rauschflur des Pico bei 868 MHz −102 dBm gegenüber −118 dBm auf 433 MHz.

## Betriebsart über DIP

Aus dem E90-DTU-SL-Handbuch, wörtlich bestätigt durch „M0 = ON，M1 = OFF,
device works in Mode 2":

| Modus | | M1 | M0 | |
|---|---|---|---|---|
| Mode 0 | Normal | ON | ON | UART + RF, transparent, Konfiguration über Luft möglich |
| Mode 1 | WOR | ON | OFF | |
| Mode 2 | **Konfiguration** | OFF | ON | Register über die serielle Schnittstelle |
| Mode 3 | Sleep | OFF | OFF | |

In **Mode 2 ist der Funk komplett aus** („Wireless transmission is off.
Wireless receiving is off."). Wer dort auf Empfang wartet, wartet vergebens —
das ist kein Fehler, sondern die Betriebsart.

Register lesen antwortet auch in **Mode 3** (Sleep), nicht nur in Mode 2.

## Anschluss

Die DB-9-Buchse ist laut Handbuch eine **Standard-RS-232-Schnittstelle**
(±12 V, invertierte Logik), die 3.81-Klemmleiste ist RS-485 plus Versorgung.
Ein USB↔**TTL**-Kabel kann an der DB-9 grundsätzlich nicht arbeiten — es
braucht einen echten USB↔RS-232-Wandler.

LEDs als Diagnose: **RXD-LED blinkt beim Empfangen, TXD-LED beim Senden**.
Blinken beide, während man Anfragen schickt, ist die Leitung in beiden
Richtungen elektrisch in Ordnung, und ein ausbleibendes Ergebnis liegt am
Protokoll — nicht am Kabel.

## Konfigurationsprotokoll: E32-Stil, nicht E22

Das Gerät antwortet **nicht** auf AT-Kommandos und nicht auf das
E22-Registerprotokoll. Es spricht den älteren 6-Byte-Rahmen:

```
C0 ADDH ADDL SPED CHAN OPTION     C0 = dauerhaft speichern
C1 C1 C1                          alles lesen
C2 ADDH ADDL SPED CHAN OPTION     nur bis zum Stromausfall
```

Auffällig: **jede** `C1 xx xx`-Anfrage liefert dieselbe Antwort, das Gerät liest
sie durchweg als „alle Parameter lesen". Wer wie beim E22 adressweise zu lesen
versucht, hält die immer gleiche Antwort für einen Fehler.

Ausgelesener Werkszustand:

```
c0 00 00 1a 06 44
      │  │  │  └── OPTION 0x44: transparent, FEC an, maximale Leistung
      │  │  └───── CHAN 0x06
      │  └──────── SPED 0x1A: 8N1, 9600 Bd UART, Luftrate 2.4k
      └─────────── Adresse 0x0000
```

Baudrate und Parität decken sich mit den dokumentierten Werkswerten, was die
Dekodierung bestätigt.

**Erstes Kommando nach dem Öffnen geht verloren.** Die Leitung muss sich erst
setzen; wer einmal sendet und nichts hört, schließt zu früh auf einen Defekt.
Zweimal senden und die zweite Antwort werten.

## Frequenz: Kanal 18 heißt 868.125 MHz

Das Handbuch gibt die Formel für die 900er-Reihe ausdrücklich an, sie muss
nicht geraten werden:

```
Actual frequency = 850.125 + CH × 1M      ->  850.125 + 18 = 868.125 MHz
```

Kanal 18 ist damit der Werkskanal des DTU; die Werkseinstellung des nackten
Moduls (`62 00 00 00 00 00`) hat dagegen Kanal 0.

## Der Sweep, der fast danebenging

Die erste Trägersuche lief mit **125 kHz Empfangsbandbreite in 1-MHz-Schritten**
und fand nichts. Das war ein Messfehler: bei BW125 beobachtet man pro
Stützstelle nur 125 kHz, also ein Achtel des Rasters — ein Träger zwischen den
Stützstellen fällt durch. Der Träger auf 868.125 MHz lag genau in so einer
Lücke und wurde als −88 dBm, also Rauschflur, protokolliert.

Mit **BW500 in 500-kHz-Schritten** (lückenlos) war er sofort da:

```
Maximum: 868.000 MHz mit −11.0 dBm
```

Feinsuche mit BW125 zeigt das Plateau von 867.9 bis 868.4 MHz — rund 500 kHz
breit, passend zur tatsächlichen Modulation:

```
867.800  −44 dBm      868.200  −15 dBm
867.900  −15 dBm      868.300  −13 dBm
868.000  −12 dBm      868.400  −23 dBm
868.100  −11 dBm      868.500  −59 dBm
```

**Merksatz: Schrittweite ≤ Empfangsbandbreite, sonst sucht man Löcher ab.**

## Funkparameter des 900SL33

| | Wert |
|---|---|
| Frequenz | 868.125 MHz (Kanal 18) |
| Modulation | **SF11 / BW500 / LDRO 1** |
| Syncword | 0x58 (Register `54 84`) |
| Luftrate laut Gerät | „2.4k" |
| Empfang am Pico | −12 dBm, SNR 7–8 dB |

Auch hier gilt: **LDRO=1**, und ohne es scheitert jede Nutzlast an der CRC,
während der Header sauber einrastet. Genau wie beim 400er.

Die Luftraten-Etiketten sind endgültig als unbrauchbar erwiesen: „19.2k" war
beim 400er SF7/BW500, „2.4k" ist hier SF11/BW500. Beide Male BW500, beide Male
nicht das, was die gängige Ebyte-Tabelle behauptet.

Verifiziert, acht von acht Paketen:

```
RSSI −12 SNR 7.8 CRC ok  Kopf 2c 12 de 7f 00 00 00 0d  b'E90UART 0587\n'
RSSI −12 SNR 7.8 CRC ok  Kopf 2c 12 d1 70 00 00 00 0d  b'E90UART 0589\n'
```

Und die Gegenrichtung, sechs von sechs — der Pico baut den Rahmen mit
`ebyte868.rahmen()`, das DTU gibt die Nutzlast seriell aus:

```
b'PICO an DTU 0\xec PICO an DTU 1\xea PICO an DTU 2\xeb
  PICO an DTU 3\xea PICO an DTU 4\xea PICO an DTU 5\xed'
```

Das angehängte Byte ist der RSSI (REG3 Bit 7), `0xEC` also −118 dBm.

**Diese Zahl passt nicht zum Rest.** Der Pico hört das DTU mit −12 dBm, das
DTU den Pico mit −118 dBm — 106 dB Unterschied, obwohl zwischen 33 dBm und
14 dBm Sendeleistung nur 19 dB liegen. Empfangen wird trotzdem lückenlos, was
bei SF11/BW500 (Empfindlichkeit um −125 dBm) auch bei −118 dBm plausibel ist.
Ob der angehängte Wert wirklich der Paket-RSSI ist oder das Umgebungsrauschen
(beide RSSI-Bits sind gesetzt), ist nicht geklärt — die Zahl sollte man
deshalb nicht als Pegelmessung verwenden.

## RSSI im laufenden Betrieb abfragen

Mit REG1 Bit 5 (Umgebungs-RSSI) lässt sich das Gerät **in Mode 0** über die
serielle Schnittstelle abfragen, ohne den DIP anzufassen — im
Konfigurationsmodus ist der Funk ja aus und es gibt nichts zu messen:

```
senden : C0 C1 C2 C3 <Adresse> <Länge>
zurück : C1 <Adresse> <Länge> <Wert>

Register 0x00  aktuelles Umgebungsrauschen
Register 0x01  RSSI des zuletzt empfangenen Pakets
dBm = −RSSI / 2
```

`python/e90ser.py --rssi` macht genau das. Der Wert ist eine vom Pico
unabhängige zweite Messquelle und beantwortet die Frage, ob das Gerät im
Sendebetrieb überhaupt noch auf den UART hört.

## Repeater-Betrieb

`REG3` Bit 5 schaltet den Repeater, Bit 6 den Fixpunkt-Modus. **Beide gehören
zusammen**, das Handbuch ist da deutlich:

> „After the repeater function is enabled, if the **target address is not the
> module itself**, the module will forward it once. In order to prevent data
> return-back, it is recommended to use it in conjunction with the fixed point
> mode. That is: the target address is different from the source address."

Ebyte filtert also **nicht nach Absender**, sondern nach **Zieladresse** — eine
Absenderkennung gibt es im Rahmen gar nicht. Die Echo-Vermeidung entsteht erst
dadurch, dass im Fixpunkt-Modus Quelle und Ziel verschieden sind. Repeater
allein, ohne Fixpunkt, würde zurückkoppeln.

```
REG3 0x83 -> 0xE3     Bit 7 RSSI-Byte | Bit 6 Fixpunkt | Bit 5 Repeater
C0 06 01 E3           dauerhaft (C2 waere nur bis zum Stromausfall)
```

**Zwei Konsequenzen, die man einplanen muss:**

* Die Adresse des Repeaters entscheidet, was er weiterleitet. Steht sie auf
  `0x0000` und ist der Verkehr ebenfalls an `0x0000` gerichtet, gilt er als
  „an mich selbst" und wird **nicht** weitergeleitet. Die Endpunkte brauchen
  also einen Adressplan, in dem das Ziel nicht die Repeater-Adresse ist.
* Im Fixpunkt-Modus liest das Gerät die **ersten drei Bytes der seriellen
  Daten als Ziel** (Adresse hoch, Adresse niedrig, Kanal). Wer den DTU vorher
  transparent benutzt hat, muss seine Sendedaten umstellen.

Gesetzt wird das im Konfigurationsmodus; laut Handbuch beginnt der Repeater zu
arbeiten, sobald danach wieder auf Mode 0 zurückgeschaltet wird.

## Funkkonfiguration `CF CF` — geht so nicht

Das Handbuch nennt eine Fernkonfiguration:

```
Command: CF CF + general command      Format error -> FF FF FF
Reply:   CF CF + general response
```

**Vom Pico aus funktioniert das nicht.** Ein Rahmen mit der Nutzlast
`cf cf c1 06 01` kommt am DTU an und wird dort unverändert auf die serielle
Seite ausgegeben — als Daten, nicht als Kommando:

```
seriell heraus: cf cf c1 06 01 ea       (ea = RSSI-Byte)
```

Der Grund steht über der Kommandotabelle: „**In configuration mode (mode 2:
M1=OFF, M0=ON), supported commands are as follows**" — die ganze Liste,
einschließlich der Funkkonfiguration, steht unter dieser Voraussetzung. Das
`CF CF` wird also am **UART des sendenden Moduls** ausgewertet, das daraufhin
ein besonders markiertes Funkpaket erzeugt. Ein selbst gebauter Rahmen trägt
diese Markierung nicht.

Nicht geklärt ist, worin die Markierung besteht. Das zweite Kopfbyte ist ein
Kandidat (`0x17` beim 400er, `0x12` beim 900er), aber unbelegt.

## Fallen auf der seriellen Seite

**Ungültige Adressen werden mit `ff ff ff` quittiert** — das ist eine Absage,
keine Antwort. `C1 00 09` geht, `C1 00 0C` nicht.

**In Mode 0 antwortet `C1` nicht mehr**, weil der UART transparent ist. Das ist
kein Defekt, sondern der beste schnelle Test, in welchem Modus das Gerät steht.

**Der PID-Block `80H`–`86H`** ist laut Handbuch „7 bytes of product
information", read-only. Eine byteweise Bedeutung gibt Ebyte nicht an; das
Gerät hier liefert `00 22 10 1e 0b 00 00`. Ohne Spezifikation ist das ein
Rohwert und keine Version.

---

# E22-900 als Empfänger für den TrackerD

Ein blankes **E22-900** an einem CH340-USB-Adapter (`/dev/ttyUSB0`) spricht
dasselbe Registerprotokoll wie das E90-DTU(900SL33) — `python/e90ser.py`
liest und schreibt es unverändert.

Auf den TrackerD abgestimmte Konfiguration:

```
00 00 00 62 20 12 80 00 00
│  │  │  │  │  │  └── REG3 0x80: RSSI-Byte an, transparent
│  │  │  │  │  └───── REG2 0x12: Kanal 18 = 868.125 MHz
│  │  │  │  └──────── REG1 0x20: Paket 240 B, Umgebungs-RSSI an, Leistung max
│  │  │  └─────────── REG0 0x62: 9600 8N1, Luftrate 2.4k
│  │  └────────────── NETID 0
└──┴───────────────── Adresse 0x0000
```

Adresse und NETID entsprechen dem, was der TrackerD in seine Ebyte-Rahmen
schreibt. Die **Paketgröße muss von 32 auf 240 Byte**: ein Alarm mit Position
und Messwerten ist über 50 Byte lang und käme sonst zerstückelt heraus.

**Die Luftrate „2.4k" ist auch hier SF11/BW500.** Gemessen, indem der Pico
dieselbe Nutzlast nacheinander auf fünf Modulationen sendete — durch kam
ausschließlich SF11/BW500:

```
E22 EMPFANGEN: b'PICO-SF11BW500\xdc'
```

Das Modul entpackt den Ebyte-Kopf selbst und hängt das RSSI-Byte an
(`\xdc` = −110 dBm).

## Adresse 0xFFFF: der Empfänger muss im Monitor stehen

**Der Werkswert `0xFFFF` ist kein Zufall, sondern Voraussetzung.** Bei Ebyte
heißt er Monitor bzw. Broadcast: das Modul nimmt alles auf seinem Kanal an.
Wer die Adresse auf den Wert des Senders setzt — hier `0x0000`, wie ihn der
TrackerD in seine Rahmen schreibt —, schaltet den Adressfilter scharf und der
Empfang hört auf:

| Adresse des E22 | TrackerD → E22 |
|---|---|
| `0xFFFF` (Werk, Monitor) | empfängt |
| `0x0000` | **nichts** |

Ein reiner Zuhörer bleibt also auf `0xFFFF`. Nur NETID und Kanal müssen
übereinstimmen.

Verifiziert: `b'076C>ALARM,T34.8,H34.1'` — der Alarm des TrackerD samt
Temperatur und Feuchte, am E22 seriell herausgekommen.

## Zwei Irrwege bei der Fehlersuche

**Das angehängte RSSI-Byte taugt nicht als Pegelmessung.** Mit eingeschaltetem
Umgebungs-RSSI (`REG1` Bit 5) liefert es plausibel den *Rauschflur* statt der
Empfangsstärke. Aus einem so gelesenen `-110 dBm` habe ich auf eine defekte
Antenne geschlossen und den Antennenwechsel empfohlen — falsch. Auch mit
abgeschaltetem Umgebungs-RSSI meldet das Modul für ein sauber dekodiertes
Paket noch `-111 dBm`, während der Pico denselben Sender mit `-19 dBm` hört.
Die 92 dB Unterschied sind nicht erklärt; der Wert ist als Größenordnung
unbrauchbar.

**Antenne über den Sendepfad prüfen, nicht über RSSI.** Eine Antenne arbeitet
in beide Richtungen gleich. In transparentem Modus geht alles, was man in den
UART schreibt, auf die Luft — kommt es bei einer Gegenstelle kräftig an, ist
die Antenne in Ordnung und der Fehler liegt woanders:

```
E22 sendet ueber seinen UART  ->  Pico empfaengt  -34 dBm
```

Das entlastet die Antenne in einem Schritt und hätte den Umweg erspart.
