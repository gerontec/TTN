# Patches statt Kopie

`src/` ist eine Arbeitskopie von Draginos v1.5.3
(`Example/LoRaWAN/examples/TrackerD/`). Dieser Quelltext liegt **ohne
Lizenzangabe** auf GitHub — lesbar, aber nicht weitergabefrei. Deshalb steht
hier nur die Aenderung.

Anwenden:

    git clone https://github.com/dragino/TrackerD ../repo
    cp -r ../repo/Example/LoRaWAN/examples/TrackerD/. src/
    cp -r ../repo/Library/arduino-lmic lib/arduino-lmic
    for p in patches/*.patch; do patch -p0 -d src < "$p"; done
    pio run
