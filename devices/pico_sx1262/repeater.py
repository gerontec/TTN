"""Relaisstelle Brauneck: gibt den Krisenkanal aus dem Lenggrieser Tal
ins naechste Tal (Bad Heilbrunn) weiter.

Zwei Richtungen ueber einen Empfangskanal:

    dell --UDP--> DLOS8N Lenggries --868.125 SF7--> Pico --869.525 SF12--> Bad Heilbrunn
    TrackerD ---------------------- 868.125 SF7--> Pico --868.125 SF7---> DLOS8N Lenggries

Der Pico hat nur ein Funkmodul und kann immer nur auf einem Kanal lauschen.
Gateway und TrackerD senden beide auf 868.125 SF7, also entscheidet der Inhalt
ueber die Richtung: was mit "L>" beginnt, kommt aus dem Tal und geht hinaus;
alles Uebrige gilt als Uplink aus dem Feld und geht nach Lenggries.

Eigenecho wird in den beiden Richtungen unterschiedlich verhindert:

**Talwaerts physikalisch.** Ausgang und Eingang unterscheiden sich in Frequenz
*und* Spreizfaktor. Spreizfaktoren sind quasi-orthogonal, ein SF7-Empfaenger
demoduliert SF12 gar nicht -- der Repeater ist fuer diese Aussendung
strukturell taub, ohne dass eine Logik greifen muesste.

**Bergwaerts per Marker.** Der Uplink nach Lenggries geht zwangslaeufig auf
demselben Kanal hinaus, auf dem auch gelauscht wird; ein zweites Funkmodul
gibt es nicht. Waehrend des Sendens ist der Empfaenger ohnehin taub, aber gegen
Umwege ueber eine zweite Relaisstelle traegt jedes weitergegebene Paket einen
Marker mit Sprungzaehler. Was den Marker schon hat, wird nicht noch einmal
weitergegeben. Ein Dublettenspeicher haelt denselben Inhalt zusaetzlich fuer
fuenf Minuten zurueck.

Warum der Ausgang auf 869.525 liegt: das Band 869.4-869.65 MHz erlaubt 500 mW
ERP bei 10 % Sendezeit, waehrend auf 868.125 nur 25 mW bei 1 % zulaessig sind.
Das sind +8 dB Leistung und das zehnfache Zeitbudget. Zusammen mit SF12 statt
SF7 (rund 14 dB empfindlicher) ist das der Unterschied, der ein Tal weiter
traegt.

Preis dafuer: das DLOS8N kann 869.525 nicht mithoeren (radio_1 sitzt auf 868.5
und reicht +/-400 kHz). Damit trotzdem sichtbar bleibt, dass das Relais
arbeitet, schickt es eine kurze Quittung auf dem Eingangskanal zurueck, die im
Gateway-Log auftaucht.

  import repeater
  repeater.run()                 # Dauerbetrieb
  repeater.run(telemetrie=False) # ohne Quittung an das Gateway
"""
import utime
import lora_p2p

# --- Eingang: was das Gateway in Lenggries sendet -------------------------
IN_FREQ, IN_SF, IN_BW = 868125000, 7, 125000

# --- Ausgang: langer Sprung ins naechste Tal ------------------------------
# 869.4-869.65 MHz: 500 mW ERP, 10 % Sendezeit
OUT_FREQ, OUT_SF, OUT_BW = 869525000, 12, 125000
OUT_POWER = 22                  # dBm, Chipmaximum; ERP bleibt unter 500 mW

# --- Richtungskennung -----------------------------------------------------
# Der Pico hat nur ein Funkmodul und kann immer nur auf einem Kanal lauschen.
# Gateway und TrackerD senden beide auf dem Eingangskanal, also muss der Inhalt
# sagen, wohin es weitergeht: alles aus Lenggries traegt "L>", alles Uebrige
# gilt als Uplink aus dem Feld und geht nach Lenggries.
TAL_PRAEFIX = b"L>"

# --- Schleifenschutz ------------------------------------------------------
MARKER = b"R"                   # Praefix "R<sprung>>", z.B. b"R1>"
MAX_HOPS = 2                    # danach wird nicht mehr weitergegeben
DEDUP_S = 300                   # gleicher Inhalt fuer 5 min gesperrt
DEDUP_MAX = 24

# --- Sendezeitbudget ------------------------------------------------------
# Nach jeder Aussendung eine Sperrzeit von Luftzeit * (100/Prozent - 1).
# Das ist die uebliche, konservative Auslegung des Duty Cycle.
OUT_DUTY = 10.0                 # Prozent, Band 869.4-869.65
IN_DUTY = 1.0                   # Prozent, Band 868.0-868.6

TELEM_EVERY = 1                 # Quittung nach jedem n-ten weitergegebenen Paket


class Budget:
    """Haelt die Sperrzeit eines Bandes nach."""

    def __init__(self, prozent):
        self.faktor = 100.0 / prozent - 1.0
        self.frei_ab = 0

    def frei(self):
        return utime.ticks_diff(utime.ticks_ms(), self.frei_ab) >= 0

    def wartezeit_s(self):
        d = utime.ticks_diff(self.frei_ab, utime.ticks_ms())
        return max(0, d) / 1000.0

    def belegen(self, luftzeit_ms):
        self.frei_ab = utime.ticks_add(utime.ticks_ms(),
                                       int(luftzeit_ms * self.faktor))


