# Wiederaufsetzpunkt — Notfallkanal Lenggries

Stand **15.08.2026**. Dieses Repo beschreibt nur noch den **lokalen** Pfad plus
TTN als optionalen Mitschnitt. Die frühere Kette über einen Server im Internet
(WireGuard, ipgate1, Datenhaltung und Traccar auf heissa.de) ist bewusst
entfernt: Der Notfallkanal darf an nichts hängen, was bei einem Internetausfall
verschwindet. In der Git-Historie steht sie weiter, falls jemand nachsehen will.

## Beteiligte

| Rolle | Adresse | Aufgabe |
|---|---|---|
| Gateway | `10.130.1.1` (eigenes WLAN), im Heimnetz über `eth1` | Dragino DLOS8N, `fwd -d sx1302` |
| Netzserver | `192.168.5.23` (dell-3660) | ChirpStack v4 + mosquitto, **maßgeblich** |
| Notebook | LA66 am USB | Funkgegenstelle vom Berg |
| TrackerD | `A840414F1188076C` | Tracker, LoRaWAN in app0, LoRa-P2P in app1 |

## Aufbau

```
   LA66 USB-Adapter        TrackerD
          |                    |
          +---------+----------+
                    v
          Dragino DLOS8N (Lenggries)
                    |
        +-----------+--------------------+
        | server2                        | server1
        | LAN, 1,2 ms, kein Tunnel       | nur mit Internet
        v                                v
   192.168.5.23                     TTN eu1
   ChirpStack :8090                 lenggries-sensors
   mosquitto :1883                  (Mitschnitt)
        |
        +-- dragino-rx.service    LoRa  -> MQTT
        +-- crisis-bcast.service  MQTT  -> LoRa
```

Der lokale Weg läuft im Normalbetrieb dauernd mit und ist damit dauernd
getestet. Ein Umschalten im Ernstfall gibt es bewusst nicht — ungetestete
Umschaltungen scheitern genau dann, wenn man sie braucht.

## Was steht

* **Beide Geräte sind lokal registriert und werden gehört.** `cs_state.py`
  zeigt `last_seen` für `la66-notfall` und `trackerd-lenggries`.
* **Beide sind zusätzlich im TTN eingetragen** (`la66-f18962e0`,
  `trackerd-1188076c`); dort steigen die Frame-Counter mit, solange Internet da
  ist.
* **Beide laufen als ABP**, lokal wie im TTN — siehe Stolperstelle 1.
* **Der LA66 lässt sich unter Linux flashen**, ohne Windows und ohne
  BOOT-Brücke: `devices/la66_p2p/la66_uart_flash.py`, Anleitung daneben.
  `la66_mode.py` schaltet in fünf bis neun Sekunden zwischen LoRaWAN und P2P.
* **Der TrackerD hat echtes Dual-Boot** (app0 LoRaWAN, app1 P2P,
  `switch_app.py`, Umschaltung in 1,4 s über otadata).
* **Raw-LoRa kommt am Gateway an**: P2P-Pakete mit Syncword `0x34` auf einem
  konfigurierten Kanal landen als `rxpk.data` im Semtech-UDP-Strom.
* **Der Rohkanal ist gebaut und nutzbar** (16.08.): `chan_Lora_std` liegt auf
  868.125 MHz / SF7 / BW125, ein dritter Forwarder-Server schiebt alles roh auf
  `192.168.5.23:1702`, wo `lora_raw.py` als `lora-raw.service` mithört und auf
  `lora/raw` veröffentlicht. Ganze Herleitung samt Persistenz-Fallen:
  **[gateway/RAWKANAL.md](gateway/RAWKANAL.md)**.

## Stolperstellen

1. **ABP, nicht OTAA — und zwar mit Absicht.** Das Gateway schiebt jeden Uplink
   an beide Server, und beide dürfen Downlinks senden. Ein OTAA-Gerät bekäme
   zwei JoinAccepts und nähme das zuerst eintreffende; der lokale Server könnte
   das Gerät jederzeit an TTN verlieren. Ohne Join gibt es nichts zu kapern.
2. **Der TrackerD-AppKey steht im Gerät**, nicht nur auf dem Aufkleber:
   `AT+CFG` zeigt ihn im Klartext. Solange er fehlte, kam nie ein JoinAccept —
   das sah wie ein Funkproblem aus und war keins.
3. **Kein REST bei ChirpStack.** Alle `/api/...`-Pfade antworten 404, deshalb
   gRPC auf `:8090`.
4. **ChirpStack meldet Doppeleinträge uneinheitlich.** Beim Gateway kommt der
   Postgres-Fehler als `INTERNAL: duplicate key` durch, nicht als
   `ALREADY_EXISTS`. `cs_setup.py` fängt beides ab.
5. **TTS-Field-Masks sind eigen.** `ids.dev_addr` ist in den NS-/AS-Masken
   verboten, und der AppSKey gehört ausschließlich dem Application Server —
   steht er in der NS-Maske, fliegt die ganze Anfrage raus.
6. **Ein halb angelegtes TTS-Gerät ist nicht reparierbar.** Steht es im
   Identity Server, aber nicht in NS/AS, laufen alle PUTs in ein 409. Auch der
   Wechsel OTAA → ABP geht nur über vollständiges Löschen: `ttn/ttn_delete.py`.
7. **409 „already exists" kann etwas anderes heißen.** Die Meldung nennt das
   Gerät, unter dem die DevEUI schon liegt — bei uns `la66-f18962e0` statt des
   erwarteten Namens. `ttn_register.py` druckt sie deshalb mit.
8. **`server_type=mqtt` legt den Forwarder still.** Dann laufen die Radios auf
   915 MHz und es kommt gar kein LoRaWAN. Richtig ist `lorawan`.
9. **Ein Flash setzt die Funkparameter des LA66 auf Werk** (868.700 MHz, SF12),
   die LoRaWAN-Schlüssel dagegen **nicht** — die liegen in einem eigenen
   Bereich und überleben.
10. **Die P2P-Firmware des TrackerD sichert nichts.** Nach jedem Reset stehen
    Frequenz, SF und Syncword wieder auf den einkompilierten Vorgaben
    (868.125 MHz, SF7, `0x12` privat) — in dem Zustand hört ihn das Gateway
    nicht, das braucht `0x34`.

## Offen

* Die ABP-Sitzung des TrackerD stammt aus einem lokalen Join. Löst jemand dort
  erneut einen Join aus, wird die im TTN hinterlegte Sitzung ungültig und muss
  nachgezogen werden.
* Die P2P-Firmware des TrackerD könnte ihre Parameter im NVS ablegen, damit sie
  einen Reset überleben. Bis dahin trägt der Quelltext die Vorgaben: `cfgSync`
  steht jetzt auf `0x34`, sonst hört das Gateway den Node nach jedem Reset nicht
  mehr. **Noch nicht neu geflasht** — TrackerD war beim Umbau nicht angesteckt.
* Sendeweg des Rohkanals (`lora_raw.py --send`) ist ungeprüft, ebenso der
  Funkweg über die neue Frequenz 868.125 MHz.
* Sendeleistung des TrackerD steht auf 17 dBm ≈ 50 mW und liegt damit über den
  25 mW ERP, die in 868.0–868.6 MHz erlaubt sind — auf 14 dBm entscheiden.
* Storage-Integration im TTN ist nicht aktiviert; Uplinks lassen sich dort
  derzeit nur über die Frame-Counter (`ttn/ttn_show.py`) nachweisen.
