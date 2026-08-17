"""Relaisstelle Brauneck: ein gemeinsamer Kanal, jeder hoert jeden.

    Nodes am Berg   ─┐
    TrackerD        ─┤
                     ├─►  Pico Brauneck (~1550 m)  ─►  gibt jedes Paket
    DLOS8N Lenggries ─┤        868.125 SF7               genau einmal weiter
    Bad Heilbrunn   ─┘         alle auf demselben Kanal

Alle Teilnehmer arbeiten auf **einer** Frequenz mit **einem** Spreizfaktor.
Nur so kann ein einzelnes Funkmodul jeden hoeren und jeden erreichen -- es kann
immer nur auf einem Kanal lauschen. Das ist dasselbe Flutungsverfahren, das
Meshtastic und Ebytes Broadcast-Modus benutzen.

Die Reichweite reicht dafuer: 14 dBm ergeben auf 10 km Sichtverbindung rund
-93 dBm gegen -123 dBm Empfindlichkeit bei SF7, also etwa 30 dB Reserve. Den
Sprung ins Nachbartal traegt der Bergstandort, nicht die Leistung.

**Eigenecho** verhindert jetzt allein die Marker-Logik -- die fruehere
physikalische Trennung ueber verschiedene Frequenzen und Spreizfaktoren faellt
mit dem gemeinsamen Kanal weg:

* Waehrend des Sendens ist der Empfaenger taub; die eigene Aussendung hoert die
  Station nie unmittelbar.
* Jedes weitergegebene Paket bekommt den Marker ``R<sprung>>``. Kommt es ueber
  eine zweite Relaisstelle zurueck, wird der Zaehler erkannt und ab MAX_HOPS
  nicht mehr weitergereicht.
* Der Dublettenspeicher schluesselt auf den Inhalt **ohne** Marker. Derselbe
  Text geht damit fuenf Minuten lang kein zweites Mal hinaus, ueber welchen
  Umweg er auch ankommt.

Mehrere Relaisstellen sind damit moeglich: aus R1> wird R2> und so fort, bis
MAX_HOPS erreicht ist.

Fernwirken siehe fernwirk.py. Frequenz und Spreizfaktor sind dort bewusst
**nicht** aenderbar -- in einem Einkanalnetz saegt man sich damit den Ast ab,
auf dem man sitzt.
"""
import machine
import utime

import fernwirk
import lora_p2p

# --- Der gemeinsame Kanal -------------------------------------------------
# Eine einzige Quelle der Wahrheit: das Profil steht im Treiber, hier wird es
# nur uebernommen. Frueher standen hier eigene Werte (868.125/SF7/BW125) -- die
# liefen beim Umstieg auf das Ebyte-Profil stillschweigend auseinander, und der
# Repeater lauschte auf einem Kanal, den niemand mehr benutzte.
KANAL_FREQ = lora_p2p.FREQ_HZ
KANAL_SF   = lora_p2p.SF
KANAL_BW   = lora_p2p.BW_HZ
KANAL_LDRO = lora_p2p.LDRO

# --- Rahmenformat ---------------------------------------------------------
# frisch:          IIII>nutzlast          z.B. b"A1B2>POSITION"
# weitergegeben:   RnIIII>nutzlast        z.B. b"R1A1B2>POSITION"
# Befehl/Antwort:  C>... bzw. A>...       (nie weitergegeben)
#
# Eindeutig, weil "R" keine Hexziffer ist und bei C>/A> an zweiter Stelle ">"
# steht, was ebenfalls keine Hexziffer sein kann. Die Ursprungskennung bleibt
# beim Weiterreichen erhalten -- man sieht auch nach drei Spruengen, wer sendet.
ID_LEN = 4
HEX = b"0123456789ABCDEF"

# --- Schleifenschutz ------------------------------------------------------
MARKER = b"R"                   # Praefix "R<sprung>", siehe Rahmenformat
MAX_HOPS = 3                    # danach wird nicht mehr weitergegeben

# --- Ebyte-Rahmen ---------------------------------------------------------
# Ein E22/E90 verpackt selbst und laesst sich das nicht abgewoehnen:
#   0x2C | Kanal | 2 Byte laufende Nummer | NETID | 2 Byte Adresse | Laenge
# dann die Nutzlast, XOR-verweisst mit der Kanalnummer (die in Byte 1 steht).
#
# Ein solcher Rahmen darf **nicht** mit "Rn<kennung>>" versehen werden: der
# Empfaenger liest die ersten acht Byte als Kopf, findet statt 0x2C ein 0x52
# ("R") und verwirft alles. Ebyte-Verkehr wird deshalb unveraendert
# weitergereicht. Gegen Schleifen traegt dort allein der Dublettenspeicher --
# einen Sprungzaehler gibt es in diesem Format nicht, MAX_HOPS greift nicht.
EBYTE_MAGIC = 0x2C
EBYTE_KOPF  = 8


