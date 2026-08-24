# TrackerD: was die LEDs sagen

Drei LEDs an drei GPIOs — und je nach Geraetevariante sind Rot und Blau
**vertauscht**:

| Farbe | `sensor_type 13` (TrackerD) | `sensor_type 22` (TrackerD-LS) |
|---|---|---|
| Rot | GPIO 13 (`LED_PIN_RED`) | GPIO 2 (`LED_PIN_RED1`) |
| Blau | GPIO 2 (`LED_PIN_BLUE`) | GPIO 13 (`LED_PIN_BLUE1`) |
| Gruen | GPIO 15 (`LED_PIN_GREEN`) | GPIO 15 |

Welche Variante vorliegt, sagt das erste Byte des Status-Uplinks auf fPort 5
(`0x13` bzw. `0x22`).

**Hauptschalter:** fast jede Anzeige haengt an `sys.lon`. `AT+LON=0` legt die
LEDs still, `AT+LON=1` schaltet sie ein; im Positions-Uplink steht das Bit als
`LON: ON|OFF`. Ausnahme ist `EV_JOINED` — das leuchtet auch bei `LON=0`.

## Blau — alles rund um GPS

| Muster | Bedeutung |
|---|---|
| 100 ms an / 100 ms aus, fortlaufend | GPS sucht (bis `AT+PT`-Grenze bzw. `Positioning_time`) |
| **1000 ms an, einmal** | **Fix gefunden** — das ist das Blinken, das im Normalbetrieb zu sehen ist |
| 200 ms an | `EV_JOINING`, also ein Join-Versuch |

## Gruen — alles rund um Funk

| Muster | Bedeutung |
|---|---|
| 200 ms an | `EV_TXSTART`, jeder Uplink |
| **an, bleibt an** | `EV_JOINED` — wird erst am Ende der Ereignisbehandlung wieder ausgeschaltet |
| 1000 ms an | ein Downlink ist angekommen (`LORA_RxData`) |
| an, waehrend der Knopf gedrueckt ist | Langdruck laeuft, noch unterhalb `exit_alarm_time` |

## Rot — Fehlt etwas oder ist Alarm

| Muster | Bedeutung |
|---|---|
| 1000 ms an | Positions-Uplink **ohne** Fix (Latitude und Longitude sind 0) |
| rot **und** gruen an | Alarm scharf: Langdruck laenger als `exit_alarm_time` (Vorgabe 2 s), kuerzer als 10 s |
| rot **und** blau an | Langdruck zwischen 10 s und 30 s |
| rot allein an | Langdruck ueber 30 s — Alarm wird ausgeloest |

## Blau → Rot → Gruen, je 500 ms nacheinander

Kein Betriebszustand, sondern eine Meldung: **die Einstellungen wurden auf
Werkszustand zurueckgesetzt.** Der Ablauf steht in `print_wakeup_reason()` im
Zweig fuer den Kaltstart und laeuft, nachdem `FDR_flag == 0` die Vorgabewerte
gesetzt hat.

Das passiert nicht nur nach `AT+FDR`, sondern **bei jedem Wechsel der
Firmware-Version**: die Firmware vergleicht `fire_version` (aus dem
Versionsstring, v1.4.8 → 148) mit `fire_version_write` im EEPROM. Sind sie
verschieden, setzt sie `FDR_flag = 1`, ruft `DATA_CLEAR()` und startet neu.

> **Falle:** app0 traegt v1.4.8, das Bauwerk in diesem Verzeichnis v1.5.3. Wer
> zwischen den beiden Slots hin und her bootet, loest **in jede Richtung** ein
> Zuruecksetzen der Einstellungen aus — `AT+PNACKMD=1` ist danach wieder 0,
> ebenso TDC und alles andere aus dem DATA-Bereich. Die Schluessel bleiben:
> DevEUI/AppKey liegen in `KEY` (eeprom0), `DATA_CLEAR()` raeumt nur `DATA`
> (eeprom1). Nach so einem Wechsel also immer [DATALOG.md](DATALOG.md)
> nacharbeiten und mit `AT+PNACKMD=?` nachsehen.

## Gruen leuchtet dauerhaft — was dann los ist

Meist ist es kein Dauerlicht, sondern ein sehr schneller Takt. Nach **jedem**
Kaltstart — und jedes Oeffnen der seriellen Konsole ist ueber DTR/RTS ein
Kaltstart — setzt `print_wakeup_reason()` `os_JOINED_flag = 1`. Daraus macht
`sys_sleep()` `sys.tdc = 1000`: ein Zyklus pro Sekunde statt pro TDC. Bei
`LON=1` blitzt Gruen dann jede Sekunde 200 ms und sieht durchgehend aus. Nach
dem naechsten regulaeren Zyklus ist der Spuk vorbei.

Dazu kommt, dass `EV_JOINED` Gruen setzt und der Ausschalter am Ende von
`onEvent()` so aussieht:

```c
digitalWrite(LED_PIN_RED | LED_PIN_BLUE | LED_PIN_GREEN | LED_PIN_RED1 | LED_PIN_BLUE1, LOW);
```

Das verodert **Pinnummern** statt die Pins einzeln zu schalten: `13|2|15|2|13`
ergibt 15. Zufaellig ist das genau Gruen — Rot und Blau werden hier also nie
ausgeschaltet, obwohl es so aussehen soll. Der Zweig liegt ausserdem nur im
`njm == 1`-Fall (OTAA); bei ABP laeuft er gar nicht.
