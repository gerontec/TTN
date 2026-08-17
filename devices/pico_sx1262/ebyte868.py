"""Gegenstelle zum E90-DTU(900SL33) auf 868.125 MHz.

Anders als beim 400er liegt dieses Geraet genau dort, wo das Waveshare-Board
angepasst ist: gemessener Empfangspegel -12 dBm gegen -78 dBm auf 433 MHz.

Alle Werte an der Luft ausgemessen, nicht aus dem Handbuch:

    Frequenz   868.125 MHz   (Kanal 18, Handbuch: 850.125 + CH * 1M)
    Modulation SF11 / BW500 / LDRO 1
    Syncword   0x55          (Register 0x0740 = 54 54)

**LDRO muss 1 sein.** Mit 0 rastet der Header ein und jede Nutzlast kommt mit
CRC-Fehler an -- derselbe irrefuehrende Fast-Treffer wie beim 400er.

Das Rahmenformat ist dasselbe wie beim 400er, nur mit anderem zweiten
Magic-Byte und der Adresse dieses Geraets (0 statt 65535). Codec und
Pruefsummenregel kommen deshalb aus ebyte433.

Das DTU muss dafuer in **Mode 0** stehen (M0 und M1 beide ON): nur dort ist der
Funk an und der UART transparent. In Mode 2 ist der Funk komplett aus.

    import ebyte868
    ebyte868.senden("hallo")   # erscheint am DTU auf der seriellen Seite
    ebyte868.hoeren()          # mitlesen, was das DTU funkt
"""
import utime

import ebyte433
import lora_p2p

FREQ_HZ = 868125000
SF = 11
BW_HZ = 500000
LDRO = 1
SYNCWORD = 0x55
POWER_DBM = 14          # 868.0-868.6 MHz: 25 mW ERP, 1 % Duty Cycle
MAGIC = b"\x2c\x12"     # der 400er benutzt hier 0x17
# NETID 0 und eigene Adresse 0x0C2B.
#
# Die NETID **muss** 0 bleiben: der E90-Repeater leitet gemessen nur weiter,
# wenn sie mit seiner eigenen uebereinstimmt (3/3 bei 0x00, 0/3 bei allen
# anderen). Die Adresse ist ihm dagegen gleichgueltig.
#
# Die Adresse traegt das Modul als **eigene** Kennung in den Rahmen -- das
# E90-DTU(400SL30) steht auf 65535 und sendet ff ff, das 900SL33 auf 0 und
# sendet 00 00. Der Pico bekommt deshalb eine eigene, damit er im Mitschnitt
# von den anderen Knoten zu unterscheiden ist: 0x0C2B, die letzten vier
# Hexstellen seiner Seriennummer e6626005a75d0c2b. Das ist dieselbe Regel, mit
# der die TrackerD-Firmware ihre Kennung 076C aus der DevEUI ableitet.
#
# Empfaenger muessen dafuer auf 0xFFFF (Monitor) stehen, dann nehmen sie jede
# Absenderadresse an. Ein Empfaenger mit fester Adresse filtert -- siehe
# EBYTE_E90.md.
# --- Adressplan -----------------------------------------------------------
# Das Gruppenkonzept von Ebyte steht im Handbuch der T22U-Serie, 4.1/4.2:
#
#     00 03 | 04 | AA BB CC
#     Ziel    Ziel  Daten
#     adresse kanal
#
# Der **Kanal** grenzt die Gruppe ab, die **Adresse** waehlt ein Mitglied
# darin. Bei Broadcast FF FF geben alle Module auf dem Kanal aus -- eines auf
# einem anderen Kanal schweigt auch dann. Die Adresse im Rahmen ist also stets
# das **Ziel**, nie der Absender; die eigene Adresse des Senders taucht im
# Paket ueberhaupt nicht auf.
#
# Eine Gruppe, weil eine zweite eine zweite Frequenz kostete: 850.125 + Kanal.
# Kanal 18 ist 868.125 MHz, Kanal 19 waere 869.125 und laege ausserhalb von
# 868.0-868.6. Im nutzbaren Unterband ist also kein Platz fuer eine zweite.
#
# Seit 17.08.2026 gilt: **die NETID ist der Gruppenwaehler, genau zwei
# Gruppen.** Die Adresse 0x2201 tragen alle Knoten gemeinsam als Netzschluessel
# -- Einzeladressierung braeuchte den Fixpunkt-Modus, den die Endgeraete nicht
# haben (gemessen: an eine Einzeladresse gerichtete Rahmen kommen im
# Transparentmodus nicht an, nur Rundrufe).
#
#   Kanal 18  = 868.125 MHz, gemeinsame Funkgruppe
#   0x2201    = gemeinsame Adresse aller Knoten
#   NETID 00  = Gruppe diesseits (E22, dell)
#   NETID BB  = Gruppe jenseits (dieser Pico)
#
# --- NETID: die Weiterleitungsregel des Relais ----------------------------
# Davon unabhaengig, und deshalb leicht zu verwechseln: Die NETID ist *keine*
# Gruppe -- laut Handbuch nur ein nachgelagerter Filter mit niedrigerer
# Prioritaet als Broadcast. Sie traegt aber die Regel des E90-Relais.
#
# Der E90 steht im Relaismodus auf ADDH=0x00, ADDL=0xBB. Dort sind ADDH/ADDL
# keine Adressen mehr, sondern das **NETID-Paar**: was auf NETID 0x00 kommt,
# geht nach 0xBB hinaus und umgekehrt (Handbuch 5.3, bidirektional).
#
#   NETID 0x00   E22 und dell -- diesseits
#   NETID 0xBB   dieser Pico  -- jenseits des Relais
#
# Der Pico bleibt deshalb auf 0xBB: nur so traegt das Relais seine Pakete zur
# Gegenseite. Auf 0x00 gesetzt staende er auf derselben Seite wie E22 und dell,
# und die Relaisstrecke waere wirkungslos.
#
# Zuvor stand hier faelschlich "Gruppe BB" -- die Gruppe ist der Kanal, die
# NETID ist die Relaisregel. Zwei Mechanismen, die nebeneinander laufen.
NETID = 0xBB
EIGENE_ADRESSE = 0x2201
BROADCAST = 0xFFFF
ZIEL_VORGABE = EIGENE_ADRESSE


