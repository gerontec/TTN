#!/usr/bin/env python3
"""TrackerD: zwischen LoRaWAN (app0) und P2P (app1) umschalten.

Der TrackerD hat ab Werk eine OTA-Partitionstabelle mit zwei gleich grossen
App-Slots, und app1 ist leer:

    nvs       0x009000  0x005000
    otadata   0x00E000  0x002000
    app0      0x010000  0x1E0000   <- Dragino LoRaWAN-Firmware
    app1      0x1F0000  0x1E0000   <- frei, hier landet P2P
    spiffs    0x3D0000  0x030000

Damit braucht P2P die LoRaWAN-Firmware nicht zu verdraengen. Dieses Skript
schreibt ausschliesslich app1 und otadata - Bootloader (0x0), Partitions-
tabelle (0x8000), app0 und nvs (Keys!) werden nie angefasst.

otadata besteht aus zwei 4-KB-Sektoren mit je einem 32-Byte-Eintrag:
ota_seq (u32), seq_label[20], ota_state (u32), crc (u32). Der Bootloader
nimmt den Eintrag mit der hoechsten gueltigen Sequenz; der Slot ergibt sich
als (ota_seq - 1) % 2. Die CRC ist zlib.crc32(ota_seq_le, 0xFFFFFFFF) -
gegen die echte otadata des Geraets verifiziert.

    ./switch_app.py status
    ./switch_app.py flash            # P2P nach app1 und dorthin booten
    ./switch_app.py lorawan          # zurueck auf app0
    ./switch_app.py p2p              # wieder app1 (ohne neu zu flashen)
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
import zlib

PORT_DEFAULT = '/dev/ttyACM0'
BAUD_DEFAULT = 921600

OTADATA_ADDR = 0x00E000
OTADATA_SIZE = 0x002000
SECTOR = 0x1000
APP1_ADDR = 0x1F0000
APP1_SIZE = 0x1E0000

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BIN = os.path.join(HERE, 'p2p', '.pio', 'build', 'trackerd_p2p',
                           'firmware.bin')

EMPTY = b'\xff' * SECTOR


def esptool(port, baud, *args):
    cmd = ['esptool', '--port', port, '--baud', str(baud)] + list(args)
    print('$', ' '.join(cmd))
    subprocess.run(cmd, check=True)


def ota_entry(seq):
    """32-Byte-Eintrag mit gueltiger CRC, Rest des Sektors bleibt 0xFF."""
    raw = struct.pack('<I', seq)
    crc = zlib.crc32(raw, 0xFFFFFFFF) & 0xFFFFFFFF
    entry = raw + b'\xff' * 20 + struct.pack('<II', 0xFFFFFFFF, crc)
    assert len(entry) == 32
    return entry + b'\xff' * (SECTOR - 32)


def read_otadata(port, baud):
    fd, path = tempfile.mkstemp(suffix='.bin')
    os.close(fd)
    try:
        esptool(port, baud, 'read-flash', hex(OTADATA_ADDR),
                hex(OTADATA_SIZE), path)
        with open(path, 'rb') as f:
            return f.read()
    finally:
        os.unlink(path)


def parse_entry(sector):
    seq, = struct.unpack('<I', sector[:4])
    crc, = struct.unpack('<I', sector[28:32])
    ok = (crc == (zlib.crc32(sector[:4], 0xFFFFFFFF) & 0xFFFFFFFF)
          and seq not in (0, 0xFFFFFFFF))
    return seq, crc, ok


def show_status(port, baud):
    data = read_otadata(port, baud)
    best_seq, best_i = 0, None
    for i in (0, 1):
        seq, crc, ok = parse_entry(data[i * SECTOR:(i + 1) * SECTOR])
        state = 'gueltig' if ok else ('leer' if seq in (0, 0xFFFFFFFF)
                                      else 'ungueltig')
        print('otadata[%d] @0x%05X: ota_seq=%-10s crc=0x%08X  %s'
              % (i, OTADATA_ADDR + i * SECTOR,
                 'leer' if seq in (0, 0xFFFFFFFF) else seq, crc, state))
        if ok and seq > best_seq:
            best_seq, best_i = seq, i
    if best_i is None:
        print('-> kein gueltiger Eintrag: Bootloader nimmt den ersten App-Slot (app0/LoRaWAN)')
    else:
        slot = (best_seq - 1) % 2
        print('-> bootet app%d (%s)' % (slot, 'LoRaWAN' if slot == 0 else 'P2P'))


def write_otadata(port, baud, slot):
    """slot 0 -> app0, slot 1 -> app1. Beide Sektoren werden gesetzt."""
    if slot == 0:
        sect0, sect1 = ota_entry(1), EMPTY
    else:
        sect0, sect1 = ota_entry(1), ota_entry(2)
    fd, path = tempfile.mkstemp(suffix='.bin')
    with os.fdopen(fd, 'wb') as f:
        f.write(sect0 + sect1)
    try:
        esptool(port, baud, 'write-flash', hex(OTADATA_ADDR), path)
    finally:
        os.unlink(path)


def flash_app1(port, baud, binpath):
    size = os.path.getsize(binpath)
    if size > APP1_SIZE:
        sys.exit('%s ist %d Byte, app1 fasst nur %d' % (binpath, size, APP1_SIZE))
    with open(binpath, 'rb') as f:
        if f.read(1) != b'\xe9':
            sys.exit('%s hat keine ESP32-Image-Magic 0xE9' % binpath)
    print('%s -> app1 @0x%06X (%d Byte)' % (binpath, APP1_ADDR, size))
    esptool(port, baud, 'write-flash', hex(APP1_ADDR), binpath)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', choices=['status', 'flash', 'p2p', 'lorawan'])
    ap.add_argument('-p', '--port', default=PORT_DEFAULT)
    ap.add_argument('-b', '--baud', type=int, default=BAUD_DEFAULT)
    ap.add_argument('--bin', default=DEFAULT_BIN, help='P2P-Image fuer "flash"')
    args = ap.parse_args()

    if args.action == 'status':
        show_status(args.port, args.baud)
    elif args.action == 'flash':
        flash_app1(args.port, args.baud, args.bin)
        write_otadata(args.port, args.baud, 1)
        print('app1 geflasht und als Bootpartition gesetzt.')
    elif args.action == 'p2p':
        write_otadata(args.port, args.baud, 1)
        print('Bootpartition = app1 (P2P).')
    else:
        write_otadata(args.port, args.baud, 0)
        print('Bootpartition = app0 (LoRaWAN).')


if __name__ == '__main__':
    main()
