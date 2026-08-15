#!/usr/bin/env python3
"""Flash a Dragino LA66 USB adapter under Linux.

Der Dragino-OTA-Bootloader laeuft mit 9600 Baud und oeffnet sein Sync-Fenster
nur direkt nach einem Reset.  DTR/RTS sind auf dem USB-Adapter nicht mit
BOOT/RST verdrahtet, das hw_reset() aus tremo_loader.py laeuft also ins Leere.
Statt dessen: ATZ ueber die AT-Konsole schicken und sofort Sync-Pakete
hinterherwerfen, bis der Bootloader antwortet.

  ./la66_flash.py LA66_P2P_v1.2.4_application_withbootloder.bin
  ./la66_flash.py -a 0x0800D000 LA66_P2P_v1.2.4_application.bin
"""
import argparse
import os
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tremo_loader import TremoLoader, CmdException  # noqa: E402

AT_BAUD = 9600          # AT-Konsole und Bootloader
FLASH_BASE = 0x08000000  # Bootloader
APP_BASE = 0x0800D000    # Applikation hinter dem Bootloader


class LA66Loader(TremoLoader):
    def __init__(self, port):
        TremoLoader.__init__(self, port, AT_BAUD)

    def _try_sync(self, baud, seconds):
        self.ser.baudrate = baud
        self.ser.timeout = 0.3
        self.ser.reset_input_buffer()
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                self.sync()
                return True
            except Exception:
                pass
        return False

    def connect_rom(self, timeout=4):
        """ROM-Bootloader (BOOT auf RX gebrueckt beim Einstecken)."""
        for baud in (921600, AT_BAUD, 115200):
            print('Suche ROM-Bootloader bei %d Baud ...' % baud)
            if self._try_sync(baud, timeout):
                print('Connected im ROM-Bootloader (%d Baud)' % baud)
                self.ser.timeout = 5
                return baud
        raise CmdException(
            'Kein Sync. BOOT-Pin beim Einstecken auf RX bruecken '
            '(Jumper/Draht), dann erneut versuchen.')

    def try_speedup(self, baud):
        current = self.ser.baudrate
        if baud == current:
            return current
        try:
            self.set_baudrate(baud)
            self.ser.timeout = 5
            self.sync()
            print('Baudrate auf %d erhoeht' % baud)
            return baud
        except Exception as e:
            print('Baudwechsel auf %d nicht moeglich (%s), bleibe bei %d'
                  % (baud, e, current))
            self.ser.baudrate = current
            self.ser.timeout = 5
            return current

    def download(self, address, filename):
        size = os.path.getsize(filename)
        with open(filename, 'rb') as f:
            data = f.read()
        checksum = zlib.crc32(data) & 0xFFFFFFFF

        print('Erase 0x%08X (%d Bytes) ...' % (address, size))
        self.erase(address, size)

        addr = address
        sent = 0
        t0 = time.time()
        for off in range(0, size, 512):
            chunk = data[off:off + 512]
            self.flash(addr, chunk)
            addr += len(chunk)
            sent += len(chunk)
            pct = 100.0 * sent / size
            sys.stdout.write('\rFlash: %6d / %d Bytes (%5.1f%%)' % (sent, size, pct))
            sys.stdout.flush()
        print('\nDauer: %.1f s' % (time.time() - t0))

        print('Verify ...')
        self.verify(address, size, checksum)
        print('Verify OK')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('firmware', help='.bin Datei')
    ap.add_argument('-p', '--port', default='/dev/ttyUSB0')
    ap.add_argument('-a', '--address', type=lambda x: int(x, 0), default=None,
                    help='Flash-Adresse (default: 0x08000000 fuer Images mit '
                         'Bootloader, 0x0800D000 fuer reine Applikationen)')
    ap.add_argument('-b', '--baud', type=int, default=115200,
                    help='Baudrate fuer den Transfer (default 115200)')
    args = ap.parse_args()

    if args.address is None:
        name = os.path.basename(args.firmware).lower()
        args.address = FLASH_BASE if 'bootlo' in name else APP_BASE
        print('Adresse automatisch gewaehlt: 0x%08X' % args.address)

    loader = LA66Loader(args.port)
    found = loader.connect_rom()
    if found != args.baud:
        loader.try_speedup(args.baud)
    loader.download(args.address, args.firmware)
    print('Reboot ...')
    loader.reboot(0)
    print('Fertig.')


if __name__ == '__main__':
    main()