def ziel_adresse(ziel=None):
    """Die drei Kopfbytes NETID, ADDH, ADDL fuer ein Ziel.

    Vorgabe ist **nicht** Broadcast, sondern die gemeinsame Adresse 0x2201.
    Der Grund ist die Prioritaetsregel des Handbuchs: "Network code filtering
    has lower priority than broadcast addresses. Even with differing network
    codes, broadcast data can still be received." Mit FFFF waeren die beiden
    Gruppen also durchlaessig -- die NETID filtert nur, solange die Adresse
    keine Broadcast-Adresse ist.

    Die Adresse ist damit ein gemeinsamer Netzschluessel, die Trennung leistet
    allein die NETID.
    """
    z = ZIEL_VORGABE if ziel is None else ziel
    return bytes([NETID, (z >> 8) & 0xFF, z & 0xFF])


def fuer_uns(roh):
    """Ist dieser Rahmen an uns gerichtet?

    Der Pico ist ein roher SX1262 ohne Ebyte-Firmware -- er hat kein
    Adressregister und hoert erst einmal alles. Damit er sich wie ein
    Gruppenmitglied verhaelt, muss die Zielpruefung hier in Software
    stattfinden: angenommen wird, was an die eigene Adresse geht oder an
    den Rundruf.
    """
    if len(roh) < 8 or roh[0] != 0x2C:
        return False
    ziel = (roh[5] << 8) | roh[6]
    return ziel in (EIGENE_ADRESSE, BROADCAST)


# Rueckwaertskompatibel: rahmen() ohne Argument sendet als Rundruf.
ADRESSE = ziel_adresse()


def rahmen(nutz):
    return ebyte433.rahmen(nutz, magic=MAGIC, adresse=ADRESSE)


def entpacken(roh):
    return ebyte433.entpacken(roh, magic=MAGIC)


def funk():
    r = lora_p2p.SX1262()
    r.begin()
    r.set_frequency(FREQ_HZ)
    r.set_power(POWER_DBM)
    # set_modulation() rechnet LDRO aus der Symboldauer und kaeme auf 0; das
    # DTU sendet mit 1. Erst sf/bw/cr setzen, dann LDRO nachziehen.
    r.set_modulation(SF, BW_HZ, lora_p2p.CR)
    r.cmd([lora_p2p.SET_MODULATION_PARAMS, SF,
           lora_p2p.BW_TABLE[BW_HZ], lora_p2p.CR, LDRO])
    r.set_syncword(SYNCWORD)
    return r


def senden(text="pico", anzahl=1, pause_s=2.0, r=None):
    r = r or funk()
    for i in range(anzahl):
        r.send(rahmen(text))
        print("gesendet: %r" % text)
        if i + 1 < anzahl:
            utime.sleep(pause_s)


def luftbefehl(befehl, r=None, timeout_ms=5000, versuche=6):
    """Registerkommando ueber die Luft schicken (Funkkonfiguration).

    Laut Handbuch: "Command: CF CF + general command", die Antwort kommt als
    "CF CF + general response" zurueck. Ein Formatfehler wird mit FF FF FF
    quittiert. Beispiel aus dem Handbuch:

        CF CF C0 05 01 09   ->   CF CF C1 05 01 09

    Damit laesst sich das DTU konfigurieren, ohne den DIP-Schalter anzufassen.
    Es muss dafuer in Mode 0 stehen -- in Mode 2 ist der Funk aus.

        luftbefehl([0xC1, 0x06, 0x01])              # REG3 lesen
        luftbefehl([0xC0, 0x06, 0x01, 0xE3])        # REG3 dauerhaft schreiben
    """
    r = r or funk()
    nutz = b"\xcf\xcf" + bytes(befehl)
    for _ in range(versuche):
        r.send(rahmen(nutz))
        got = r.recv(timeout_ms=timeout_ms)
        if got is None:
            continue
        antwort = entpacken(got[0])
        if antwort is None:
            continue
        if antwort[:2] == b"\xcf\xcf":
            return antwort[2:]
        if antwort[:3] == b"\xff\xff\xff":
            return b"\xff\xff\xff"          # Formatfehler laut Handbuch
    return None


def hoeren(timeout_ms=0, r=None):
    r = r or funk()
    print("hoere auf %.3f MHz SF%d BW%d LDRO%d Sync 0x%02X"
          % (FREQ_HZ / 1e6, SF, BW_HZ // 1000, LDRO, SYNCWORD))
    while True:
        got = r.recv(timeout_ms=timeout_ms)
        if got is None:
            print("nichts")
            return
        data, rssi, snr, crcbad = got
        nutz = entpacken(data)
        print("RSSI %.0f dBm  SNR %.1f dB  %s  %r"
              % (rssi, snr, "CRC-FEHLER" if crcbad else "CRC ok",
                 nutz if nutz is not None else data))