def ist_ebyte(roh):
    """Byte 0 ist die Kennung, Byte 7 die Nutzlastlaenge -- zusammen ein
    belastbares Merkmal, das Textpakete nicht zufaellig erfuellen."""
    return (len(roh) > EBYTE_KOPF
            and roh[0] == EBYTE_MAGIC
            and roh[EBYTE_KOPF - 1] == len(roh) - EBYTE_KOPF)
DEDUP_S = 300                   # gleicher Inhalt fuer 5 min gesperrt
DEDUP_MAX = 24

# --- Sendezeitbudget ------------------------------------------------------
# Sperrzeit = Luftzeit * (100/Prozent - 1), die uebliche konservative Auslegung.
# 868.0-868.6 MHz erlaubt 1 %; bei ~72 ms Luftzeit sind das gut 7 s Sperre.
DUTY = 1.0

# --- Systemtakt -----------------------------------------------------------
# Die Station haengt am Panel ohne Puffer; jedes eingesparte Milliampere senkt
# den Spannungseinbruch unter Last. Der Prozessor wartet ohnehin nur auf den
# Funkchip. Abgetastet: 125/96/64/48/32/24 MHz laufen sauber, bei 18 MHz
# liefert der SPI Muell (Syncword liest a2a2 statt 3444), 12 MHz lehnt
# MicroPython ab. 48 MHz laesst reichlich Abstand zu dieser Kante.
TAKT_HZ = 48000000


class Budget:
    """Haelt die Sperrzeit des Bandes nach."""

    def __init__(self, prozent):
        self.faktor = 100.0 / prozent - 1.0
        self.frei_ab = 0

    def frei(self):
        return utime.ticks_diff(utime.ticks_ms(), self.frei_ab) >= 0

    def wartezeit_s(self):
        return max(0, utime.ticks_diff(self.frei_ab, utime.ticks_ms())) / 1000.0

    def belegen(self, luftzeit_ms):
        self.frei_ab = utime.ticks_add(utime.ticks_ms(),
                                       int(luftzeit_ms * self.faktor))


class Dedup:
    """Merkt sich zuletzt weitergegebene Inhalte, ohne Marker."""

    def __init__(self):
        self.eintraege = {}

    def bekannt(self, schluessel):
        jetzt = utime.ticks_ms()
        for k in [k for k, t in self.eintraege.items()
                  if utime.ticks_diff(jetzt, t) > DEDUP_S * 1000]:
            del self.eintraege[k]
        if schluessel in self.eintraege:
            return True
        if len(self.eintraege) >= DEDUP_MAX:
            del self.eintraege[min(self.eintraege,
                                   key=lambda k: self.eintraege[k])]
        self.eintraege[schluessel] = jetzt
        return False


def _ist_hex(b):
    return len(b) == ID_LEN and all(c in HEX for c in b.upper())


def zerlege(roh):
    """(sprung, absender, nutzlast). sprung 0 = frisch, absender None = ohne."""
    # weitergegeben: R<ziffer><IIII>>
    if (len(roh) > ID_LEN + 3 and roh[0:1] == MARKER
            and 0x30 <= roh[1] <= 0x39
            and roh[2 + ID_LEN:3 + ID_LEN] == b">"
            and _ist_hex(roh[2:2 + ID_LEN])):
        return roh[1] - 0x30, roh[2:2 + ID_LEN], roh[3 + ID_LEN:]
    # frisch: <IIII>>
    if (len(roh) > ID_LEN and roh[ID_LEN:ID_LEN + 1] == b">"
            and _ist_hex(roh[0:ID_LEN])):
        return 0, roh[0:ID_LEN], roh[ID_LEN + 1:]
    # ohne Kennung -- aeltere Sender, trotzdem weitergeben
    return 0, None, roh


def bauen(sprung, absender, nutzlast):
    kennung = absender if absender else b"????"
    return MARKER + bytes([0x30 + sprung]) + kennung + b">" + nutzlast


def _kanal(r):
    r.set_frequency(KANAL_FREQ)
    r.set_modulation(KANAL_SF, KANAL_BW, lora_p2p.CR, KANAL_LDRO)


