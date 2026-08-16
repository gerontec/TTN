"""Gegenstelle zum E90-DTU(900SL33) auf 868.125 MHz.

Anders als beim 400er liegt dieses Geraet genau dort, wo das Waveshare-Board
angepasst ist: gemessener Empfangspegel -12 dBm gegen -78 dBm auf 433 MHz.

Alle Werte an der Luft ausgemessen, nicht aus dem Handbuch:

    Frequenz   868.125 MHz   (Kanal 18, Handbuch: 850.125 + CH * 1M)
    Modulation SF11 / BW500 / LDRO 1
    Syncword   0x58          (Register 0x0740 = 54 84)

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
SYNCWORD = 0x58
POWER_DBM = 14          # 868.0-868.6 MHz: 25 mW ERP, 1 % Duty Cycle
MAGIC = b"\x2c\x12"     # der 400er benutzt hier 0x17
ADRESSE = b"\x00\x00\x00"   # NETID 0, Adresse 0x0000


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
