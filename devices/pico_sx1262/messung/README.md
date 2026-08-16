# Messskripte

Alle drei laufen direkt auf dem Pico und setzen `lora_p2p.py` auf dem Board
voraus (ausser `tcxo.py`, das eigenständig ist):

```sh
mpremote connect /dev/ttyACM0 run band.py
```

| Skript | Zweck | Ergebnis dieser Messung |
|---|---|---|
| `tcxo.py` | fährt alle acht `SetDIO3AsTCXOCtrl`-Spannungsstufen durch und liest `GetDeviceErrors` | ohne DIO3-Versorgung `0x0020` (XOSC_START_ERR); jede Stufe ab 1.6 V räumt ihn ab |
| `band.py` | Chip-Kennung 0x0320, PLL-Rastbereich per `SetFs`, Rauschflur über 28 Frequenzen | `"SX1261 V2D 2D02"`; PLL rastet 100–1100 MHz (untauglich als Bandindikator); unter 700 MHz Rauschflur, ab 750 MHz Durchlass |
| `rssi.py` | 30 s Dauerempfang, `GetRssiInst` pollen | fand die fehlende Antenne: 1444 Proben zwischen −114,0 und −112,0 dBm, während das Gateway mit 14 dBm sendete |

`rssi.py` ist das nützlichste Werkzeug bei stiller Strecke: es trennt
Antenne/Frontend von der Demodulation in einer einzigen Messung. `TxDone` sagt
darüber nichts aus — der Chip meldet es auch ohne angeschlossene Antenne.

Für `band.py` gilt die Einschränkung aus dem Haupt-README: der Rauschflur-Sweep
misst Frontend-Durchlass **mal** Umgebungssender. Die Spitzen bei 750/800/928 MHz
sind LTE und GSM, nicht die Filterkurve.

`../readlorarf.original` ist die Datei, die beim Anstecken auf dem Board lag —
aufgehoben, weil sie den Ausgangspunkt dokumentiert (SPI-Mode 3, Senden ohne
`WriteBuffer`/`SetTx`, kein Syncword, kein TCXO).
