# Pico-E22: die AT-Befehle

Der Knoten `pico-0e22` (Raspberry Pi Pico + Ebyte E22-900M22S, Quelltext in
`e22pico/`) spricht neben seinen kurzen Klartext-Kommandos den AT-Satz der
Dragino-Geraete. Damit laesst er sich einbinden wie ein LA66-Stick: ein Host
schickt `AT+SENDB=0,2,2,00ff` und bekommt `OK`.

Vorlage ist der `AT+CFG`-Auszug unseres eigenen LA66
(`devices/la66_p2p/la66_lorawan_v1.3_cfg.txt`). Geprueft gegen
`e22pico/src/main.cpp` (`atBefehl()`, `atCfg()`, `atHilfe()`) und
`e22pico/src/atparms.h`.

## Anschluss

Zwei gleichberechtigte Wege, beide bedienen denselben Parser:

| Weg | Parameter |
|---|---|
| USB-Konsole | CDC, Baudrate egal |
| UART auf **GP0 (TX) / GP1 (RX)** | **9600 8N1**, wie der LA66-Stick ab Werk |

Die UART ist der eigentliche Zweck: ein Host ohne USB-Stack — ein ESP, eine
SPS, ein Pi ohne freien Port — haengt mit zwei Draehten am Knoten. Abschalten
laesst sie sich mit `AT_UART_AN false` in `atparms.h`.

## Form der Befehle

Alles, was mit `AT` beginnt (Gross- und Kleinschreibung egal), geht an den
AT-Parser; alles andere an die kurze Klartext-Konsole (siehe unten). Der
Befehlsname wird intern in Grossbuchstaben gewandelt, `at+fre=?` geht also
genauso.

| Form | Bedeutung |
|---|---|
| `AT` | Lebenszeichen, antwortet `OK` |
| `AT?` | Hilfeliste |
| `ATZ` | Neustart (`NVIC_SystemReset`) |
| `AT+CMD=?` | Wert lesen |
| `AT+CMD` | dito — ohne `=` wird ebenfalls gelesen |
| `AT+CMD=<wert>` | Wert setzen |

Geantwortet wird mit dem Wert, dann `OK`. Fehler sind `AT_ERROR` (Befehl
unbekannt oder Schreibversuch auf einen festen Wert), `AT_PARAM_ERROR` (Wert
unzulaessig) und `AT_ERROR (<n>)` mit RadioLib-Fehlernummer, wenn das Funkmodul
den Sendeauftrag ablehnt.

## Kennungen — nur lesbar

| Befehl | Antwort |
|---|---|
| `AT+DEUI` | DevEUI, Byte fuer Byte mit Leerzeichen wie beim LA66 |
| `AT+APPEUI` | JoinEUI |
| `AT+APPKEY` | `<in device>` — **der Schluessel wird nie herausgegeben**, bewusste Abweichung vom LA66 |
| `AT+DADDR` | DevAddr der laufenden Sitzung, `00000000` ohne Join |
| `AT+FCU` | Uplink-Zaehler |
| `AT+NJM` | `1` (der Knoten kann nur OTAA) |
| `AT+NJS` | `1`, wenn eine Sitzung steht |
| `AT+CLASS` | `A` |
| `AT+ID` | Stationsname |
| `AT+VER`, `AT+VERSION` | `EU868 v2.0.0 pico-e22 LoRa+LoRaWAN` — beide Schreibweisen, weil Draginos Firmwares sich da nicht einig sind |
| `AT+RSSI`, `AT+SNR` | Empfangswerte des letzten Pakets |
| `AT+CFG` | alles auf einmal, als `AT+X=Y`-Zeilen |

## Rohkanal

Die Funkparameter kommen aus `loraparms.h` und gelten nach jedem Start
unveraendert. Lesen geht immer, schreiben nur bei dreien.

| Befehl | Wert | Vorgabe |
|---|---|---|
| `AT+SF` | nur lesen | `11` |
| `AT+BW` | nur lesen | `500` kHz |
| `AT+CR` | nur lesen | `5` (= 4/5) |
| `AT+SYNCWORD` | nur lesen | `55` |
| `AT+FRE` | `<MHz>[,0]` | `868.1250` |
| `AT+POWER` | `-9`..`22` dBm | aus `loraparms.h` |
| `AT+PREAMBLE` | `4`..`4000` Symbole | `8` |

Ein Schreibversuch auf `SF`, `BW`, `CR` oder `SYNCWORD` antwortet `AT_ERROR` —
diese vier bilden zusammen mit NETID und Adresse den Krisenkanal, sie werden
nicht im laufenden Betrieb verstellt.

