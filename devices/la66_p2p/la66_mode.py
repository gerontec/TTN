#!/usr/bin/env python3
"""LA66 zwischen LoRaWAN und LoRa-P2P umschalten.

Warum das Umflashen ist und kein Slot-Wechsel: der ASR6601 hat genau **einen**
Applikationsbereich ab 0x0800D000, und der Dragino-Bootloader springt
bedingungslos dorthin.  Ein zweiter Slot brächte auch nichts -- beide
Dragino-Images sind fest auf 0x0800D000 gelinkt (Reset-Vektor 0x0800F00D bzw.
0x0800F30D, absolute Adressen mitten im 0x0800D000-Bild).  Aus einer anderen
Adresse gestartet laufen sie nicht.  Ohne Quellen und Re-Link ist echtes
Dual-Boot also nicht zu haben.

Was geht: der Wechsel dauert ueber den Bootloader-Weg rund fuenf Sekunden, also
wird schlicht das jeweils andere Image geschrieben -- derselbe Gedanke wie
switch_app.py beim TrackerD, nur ohne otadata.

Die Kombi-Images (Bootloader + App) sind nachweislich reine Aneinanderreihung:
`…_withbootloder.bin[0xD000:]` ist byte-identisch mit dem eigenstaendigen
`…_application.bin`.  Deshalb kann auch die LoRaWAN-App aus ihrem Kombi-Image
herausgeschnitten und ueber die AT-UART geflasht werden -- kein BOOT<->RX noetig.

  ./la66_mode.py status
  ./la66_mode.py p2p
  ./la66_mode.py lorawan
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from la66_uart_flash import (LA66UartFlasher, APP_ADDRESS, BAUD_AT,  # noqa: E402
                             Timeout)

APP_OFFSET = 0xD000     # Start der App im Kombi-Image

MODES = {
    'p2p': {
        'image': 'LA66_P2P_v1.2.4_application.bin',
        'combo': 'LA66_P2P_v1.2.4_application_withbootloder.bin',
        'marker': 'P2P Firmware',
    },
    'lorawan': {
        'image': None,   # es gibt nur das Kombi-Image
        'combo': 'LA66_LoRaWAN_v1.3_EU868_with_bootloader.bin',
        'marker': 'LA66 Device',
    },
}


def find(basedir, name):
    for cand in (os.path.join(basedir, name),
                 os.path.join(basedir, 'firmware', name)):
        if os.path.exists(cand):
            return cand
    return None


def app_image(basedir, mode, workdir):
    """Liefert ein reines App-Image fuer 0x0800D000, notfalls aus dem Kombi."""
    spec = MODES[mode]
    if spec['image']:
        p = find(basedir, spec['image'])
        if p:
            return p
    combo = find(basedir, spec['combo'])
    if not combo:
        raise SystemExit('Kein Image fuer "%s" gefunden (%s / %s)'
                         % (mode, spec['image'], spec['combo']))
    data = open(combo, 'rb').read()
    if len(data) <= APP_OFFSET:
        raise SystemExit('%s ist kleiner als 0x%X, kein Kombi-Image'
                         % (combo, APP_OFFSET))
    out = os.path.join(workdir, os.path.basename(combo)
                       .replace('.bin', '_app_0x0800D000.bin'))
    with open(out, 'wb') as f:
        f.write(data[APP_OFFSET:])
    print('  App aus Kombi geschnitten: %s (%d Bytes ab 0x%X)'
          % (os.path.basename(out), len(data) - APP_OFFSET, APP_OFFSET))
    return out


def read_banner(port, seconds=6, tries=4):
    """ATZ ausloesen und die Startmeldung einsammeln."""
    import serial
    s = serial.Serial(port, BAUD_AT, timeout=0.3)
    time.sleep(0.3)
    try:
        for _ in range(tries):
            s.reset_input_buffer()
            s.write(b'ATZ\r\n')
            t0 = time.time()
            blob = b''
            while time.time() - t0 < seconds:
                blob += s.read(256)
            if b'bootloader' in blob:
                return blob.decode('ascii', 'replace')
            time.sleep(0.8)
        return blob.decode('ascii', 'replace')
    finally:
        s.close()


RF_TRACKERD = ('AT+FRE=868.125,868.125', 'AT+SF=7,7', 'AT+BW=0,0',
               'AT+CR=1,1', 'AT+PREAMBLE=8,8', 'AT+CRC=1,1')


def apply_rf(port, cmds=RF_TRACKERD):
    """Funkparameter setzen -- ein Flash setzt sie auf Werk zurueck."""
    import serial
    print('\nFunkparameter setzen (Werkszustand ist 868.700 MHz / SF12):')
    s = serial.Serial(port, BAUD_AT, timeout=0.3)
    time.sleep(0.3)
    try:
        for cmd in cmds:
            s.reset_input_buffer()
            s.write((cmd + '\r\n').encode())
            time.sleep(1.0)
            resp = s.read(300).decode('ascii', 'replace').strip().replace('\n', ' ')
            print('  %-26s -> %s' % (cmd, resp))
    finally:
        s.close()
    print('  ATZ (AT+BW greift erst nach Reset)')


def detect(port):
    banner = read_banner(port)
    for mode, spec in MODES.items():
        if spec['marker'] in banner:
            return mode, banner
    return None, banner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=('status', 'p2p', 'lorawan'))
    ap.add_argument('-p', '--port', default='/dev/ttyUSB0')
    ap.add_argument('-d', '--dir', default=os.path.dirname(os.path.abspath(__file__)),
                    help='Verzeichnis mit den Images bzw. firmware/')
    ap.add_argument('-f', '--force', action='store_true',
                    help='auch flashen, wenn der Modus schon stimmt')
    ap.add_argument('--apply-rf', action='store_true',
                    help='nach dem Wechsel auf p2p die TrackerD-Parameter setzen '
                         '(868.125 MHz, SF7, BW 125 kHz, CR 4/5, Praeambel 8, CRC an)')
    args = ap.parse_args()

    current, banner = detect(args.port)
    print('Aktuell: %s' % (current or 'unbekannt'))
    for line in banner.splitlines():
        line = line.strip()
        if line:
            print('  | %s' % line)

    if args.mode == 'status':
        return 0 if current else 1

    if current == args.mode and not args.force:
        print('\nSchon im Modus "%s" -- nichts zu tun (--force erzwingt).' % args.mode)
        return 0

    workdir = os.path.join(args.dir, 'build')
    os.makedirs(workdir, exist_ok=True)
    image = app_image(args.dir, args.mode, workdir)

    print('\nSchalte auf "%s": %s -> 0x%08X'
          % (args.mode, os.path.basename(image), APP_ADDRESS))
    f = LA66UartFlasher(args.port)
    try:
        f.reset_la66()
        f.enter_prog_mode()
        time.sleep(0.5)
        f.ser.baudrate = 921600
        f.sync()
        f.download(APP_ADDRESS, image)
    except Timeout as e:
        print('FEHLER: %s' % e)
        f.ser.close()
        return 1
    for line in f.read_boot_output():
        print('  | %s' % line)
    f.ser.close()

    if args.apply_rf and args.mode == 'p2p':
        apply_rf(args.port)

    time.sleep(1.0)
    now, _ = detect(args.port)
    print('\nJetzt: %s' % (now or 'unbekannt'))
    return 0 if now == args.mode else 1


if __name__ == '__main__':
    sys.exit(main())
