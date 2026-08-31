# Patches statt Kopie

Draginos Quelltext liegt **ohne Lizenzangabe** auf GitHub — lesbar, aber nicht
weitergabefrei. Deshalb steht hier nur die Aenderung, nie eine Kopie. Die
Grundlage ist Tag `v1.4.8` (`repo148`), das Vorgehen steht in
[../README.md](../README.md), Abschnitt "Bauen".

| Datei | wirkt auf | was |
|---|---|---|
| `TrackerD.ino.patch` | `src/` | Spurpuffer bei PNACKMD=0, Alarmzyklus, Pad-Holds beim Start |
| `extiButton.cpp.patch` | `src/` | Knopfbehandlung |
| `fix_version.py` | `src/common.h` | `Pro_version` auf die geklonte Basis `v1.4.8` statt des stehen gebliebenen `v1.4.6` |
| `fix_config_uplink.py` | `src/TrackerD.ino` | Konfigrahmen als JSON auf fPort 9, alle 20 min, mit laufendem OTA-Slot |
| `fix_motion_sens.py` | `src/TrackerD.ino` | Weckschwelle 320 mg → 160 mg, Hochachse dazu |
| `fix_aes_len.py` | `lib/arduino-lmic` | **Bibliotheksfehler**: `os_aes()` prueft die Restlaenge in 8 statt 16 Bit |

Der letzte ist kein Eigenbedarf, sondern eine echte Luecke: Rahmen ab 128 Byte
gingen unverschluesselt und ohne gueltigen MIC ueber die Luft. Gemeldet als
[mcci-catena/arduino-lmic#1071](https://github.com/mcci-catena/arduino-lmic/issues/1071),
Korrektur als [#1072](https://github.com/mcci-catena/arduino-lmic/pull/1072).
Solange die nicht drin ist, muss der Patch hier bleiben — er trifft jede
mitgelieferte Kopie der Bibliothek, auch Draginos.