def run(telemetrie=None, verbose=True, dauer_s=0):
    """dauer_s=0 heisst Dauerbetrieb, sonst Abbruch mit Bilanz."""
    # Takt vor dem Funkchip stellen: clk_peri haengt an clk_sys, ein vorher
    # erzeugtes SPI-Objekt haette die falsche Teilung.
    if machine.freq() != TAKT_HZ:
        machine.freq(TAKT_HZ)
        lora_p2p._radio = None

    r = lora_p2p.radio()
    start = utime.ticks_ms()
    konf = fernwirk.konf_laden()
    if telemetrie is not None:
        konf["telemetrie"] = telemetrie
    budget = Budget(DUTY)
    dedup = Dedup()
    gehoert = weiter = unterdrueckt = 0
    stat = {"start": start, "weiter": 0, "unterdrueckt": 0,
            "dedup": dedup, "reboot": False, "konf_geaendert": False}

    print("Relais Brauneck -- ein Kanal, jeder hoert jeden")
    print("  Kanal : %.3f MHz  SF%d  BW%d  %d dBm  (%.0f %% Sendezeit)"
          % (KANAL_FREQ / 1e6, KANAL_SF, KANAL_BW // 1000,
             konf["out_power"], DUTY))
    print("  Takt  : %d MHz,  hoechstens %d Spruenge"
          % (machine.freq() // 1000000, MAX_HOPS))
    print("  Fernwirken: C>POWER <dBm> | STATUS | RELAY | TELEM | SAVE | REBOOT")

    while True:
        if dauer_s and utime.ticks_diff(utime.ticks_ms(), start) > dauer_s * 1000:
            print("Bilanz: %d gehoert, %d weitergegeben, %d unterdrueckt"
                  % (gehoert, weiter, unterdrueckt))
            return gehoert, weiter, unterdrueckt

        _kanal(r)
        # Bewusst mit Zeitschranke statt endlos: so bleibt die Schleife
        # ansprechbar und kann Budget und Dubletten pflegen.
        got = r.recv(2000)
        if got is None:
            continue
        roh, rssi, snr, crc_kaputt = got
        gehoert += 1

        if crc_kaputt:
            unterdrueckt += 1
            if verbose:
                print("  verworfen: CRC-Fehler, RSSI %.0f" % rssi)
            continue

        # Fernwirkbefehl: ausfuehren, nie weitergeben.
        if roh.startswith(fernwirk.BEFEHL_PRAEFIX):
            stat["unterdrueckt"] = unterdrueckt
            stat["weiter"] = weiter
            stat["konf_geaendert"] = False
            text = fernwirk.ausfuehren(roh, konf, stat)
            # Sofort sichern: die Station laeuft solar und geht abends aus,
            # ungesicherte Werte waeren am naechsten Morgen verloren.
            if stat["konf_geaendert"]:
                fernwirk.konf_sichern(konf)
            print("  Befehl %r -> %s" % (roh, text))
            if budget.frei():
                a = fernwirk.antwort(text, konf.get("id", "B001"))
                r.set_power(konf["out_power"])
                r.send(a)
                budget.belegen(lora_p2p.airtime_ms(len(a), sf=KANAL_SF,
                                                   bw=KANAL_BW))
            if stat["reboot"]:
                utime.sleep_ms(500)
                machine.reset()
            continue

        # Eigene Antwort oder die einer anderen Station: nicht weitergeben.
        if roh.startswith(fernwirk.ANTWORT_PRAEFIX):
            continue

        if not konf["relay_aktiv"]:
            unterdrueckt += 1
            if verbose:
                print("  verworfen: Weitergabe abgeschaltet")
            continue

        ebyte = ist_ebyte(roh)
        if ebyte:
            # unveraendert weiterreichen, siehe EBYTE_MAGIC oben
            n, absender, nutz = 0, None, roh
        else:
            n, absender, nutz = zerlege(roh)
            if n >= MAX_HOPS:
                unterdrueckt += 1
                if verbose:
                    print("  verworfen: %d Spruenge erreicht, von %s"
                          % (n, absender or b"?"))
                continue

        # Schluessel aus Absender und Nutzlast, also ohne Sprungzaehler:
        # derselbe Inhalt geht nicht zweimal hinaus, ueber welchen Umweg auch.
        # Bei Ebyte der ganze Rahmen -- die laufende Nummer darin unterscheidet
        # zwei echte Aussendungen und faengt die Kopie vom Nachbarrelais ab.
        if dedup.bekannt(roh if ebyte else (absender or b"") + nutz):
            unterdrueckt += 1
            if verbose:
                print("  verworfen: Dublette, %r" % roh[:24])
            continue

        if not budget.frei():
            unterdrueckt += 1
            print("  verworfen: Sendezeitbudget, noch %.1f s gesperrt"
                  % budget.wartezeit_s())
            continue

        raus = roh if ebyte else bauen(n + 1, absender, nutz)
        luft = lora_p2p.airtime_ms(len(raus), sf=KANAL_SF, bw=KANAL_BW)
        r.set_power(konf["out_power"])
        ok = r.send(raus)
        budget.belegen(luft)
        weiter += 1 if ok else 0
        stat["weiter"] = weiter
        stat["unterdrueckt"] = unterdrueckt
        print("%s %s  RSSI %.0f SNR %.1f  %.0f ms  %r"
              % ("weiter:" if ok else "TX-FEHLER:",
                 "Ebyte, unveraendert" if ebyte
                 else "von %s Sprung %d" % ((absender or b"ohne").decode(), n + 1),
                 rssi, snr, luft, nutz[:32]))
