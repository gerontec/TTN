#!/usr/bin/env python3
"""Kleine AT-Konsole fuer LA66 (9600) und TrackerD-P2P (115200).

  ./at.py 'AT?'                       # LA66 an /dev/ttyUSB0
  ./at.py -p /dev/ttyACM0 -b 115200 'AT+CFG'
  ./at.py 'AT+CFG' 'AT+RXMODE=1'      # mehrere Kommandos nacheinander
  ./at.py -l 20                       # nur 20 s mitlesen
"""
import argparse
import serial
import sys
import time


def at(ser, cmd, wait):
    ser.reset_input_buffer()
    ser.write((cmd + '\r\n').encode())
    t0 = time.time()
    buf = b''
    while time.time() - t0 < wait:
        buf += ser.read(512)
    return buf.decode('ascii', 'replace')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmds', nargs='*')
    ap.add_argument('-p', '--port', default='/dev/ttyUSB0')
    ap.add_argument('-b', '--baud', type=int, default=9600)
    ap.add_argument('-w', '--wait', type=float, default=2.0)
    ap.add_argument('-l', '--listen', type=float, default=0,
                    help='nach den Kommandos n Sekunden mitlesen')
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    time.sleep(0.2)
    for cmd in args.cmds:
        print('>>> %s' % cmd)
        print(at(ser, cmd, args.wait).strip())
        print()
    if args.listen:
        print('--- lausche %.0f s ---' % args.listen)
        t0 = time.time()
        while time.time() - t0 < args.listen:
            d = ser.read(512)
            if d:
                sys.stdout.write(d.decode('ascii', 'replace'))
                sys.stdout.flush()
    ser.close()


if __name__ == '__main__':
    main()
