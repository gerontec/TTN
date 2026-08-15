#!/usr/bin/env python3
"""Sucht die SF/BW-Kombination, auf der TrackerD-P2P und EByte E22 sich hoeren.

EByte gibt statt Spreading Factor und Bandbreite nur eine "Air Rate" heraus;
im Handbuch steht dazu nur die Fussnote "2.4kbps@SF11". Statt zu raten laesst
dieses Skript den E22 dauernd senden und dreht auf der TrackerD-Seite SF und
BW durch, bis Pakete ankommen. Danach dieselbe Runde in Gegenrichtung.

Voraussetzung: E22 im Uebertragungsmodus (LED gruen), Kanal 18 = 868.125 MHz,
serielle Rate 9600 - also genau die Konfiguration aus e22.py.

    ./p2p_sweep.py                       # beide Richtungen, alle Kombinationen
    ./p2p_sweep.py --sf 11 --bw 500000   # nur eine Kombination pruefen
"""
import argparse
import serial
import threading
import time

PAYLOAD = b'E22TOTRACKERD\n'


class Reader(threading.Thread):
    """Liest einen Port dauerhaft leer und sammelt, was kommt."""

    def __init__(self, ser):
        threading.Thread.__init__(self, daemon=True)
        self.ser = ser
        self.buf = b''
        self.running = True

    def run(self):
        while self.running:
            d = self.ser.read(512)
            if d:
                self.buf += d

    def take(self):
        b, self.buf = self.buf, b''
        return b

    def stop(self):
        self.running = False
        time.sleep(0.3)


def at(ser, cmd, wait=0.4):
    ser.write((cmd + '\r\n').encode())
    time.sleep(wait)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trackerd', default='/dev/ttyACM0')
    ap.add_argument('--e22', default='/dev/ttyUSB1')
    ap.add_argument('--freq', default='868.125')
    ap.add_argument('--sf', type=int, default=None)
    ap.add_argument('--bw', type=int, default=None)
    ap.add_argument('--wait', type=float, default=3.0)
    args = ap.parse_args()

    bws = [args.bw] if args.bw else [500000, 250000, 125000]
    sfs = [args.sf] if args.sf else [12, 11, 10, 9, 8, 7]

    td = serial.Serial(args.trackerd, 115200, timeout=0.3)
    e22 = serial.Serial(args.e22, 9600, timeout=0.3)
    tdr, er = Reader(td), Reader(e22)
    tdr.start()
    er.start()
    time.sleep(0.5)

    at(td, 'AT+FRE=%s' % args.freq)
    at(td, 'AT+SYNCWORD=0x12')
    at(td, 'AT+CR=1')
    at(td, 'AT+CRC=1')
    at(td, 'AT+RX=1')
    tdr.take()

    hits = []
    print('=== Richtung E22 -> TrackerD (E22 sendet, TrackerD hoert)')
    for bw in bws:
        for sf in sfs:
            at(td, 'AT+BW=%d' % bw)
            at(td, 'AT+SF=%d' % sf)
            tdr.take()
            e22.write(PAYLOAD)
            time.sleep(args.wait)
            e22.write(PAYLOAD)
            time.sleep(args.wait)
            out = tdr.take().decode(errors='replace')
            rx = [l for l in out.splitlines() if l.startswith('+RX:')]
            print('BW%-7d SF%-2d %s' % (bw, sf, rx[0] if rx else '-'))
            if rx:
                hits.append((bw, sf, 'E22->TrackerD'))

    print()
    print('=== Richtung TrackerD -> E22 (TrackerD sendet, E22 hoert)')
    for bw in bws:
        for sf in sfs:
            at(td, 'AT+BW=%d' % bw)
            at(td, 'AT+SF=%d' % sf)
            er.take()
            at(td, 'AT+SEND=TRACKERDTOE22', wait=0.3)
            time.sleep(args.wait)
            at(td, 'AT+SEND=TRACKERDTOE22', wait=0.3)
            time.sleep(args.wait)
            got = er.take()
            print('BW%-7d SF%-2d %s' % (bw, sf, repr(got) if got else '-'))
            if got:
                hits.append((bw, sf, 'TrackerD->E22'))

    tdr.stop()
    er.stop()
    td.close()
    e22.close()

    print()
    if hits:
        print('Treffer:')
        for bw, sf, d in hits:
            print('  BW %d Hz, SF%d  (%s)' % (bw, sf, d))
    else:
        print('Kein Treffer - Frequenz, Kanal oder E22-Modus pruefen.')


if __name__ == '__main__':
    main()