class Dedup:
    """Merkt sich zuletzt weitergegebene Inhalte."""

    def __init__(self):
        self.eintraege = {}

    def bekannt(self, roh):
        jetzt = utime.ticks_ms()
        for k in [k for k, t in self.eintraege.items()
                  if utime.ticks_diff(jetzt, t) > DEDUP_S * 1000]:
            del self.eintraege[k]
        if roh in self.eintraege:
            return True
        if len(self.eintraege) >= DEDUP_MAX:
            aeltester = min(self.eintraege, key=lambda k: self.eintraege[k])
            del self.eintraege[aeltester]
        self.eintraege[roh] = jetzt
        return False


def hops(nutzlast):
    """Sprungzahl aus dem Marker, 0 wenn keiner da ist."""
    if (len(nutzlast) >= 3 and nutzlast[0:1] == MARKER
            and nutzlast[2:3] == b">" and 0x30 <= nutzlast[1] <= 0x39):
        return nutzlast[1] - 0x30
    return 0


def markieren(nutzlast, n):
    return MARKER + bytes([0x30 + n]) + b">" + nutzlast


def _rx_modus(r):
    r.set_frequency(IN_FREQ)
    r.set_modulation(IN_SF, IN_BW, lora_p2p.CR)


def _tx_modus(r, freq, sf, bw, power):
    r.set_frequency(freq)
    r.set_modulation(sf, bw, lora_p2p.CR)
    r.set_power(power)


def run(telemetrie=True, verbose=True, dauer_s=0):
    """dauer_s=0 heisst Dauerbetrieb, sonst Abbruch mit Bilanz."""
    r = lora_p2p.radio()
    start = utime.ticks_ms()
    aus = Budget(OUT_DUTY)
    ein = Budget(IN_DUTY)
    dedup = Dedup()
    gehoert = weiter = unterdrueckt = 0

    print("Relais Brauneck")
    print("  Eingang : %.3f MHz  SF%d  BW%d" % (IN_FREQ / 1e6, IN_SF, IN_BW // 1000))
    print("  Ausgang : %.3f MHz  SF%d  BW%d  %d dBm  (%.0f %% Sendezeit)"
          % (OUT_FREQ / 1e6, OUT_SF, OUT_BW // 1000, OUT_POWER, OUT_DUTY))
    print("  Luftzeit je Paket ausgangsseitig: %.0f ms bei 30 B"
          % lora_p2p.airtime_ms(30, sf=OUT_SF, bw=OUT_BW))

    while True:
        if dauer_s and utime.ticks_diff(utime.ticks_ms(), start) > dauer_s * 1000:
            print("Bilanz: %d gehoert, %d weitergegeben, %d unterdrueckt"
                  % (gehoert, weiter, unterdrueckt))
            return gehoert, weiter, unterdrueckt
        _rx_modus(r)
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

        n = hops(roh)
        if n:
            # Traegt bereits unseren Marker: entweder unsere eigene Aussendung
            # ueber einen Umweg, oder die einer zweiten Relaisstelle.
            unterdrueckt += 1
            if verbose:
                print("  verworfen: schon %d Sprung(e), %r" % (n, roh[:24]))
            continue

        if dedup.bekannt(roh):
            unterdrueckt += 1
            if verbose:
                print("  verworfen: Dublette, %r" % roh[:24])
            continue

        # Richtung bestimmen: aus dem Tal hinaus, oder vom Feld nach Lenggries.
        talwaerts = roh.startswith(TAL_PRAEFIX)
        if talwaerts:
            ziel, budget = (OUT_FREQ, OUT_SF, OUT_BW, OUT_POWER), aus
            wohin = "-> Bad Heilbrunn"
        else:
            ziel, budget = (IN_FREQ, IN_SF, IN_BW, 14), ein
            wohin = "-> Lenggries"

        if not budget.frei():
            unterdrueckt += 1
            print("  verworfen: Sendezeitbudget %s, noch %.1f s gesperrt"
                  % (wohin, budget.wartezeit_s()))
            continue

        raus = markieren(roh, 1)
        luft = lora_p2p.airtime_ms(len(raus), sf=ziel[1], bw=ziel[2])
        _tx_modus(r, *ziel)
        ok = r.send(raus)
        budget.belegen(luft)
        weiter += 1 if ok else 0
        print("%s %s RSSI %.0f SNR %.1f  %.3f MHz SF%d %d dBm, %.0f ms, %r"
              % ("weiter:" if ok else "TX-FEHLER:", wohin, rssi, snr,
                 ziel[0] / 1e6, ziel[1], ziel[3], luft, roh[:32]))

        # Quittung nur talwaerts: dorthin kann das Gateway nicht mithoeren,
        # der Uplink nach Lenggries taucht dagegen selbst im Gateway-Log auf.
        if telemetrie and ok and talwaerts and weiter % TELEM_EVERY == 0 and ein.frei():
            quittung = markieren(b"BRAUNECK %d/%d rssi%d" % (weiter, gehoert,
                                                            int(rssi)), 9)
            lq = lora_p2p.airtime_ms(len(quittung), sf=IN_SF, bw=IN_BW)
            _tx_modus(r, IN_FREQ, IN_SF, IN_BW, 14)
            r.send(quittung)
            ein.belegen(lq)
            if verbose:
                print("  Quittung ans Gateway: %r" % quittung)