`AT+FRE` verschiebt die Frequenz um bis zu ±63,5 kHz um 868,125 MHz. Zweiter
Parameter wie bei `AT+LORAWAN`: `1` (Vorgabe) schreibt den Versatz in den
Flash, `0` haelt ihn nur bis zum naechsten Stromausfall.

## Betriebsart

| Befehl | Wert | Wirkung |
|---|---|---|
| `AT+LORAWAN` | `0` / `1` [`,<minuten>`] | `0` = Rohkanal, `1` = LoRaWAN. Der zweite Wert ist ein Rueckfahrschein: nach so vielen Minuten schaltet der Knoten von selbst zurueck (nur im RAM gemerkt) |
| `AT+RELAY` | `0` / `1` | Relaisbetrieb des Rohkanals |

Der Moduswechsel wird erst ausgefuehrt, wenn die Antwort darauf gesendet ist —
sonst risse das Neuaufsetzen des Funkmoduls die eigene Quittung weg.

## LoRaWAN-Betrieb

| Befehl | Wert | Wirkung |
|---|---|---|
| `AT+ADR` | `0` / `1` | Adaptive Data Rate |
| `AT+DR` | `0`..`7` | Datenrate, Vorgabe `3` (SF9 BW125) |
| `AT+JOIN` | ausfuehren | OTAA-Join sofort anstossen. Ausserhalb des LoRaWAN-Modus `AT_ERROR` |

## Senden und Empfangen

    AT+SEND=<bestaetigt>,<port>,<laenge>,<text>
    AT+SENDB=<bestaetigt>,<port>,<laenge>,<hex>

`bestaetigt` 0 oder 1, `port` 0 nimmt den voreingestellten Port 1. Die
Laengenangabe wird **geprueft, nicht geglaubt**: stimmt sie nicht mit den Daten
ueberein, kommt `AT_PARAM_ERROR`. Mehr als 128 Byte gehen nicht.

| Befehl | Antwort |
|---|---|
| `AT+RECV` | `<port>:<text>` der letzten Empfangsnachricht |
| `AT+RECVB` | `<port>:<hex>` derselben |

Empfangenes wird ausserdem **unaufgefordert** gemeldet, im LA66-Format:

    AT+RECVB=2:00FF

Wer nur Antworten auf eigene Fragen sehen will, setzt `AT_RECV_MELDEN false`
in `atparms.h`. Reine MAC-Downlinks (fPort 0) werden nie gemeldet.

## Kurze Klartext-Kommandos

Die aeltere Konsole gibt es weiter, sie ist beim Messen bequemer als AT:

| Kommando | Wirkung |
|---|---|
| `boot` | in den UF2-Bootloader springen |
| `diag` | Funkregister und Zustand ausgeben |
| `phy` | CRC, IQ, Header, Praeambel, Leistung, Rampe, PA, Frequenz auf einer Zeile |
| `freq`, `freq <MHz>`, `freq tmp <MHz>` | Frequenz lesen, dauerhaft setzen, nur fluechtig setzen |
| `pow`, `pow <dBm>` | Sendeleistung, −9..22 |
| `pre`, `pre <symbole>` | Praeambel, 4..4000 |
| `crc 0\|1`, `iq 0\|1`, `hdr explicit\|implicit` | Rahmenparameter |
| `ramp <us>` | Sendrampe: 10 20 40 80 200 800 1700 3400 |
| `paconf opt\|datenblatt` | PA-Konfiguration: RadioLib-Tabelle oder Datenblatt-Vorgabe |
| `mode`, `mode lora`, `mode lorawan` | Betriebsart wie `AT+LORAWAN` |
| `relay`, `relay on`, `relay off` | Relais wie `AT+RELAY` |
| `lwstat` | LoRaWAN-Zustand |
| `lwreset` | Sitzung und Nonces verwerfen, neu joinen |
| `lwsend <text>` | Uplink auf dem Standardport |
| `tx` | Testpaket `CTEST t=<ms>` im Ebyte-Rahmen senden |
| `src` | den eingebetteten Quelltext ausgeben |

Alle 30 s meldet sich der Knoten von selbst mit einer `alive:`-Zeile — im
LoRaWAN-Modus mit Join-Zustand und Zaehlern, im Rohkanal mit Empfangs-,
Antwort- und Warteschlangenstand.

## Abweichungen vom LA66

Drei, alle bewusst:

1. `AT+APPKEY` antwortet maskiert.
2. Die Rohkanal-Parameter sind fest verdrahtet und nur lesbar.
3. `AT+LORAWAN=0|1` gibt es beim LA66 nicht — es ist dieselbe Sprache, in der
   die TrackerD-Firmware zwischen ihren beiden Anwendungen umschaltet.
