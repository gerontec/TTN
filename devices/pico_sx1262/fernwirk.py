"""Fernwirken der Relaisstelle Brauneck ueber LoRa selbst.

Der Pico hat kein WLAN (es ist ein RP2040, kein Pico W -- `network` fehlt), auf
dem Berg gibt es also weder SSH noch OTA. Der einzige Rueckkanal ist der Funk,
auf dem das Relais ohnehin arbeitet. Fuer ein Krisensystem ist das sogar der
richtige Weg: er traegt genau dann, wenn alles andere ausgefallen ist.

Bewusst ohne Authentisierung gehalten -- wer in Funkreichweite ist, koennte das
Relais umstellen. Das ist eine Abwaegung zugunsten der Einfachheit.

Rahmenformat, beides schlichter Text:

    Befehl:   C>POWER 20
    Antwort:  A>POWER 20 dBm

Befehle:

    POWER <dBm>       Sendeleistung talwaerts, 2..22   (der wichtigste)
    SF <7..12>        Spreizfaktor talwaerts
    FREQ <MHz>        Sendefrequenz talwaerts, z.B. 869.525
    STATUS            Zaehler, Laufzeit, Konfiguration
    RELAY 0|1         Weitergabe aus- oder einschalten
    TELEM 0|1         Quittungen aus- oder einschalten
    SAVE              Konfiguration dauerhaft sichern
    REBOOT            Neustart des Boards
    PING              lebt die Station?

Geaenderte Werte wirken sofort **und werden sofort nach /relais.json
gesichert**. Das ist kein Luxus: die Station laeuft rein solar und geht jeden
Abend aus. Ohne automatisches Sichern waere eine per Funk gesetzte
Sendeleistung am naechsten Morgen wieder weg. `SAVE` bleibt fuer den Fall, dass
man den Stand ausdruecklich bestaetigen will.
"""
import json

KONF_DATEI = "/relais.json"
BEFEHL_PRAEFIX = b"C>"
ANTWORT_PRAEFIX = b"A>"

STANDARD = {
    "out_freq": 869525000,
    "out_sf": 12,
    "out_power": 22,
    "telemetrie": True,
    "relay_aktiv": True,
}


def konf_laden():
    k = dict(STANDARD)
    try:
        with open(KONF_DATEI) as f:
            k.update(json.load(f))
    except (OSError, ValueError):
        pass
    return k


def konf_sichern(k):
    try:
        with open(KONF_DATEI, "w") as f:
            json.dump(k, f)
        return True
    except OSError:
        return False


def ausfuehren(roh, konf, stat):
    """roh ist der ganze Rahmen inklusive "C>". Gibt den Antworttext zurueck."""
    import utime

    befehl = roh[len(BEFEHL_PRAEFIX):].strip()
    teile = befehl.split(b" ", 1)
    name = teile[0].upper()
    wert = teile[1].decode().strip() if len(teile) > 1 else None

    if name == b"POWER":
        try:
            p = int(wert)
        except (TypeError, ValueError):
            return "POWER: Zahl erwartet"
        if not 2 <= p <= 22:
            return "POWER: nur 2..22 dBm"
        konf["out_power"] = p
        stat["konf_geaendert"] = True
        return "POWER %d dBm" % p

    if name == b"SF":
        try:
            s = int(wert)
        except (TypeError, ValueError):
            return "SF: Zahl erwartet"
        if not 7 <= s <= 12:
            return "SF: nur 7..12"
        konf["out_sf"] = s
        stat["konf_geaendert"] = True
        return "SF %d" % s

    if name == b"FREQ":
        try:
            f = float(wert)
        except (TypeError, ValueError):
            return "FREQ: MHz erwartet"
        if not 863.0 <= f <= 870.0:
            return "FREQ: nur 863..870 MHz"
        konf["out_freq"] = int(f * 1e6)
        stat["konf_geaendert"] = True
        return "FREQ %.3f MHz" % f

    if name == b"STATUS":
        return "auf%d ab%d unt%d %ds %s SF%d %ddBm %.3f tel%d" % (
            stat["weiter_auf"], stat["weiter_ab"], stat["unterdrueckt"],
            utime.ticks_diff(utime.ticks_ms(), stat["start"]) // 1000,
            "an" if konf["relay_aktiv"] else "AUS",
            konf["out_sf"], konf["out_power"], konf["out_freq"] / 1e6,
            1 if konf["telemetrie"] else 0)

    if name == b"RELAY" and wert in ("0", "1"):
        konf["relay_aktiv"] = wert == "1"
        stat["konf_geaendert"] = True
        return "RELAY %s" % ("an" if konf["relay_aktiv"] else "aus")

    if name == b"TELEM" and wert in ("0", "1"):
        konf["telemetrie"] = wert == "1"
        stat["konf_geaendert"] = True
        return "TELEM %s" % wert

    if name == b"SAVE":
        return "gesichert" if konf_sichern(konf) else "SAVE fehlgeschlagen"

    if name == b"REBOOT":
        stat["reboot"] = True
        return "Neustart"

    if name == b"PING":
        return "PONG"

    return "unbekannt: %s" % name.decode()


def antwort(text):
    return ANTWORT_PRAEFIX + text.encode()
