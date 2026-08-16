"""Gegenstelle zum E90-DTU(400SL30)E auf 433.125 MHz.

Das E90 ist ein 400er Modul und kommt nicht auf die 868.125 MHz, auf denen die
Brauneck-Strecke laeuft. Getroffen wird sich deshalb auf dem E90-Kanal 23:

    410.125 MHz + 23 * 1 MHz = 433.125 MHz

Alle Parameter unten sind an der Luft ausgemessen, nicht aus dem Handbuch
uebernommen -- das Handbuch in ~/Dokumente gehoert zum 900er Modell und passt
weder in der Frequenz noch in der Ratentabelle.

Modulation
----------
Gefunden ueber den PreambleDetected-Interrupt, der schon vor der
Syncword-Pruefung feuert und deshalb die Modulation unabhaengig vom Syncword
verraet. Treffer gab es bei SF7/BW500 und SF6/BW250 -- beide haben dieselbe
Chirprate (BW/2^SF = 3906.25), sind fuer den Praeambeldetektor also nicht zu
unterscheiden. Nur SF7/BW500 rastet dann auch auf den Header ein.

**LDRO muss 1 sein.** Mit dem aus der Symboldauer berechneten LDRO=0 rastet der
Header zwar ein, die Nutzlast kommt aber durchweg mit CRC-Fehler an. Das ist
die Falle an dieser Strecke: es sieht nach fast-richtig aus und ist falsch.

Syncword 0x58 (Register 0x54/0x84). Gefunden durch Absuchen von 0x00-0x7F;
0x58-0x5F liefern alle einen Treffer, weil nur das erste Registerbyte
ausgewertet wird.

Rahmen
------
    2c 17 XX YY 00 ff ff LL | Nutzlast XOR 0x12

    2c 17    fest
    XX       XOR ueber die Klartext-Nutzlast, danach ^ 0xA0
    YY       XX ^ 0xA1
    00 ff ff Adresse 0xFFFF (Monitor)
    LL       Laenge der Nutzlast

Die XX/YY-Regel ist an mehreren Frames gegengeprueft, u.a. am MAC-Beacon des
E90 (Nutzlast 78 ee 4c d7 ea 07, XOR 0xE0, XX 0x40). Ein Frame mit falschem XX
wird vom E90 verworfen -- ein wortgleicher Replay dagegen angenommen.

Was das E90 dafuer koennen muss (siehe python/e90_pico_setup.py):
Kanal 23, Adresse 65535, transparent. Die Luftrate stellt SF/BW; welcher Index
zu SF7/BW500 gehoert, steht in e90_pico_setup.py.

    import ebyte433
    ebyte433.hoeren()          # mitlesen, was aus dem E90-Sockel rausgeht
    ebyte433.senden("hallo")   # erscheint am E90 auf TCP 8886
"""
import utime

import lora_p2p

FREQ_HZ = 433125000
SF = 7
BW_HZ = 500000
LDRO = 1
SYNCWORD = 0x58
POWER_DBM = 10          # 433.050-434.790 MHz: 10 mW ERP, nicht die 14 aus lora_p2p
ADRESSE = b"\x00\xff\xff"
XOR = 0x12
KOPF_MAGIC = b"\x2c\x17"


def pruefbyte(nutz):
    """XX aus der Klartext-Nutzlast. YY ist XX ^ 0xA1."""
    x = 0
    for b in nutz:
        x ^= b
    return (x ^ 0xA0) & 0xFF


def rahmen(nutz):
    """Ebyte-Frame aus einer Klartext-Nutzlast bauen."""
    if isinstance(nutz, str):
        nutz = nutz.encode()
    xx = pruefbyte(nutz)
    kopf = KOPF_MAGIC + bytes([xx, xx ^ 0xA1]) + ADRESSE + bytes([len(nutz)])
    return kopf + bytes(b ^ XOR for b in nutz)


def entpacken(roh):
    """Klartext aus einem empfangenen Frame, oder None wenn es keiner ist."""
    if len(roh) < 9 or roh[0:2] != KOPF_MAGIC:
        return None
    laenge = roh[7]
    nutz = bytes(b ^ XOR for b in roh[8:8 + laenge])
    if roh[2] != pruefbyte(nutz):
        return None
    return nutz


def funk():
    """SX1262 auf den E90-Kanal stellen."""
    r = lora_p2p.SX1262()
    r.begin()
    r.set_frequency(FREQ_HZ)
    r.set_power(POWER_DBM)
    # set_modulation() rechnet LDRO aus der Symboldauer und kaeme hier auf 0;
    # das E90 sendet aber mit LDRO=1. Erst set_modulation fuer sf/bw/cr, dann
    # die Modulationsparameter mit dem richtigen LDRO nachziehen.
    r.set_modulation(SF, BW_HZ, lora_p2p.CR)
    r.cmd([lora_p2p.SET_MODULATION_PARAMS, SF,
           lora_p2p.BW_TABLE[BW_HZ], lora_p2p.CR, LDRO])
    r.set_syncword(SYNCWORD)
    return r


def senden(text="pico", anzahl=1, pause_s=1.5, r=None):
    r = r or funk()
    for i in range(anzahl):
        r.send(rahmen(text))
        print("gesendet: %r" % text)
        if i + 1 < anzahl:
            utime.sleep(pause_s)


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
