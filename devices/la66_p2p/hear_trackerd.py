#!/usr/bin/env python3
"""Hoert der LA66 den TrackerD? Beide Seiten angleichen und Pakete zaehlen.

Der LA66 laeuft mit der P2P-Firmware (v1.2.4) und steht im RX-Modus, der
TrackerD mit der selbst gebauten P2P-Firmware in app1.  Das Skript gleicht die
Funkparameter ab -- der LA66 kennt nur Bandbreiten-Indizes, 62500 Hz gibt es
dort nicht, also zieht der TrackerD auf 125 kHz nach -- und laesst den TrackerD
dann senden, waehrend die LA66-Konsole mitgeschrieben wird.

  ./hear_trackerd.py                 # Einzelpakete + TXTEST-Dauerfeuer
  ./hear_trackerd.py --txtest 20
"""
import argparse
import re
import threading
import time

import serial

LA66_BAUD = 9600
TRACKERD_BAUD = 115200


class Reader(threading.Thread):
    """Liest einen Port dauerhaft leer und stempelt jede Zeile."""

    def __init__(self, ser):
        threading.Thread.__init__(self, daemon=True)
        self.ser = ser
        self.lines = []
        self.running = True
        self.t0 = time.time()

    def run(self):
        buf = b''
        while self.running:
            d = self.ser.read(256)
            if not d:
                continue
            buf += d
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                line = line.strip(b'\r')
                if line:
                    self.lines.append((time.time() - self.t0,
                                       line.decode('ascii', 'replace')))

    def take(self):
        out, self.lines = self.lines, []
        return out

    def stop(self):
        self.running = False
        time.sleep(0.3)


def at(ser, cmd, wait=1.0):
    ser.reset_input_buffer()
    ser.write((cmd + '\r\n').encode())
    t0 = time.time()
    buf = b''
    while time.time() - t0 < wait:
        buf += ser.read(512)
    return buf.decode('ascii', 'replace').strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--la66', default='/dev/ttyUSB0')
    ap.add_argument('--trackerd', default='/dev/ttyACM0')
    ap.add_argument('--bw', default='125000', help='Bandbreite fuer den TrackerD in Hz')
    ap.add_argument('--txtest', type=int, default=10, help='Sekunden Dauerfeuer')
    args = ap.parse_args()

    la = serial.Serial(args.la66, LA66_BAUD, timeout=0.2)
    td = serial.Serial(args.trackerd, TRACKERD_BAUD, timeout=0.2)
    time.sleep(0.4)

    print('=== TrackerD angleichen ===')
    print(at(td, 'AT+BW=' + args.bw))
    cfg = at(td, 'AT+CFG', 1.5)
    print(cfg)

    print('\n=== LA66 ===')
    print(at(la, 'AT+CFG', 2.0))

    rx = Reader(la)
    rx.start()
    time.sleep(0.5)
    rx.take()

    print('\n=== Einzelpakete ===')
    for i in range(3):
        marker = 'LA66HEARSME%d' % i
        resp = at(td, 'AT+SEND=' + marker, 1.0)
        time.sleep(1.5)
        hits = rx.take()
        print('%-14s TrackerD: %-12s  LA66: %s'
              % (marker, resp.replace('\n', ' '),
                 hits if hits else '-- nichts --'))

    print('\n=== Dauerfeuer AT+TXTEST=%d ===' % args.txtest)
    td.reset_input_buffer()
    td.write(('AT+TXTEST=%d\r\n' % args.txtest).encode())
    deadline = time.time() + args.txtest + 4
    got = []
    while time.time() < deadline:
        got.extend(rx.take())
        time.sleep(0.5)
    tdout = td.read(2000).decode('ascii', 'replace').strip()

    rx.stop()
    la.close()
    td.close()

    print('TrackerD: %s' % tdout.replace('\n', ' '))
    print('LA66 hat %d Zeilen empfangen:' % len(got))
    for t, line in got[:60]:
        print('  +%6.2fs  %s' % (t, line))

    rssi = [l for _, l in got if 'RSSI' in l.upper()]
    payload = [l for _, l in got if 'TRACKERD' in l.upper() or 'LA66HEARSME' in l.upper()]
    print('\nErgebnis: %s' % ('GEHOERT' if got else 'NICHTS EMPFANGEN'))
    if payload:
        print('  Nutzlast erkannt: %d Treffer, z.B. %s' % (len(payload), payload[0]))
    if rssi:
        print('  Pegel: %s' % rssi[-1])
    return 0 if got else 1


if __name__ == '__main__':
    raise SystemExit(main())
