#!/usr/bin/env python3
"""Ping-Pong-Test gegen die RadioLib-Firmware des Picos.

Der E22 am USB sendet N Pakete "A n"; der Pico (Waveshare SX1262 am SPI,
RadioLib-Firmware) hoert mit, beantwortet jedes Paket mit einem Zeitstempel
(PONG) und gibt alles ueber USB aus. Gezaehlt wird:

  1. RX-Zeilen des Picos        -- hat er die E22-Pakete gehoert?
  2. PONGs am E22-UART          -- kommt die Antwort des Picos zurueck?

    python3 pico_c_pingpong.py            # 5 Pakete
    python3 pico_c_pingpong.py -n 10 -i 3 # laenger, anderer Takt
"""
import argparse
import os
import re
import select
import sys
import threading
import termios
import time
import tty

PICO_PORT = "/dev/ttyACM0"
E22_PORT = "/dev/ttyUSB0"
E22_BAUD = termios.B9600


def port_oeffnen(port, baud=None):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    if baud is not None:
        attrs = termios.tcgetattr(fd)
        attrs[4] = attrs[5] = baud
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def leser(stopp, zeilen, roh, fd, markierung):
    # Der Pico schreibt mit Zeilenumbruch, der E22 schickt die Nutzlast roh
    # ohne \n. Deshalb beides sammeln: Zeilen fuer die Anzeige, Rohbytes
    # fuer die Trefferzaehlung.
    puffer = b""
    while not stopp.is_set():
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            b = os.read(fd, 4096)
            if b:
                roh[markierung] = roh.get(markierung, b"") + b
                puffer += b
                while b"\n" in puffer:
                    zeile, puffer = puffer.split(b"\n", 1)
                    text = zeile.decode("utf-8", "replace").strip()
                    if text:
                        zeilen.append((markierung, text))
                        print("[%s] %s" % (markierung, text))
                        sys.stdout.flush()
    if puffer:                        # Rest ohne Zeilenumbruch (E22)
        text = puffer.decode("utf-8", "replace").strip()
        if text:
            zeilen.append((markierung, text))
            print("[%s] %s" % (markierung, text))
            sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", "--anzahl", type=int, default=5)
    ap.add_argument("-i", "--intervall", type=float, default=2.0)
    args = ap.parse_args()

    if not os.path.exists(PICO_PORT) or not os.path.exists(E22_PORT):
        sys.exit("Geraete fehlen: erwartet %s und %s" % (PICO_PORT, E22_PORT))

    pico_fd = port_oeffnen(PICO_PORT)
    e22_fd = port_oeffnen(E22_PORT, E22_BAUD)
    stopp = threading.Event()
    zeilen = []
    roh = {}
    t1 = threading.Thread(target=leser, args=(stopp, zeilen, roh, pico_fd,
                                              "PICO"), daemon=True)
    t2 = threading.Thread(target=leser, args=(stopp, zeilen, roh, e22_fd,
                                              "E22 "), daemon=True)
    t1.start(); t2.start()
    time.sleep(2)                     # Puffer leeren sich, Firmware gibt Banner

    for i in range(args.anzahl):
        os.write(e22_fd, ("A %d\n" % i).encode())
        print("[SEND] A %d" % i)
        sys.stdout.flush()
        if i + 1 < args.anzahl:
            time.sleep(args.intervall)

    time.sleep(8)                     # Nachlauf: PONGs kommen erst +2,5/+3 s
    stopp.set()
    t1.join(timeout=3); t2.join(timeout=3)

    rx = sum(1 for m, t in zeilen if m == "PICO" and t.startswith("RX #"))
    geplant = sum(1 for m, t in zeilen if m == "PICO" and "geplant" in t)
    e22_roh = roh.get("E22 ", b"")
    pong_e22 = e22_roh.count(b"PONG")
    print("\nErgebnis: %d/%d Pakete vom Pico gehoert, "
          "%d Antworten eingeplant (2 je Paket), %d PONGs am E22-UART angekommen"
          % (rx, args.anzahl, geplant, pong_e22))
    if e22_roh:
        print("E22-Rohbytes (%d): %r" % (len(e22_roh), e22_roh[:200]))
    sys.exit(0 if rx == args.anzahl and pong_e22 > 0 else 1)


if __name__ == "__main__":
    main()
