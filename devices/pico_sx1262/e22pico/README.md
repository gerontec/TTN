# e22pico — RadioLib-Responder auf dem Pico-LoRa (Waveshare SX1262)

Antwortet auf jedes gehörte Ebyte-Paket mit zwei `PONG`-Zeitstempeln
(NETID 00 und NETID BB, Rundruf FFFF, 2,5/3,0 s verzögert wegen der
Taubheit des E22 nach eigenem Senden). Messstand 19.08.2026: der Pico hört
den E22 5/5; umgekehrt kamen 2/10 PONGs am E22-UART an — Einzelheiten und
offene Fragen in `../e22spec.md`, Abschnitt 4.

## Inhalt

```
platformio.ini          PlattformIO-Projekt (board=pico, framework=arduino)
src/loraparms.h         alle LoRa-Parameter und Pins — wird nach jedem Start gelesen
src/main.cpp            Firmware, eng nach RadioLib-Beispiel SX126x_PingPong
pico_c_pingpong.py      Testskript: E22 sendet „A n“, zählt PONGs an beiden UARTs
```

## Bauen und Flashen (fernsteuerbar, ohne Taste)

```bash
pio run -d ~/e22pico                     # → .pio/build/pico/firmware.uf2
printf "boot\n" > /dev/ttyACM0           # Firmware-Kommando „boot“ → BOOTSEL
sleep 2
DEV=$(lsblk -lnp -o NAME,LABEL | awk '$2=="RPI-RP2"{print $1}')
sudo mount -t vfat -o uid=gh "$DEV" /mnt/rp2
cp ~/e22pico/.pio/build/pico/firmware.uf2 /mnt/rp2/
sync && sleep 2                          # Laufwerk verschwindet, Pico rebootet
```

Das BOOTSEL-Laufwerk wandert bei jedem Start (`sda`/`sdb`/…), deshalb die
Suche über `lsblk`. Der Pico meldet sich nach dem Reboot wieder als
`/dev/ttyACM0`.

## USB-Kommandos der Firmware

| Kommando | Wirkung |
|---|---|
| `diag` | Status, Syncword-Register, DeviceErrors, TX-Testrahmen |
| `tx` | einen Ebyte-Rahmen senden |
| `boot` | in den BOOTSEL-Modus (zum Flashen, s. o.) |

Beim Start sendet die Firmware ihre Parameter als `PARM …`-Beacon über die
Luft; das Gateway schreibt ihn in die Datenbank.
