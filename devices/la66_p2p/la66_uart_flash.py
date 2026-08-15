#!/usr/bin/env python3
"""LA66-USB unter Linux flashen -- ueber den Dragino-OTA-Bootloader.

1:1-Portierung des UART-Update-Wegs aus dem Dragino Sensor Manager Utility
(V1.5, PyInstaller/PyQt5, Klasse `ThreadSerial1`).  Damit braucht es weder
Windows noch die BOOT<->RX-Bruecke: der Bootloader wird ueber die normale
AT-Konsole angesprochen.

Der entscheidende Punkt, den man ohne Blick in das Utility nicht raet: der
Bootloader haelt sein Fenster nur ~2 s offen und reagiert dort **nicht** auf
rohe Tremo-Sync-Pakete.  Er will

  1. den Trigger `123456` bzw. `ATZ` (abwechselnd, 9600 und 921600 Baud),
  2. danach `AT+MOD=1`, um in den Programmiermodus zu gehen,
  3. und alle weiteren Tremo-Kommandos als **ASCII-Hex in `AT+TX=<len>,<HEX>`**
     verpackt, jeweils mit der festen UUID 6666666666666666.

Adresse ist 0x0800D000 (Applikation hinter dem Bootloader), Nutzlast 224 Byte
je Paket -- beides wie im Original.

  ./la66_uart_flash.py LA66_P2P_v1.2.4_application.bin
  ./la66_uart_flash.py -p /dev/ttyUSB0 --address 0x0800D000 firmware.bin
"""
import argparse
import binascii
import os
import struct
import sys
import time
import zlib

import serial

# --- Konstanten aus ThreadSerial1 -------------------------------------------
DEUI = '6666666666666666'
UUID = '6666666666666666'
LORA_FREQ = 838000000
LORA_SF = 5
LORA_BW = 2
LORA_TX_POWER = 10

CMD_SYNC = 1
CMD_FLASH = 3
CMD_ERASE = 4
CMD_VERIFY = 5
CMD_RESET = 6
CMD_REBOOT = 12

APP_ADDRESS = 0x0800D000      # 134270976, wie im Utility hart kodiert
CHUNK = 224                   # Nutzlast je AT+TX-Paket
BAUD_AT = 9600
BAUD_XFER = 921600


class Timeout(Exception):
    pass


class LA66UartFlasher(object):
    def __init__(self, port, verbose=False):
        self.ser = serial.Serial(port, BAUD_AT, timeout=1)
        self.verbose = verbose

    # --- Rahmenbau -----------------------------------------------------------
    def _frame(self, cmd, data=b''):
        """FE cmd UUID len data crc32 EF -> 'AT+TX=<len>,<HEXUPPER>\r\n'."""
        uuid_raw = binascii.a2b_hex(UUID)
        pkt = struct.pack('<BB', 0xFE, cmd) + uuid_raw + struct.pack('<H', len(data)) + data
        pkt += struct.pack('<IB', zlib.crc32(pkt) & 0xFFFFFFFF, 0xEF)
        body = binascii.b2a_hex(pkt).decode('ascii').upper().encode('ascii')
        return b'AT+TX=' + str(len(data) + 17).encode('ascii') + b',' + body + b'\r\n'

    def _wait_for(self, expected, timeout):
        """Zeilenweise lesen, bis `expected` vorkommt -- sonst Timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.ser.readline()
            if self.verbose and line:
                sys.stdout.write('    < %r\n' % line)
            if expected in line:
                return line
        raise Timeout('warte vergeblich auf %r' % expected)

    def request(self, cmd, data=b''):
        """Kommando senden und auf das UUID-Echo warten (ein Wiederholversuch)."""
        frame = self._frame(cmd, data)
        self.ser.flushInput()
        self.ser.write(frame)
        try:
            self._wait_for(UUID.encode('ascii'), 5)
            return
        except Timeout:
            pass
        # Original: einmal nachfassen, vorher ein nacktes CRLF
        self.ser.flushInput()
        time.sleep(0.02)
        self.ser.write(b'\r\n')
        time.sleep(0.5)
        self.ser.write(frame)
        self._wait_for(UUID.encode('ascii'), 5)

    # --- Ablauf --------------------------------------------------------------
    def reset_la66(self, timeout=60):
        """Trigger und Baudrate durchrotieren, bis das Bootloader-Banner kommt."""
        deadline = time.time() + timeout
        i = j = 0
        tries = 0
        while time.time() < deadline:
            self.ser.baudrate = BAUD_AT if j == 0 else BAUD_XFER
            self.ser.write(b'123456\r\n' if i == 0 else b'ATZ\r\n')
            tries += 1
            i += 1
            if i > 1:
                i = 0
                j = (j + 1) % 2
            try:
                self.ser.baudrate = BAUD_AT
                self._wait_for(b'Dragino OTA bootloader', 1)
                print('  Bootloader gefangen (%d Versuche)' % tries)
                return
            except Timeout:
                continue
        raise Timeout('Bootloader hat sich nicht gemeldet')

    def enter_prog_mode(self):
        time.sleep(0.1)
        self.ser.write(b'AT+MOD=1\r\n')
        self._wait_for(b'OK', 1)
        print('  Programmiermodus aktiv (AT+MOD=1)')

    def sync(self):
        pkt = struct.pack('<BB', 0xFE, CMD_SYNC) + binascii.a2b_hex(UUID)
        pkt += struct.pack('<H', 15) + binascii.a2b_hex(DEUI)
        pkt += struct.pack('<IBBB', LORA_FREQ, LORA_SF, LORA_BW, LORA_TX_POWER)
        pkt += struct.pack('<IB', zlib.crc32(pkt) & 0xFFFFFFFF, 0xEF)
        body = binascii.b2a_hex(pkt).decode('ascii').upper().encode('ascii')
        frame = b'AT+TX=32,' + body + b'\r\n'
        self.ser.flushInput()
        self.ser.write(frame)
        deadline = time.time() + 30
        while time.time() < deadline:
            self.ser.write(frame)
            try:
                self._wait_for(UUID.encode('ascii'), 1)
                print('  Sync ok')
                return
            except Timeout:
                continue
        raise Timeout('Sync fehlgeschlagen')

    def erase(self, addr, size):
        self.request(CMD_ERASE, struct.pack('<II', addr, size))

    def flash(self, addr, chunk):
        self.request(CMD_FLASH, struct.pack('<II', addr, len(chunk)) + chunk)

    def verify(self, addr, size, checksum):
        self.request(CMD_VERIFY, struct.pack('<III', addr, size, checksum))

    def reboot(self, mode=0):
        self.request(CMD_REBOOT, struct.pack('I', mode))

    def download(self, address, filename):
        data = open(filename, 'rb').read()
        size = len(data)
        checksum = zlib.crc32(data) & 0xFFFFFFFF
        print('  Datei: %s (%d Bytes, CRC32 %08X)' % (filename, size, checksum))

        print('  Erase 0x%08X ...' % address)
        self.erase(address, size)

        t0 = time.time()
        addr = address
        for off in range(0, size, CHUNK):
            piece = data[off:off + CHUNK]
            self.flash(addr, piece)
            addr += len(piece)
            done = off + len(piece)
            sys.stdout.write('\r  Flash: %6d / %d (%5.1f%%)'
                             % (done, size, 100.0 * done / size))
            sys.stdout.flush()
        print('\n  Dauer: %.1f s' % (time.time() - t0))

        print('  Verify ...')
        self.verify(address, size, checksum)
        print('  Verify ok')
        self.reboot(0)

    def read_boot_output(self, seconds=8):
        """Nach dem Reboot die Startmeldungen der neuen Firmware mitlesen."""
        self.ser.baudrate = BAUD_AT
        deadline = time.time() + seconds
        out = []
        while time.time() < deadline:
            line = self.ser.readline()
            if not line:
                continue
            try:
                text = line.decode('utf-8')
            except UnicodeDecodeError:
                text = line.decode('iso-8859-1')
            text = text.replace('\r', '').replace('\n', '')
            if text:
                out.append(text)
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('firmware', help='Applikation OHNE Bootloader (0x0800D000)')
    ap.add_argument('-p', '--port', default='/dev/ttyUSB0')
    ap.add_argument('-a', '--address', type=lambda x: int(x, 0), default=APP_ADDRESS)
    ap.add_argument('-v', '--verbose', action='store_true', help='Serienverkehr zeigen')
    args = ap.parse_args()

    if 'bootlo' in os.path.basename(args.firmware).lower() and args.address == APP_ADDRESS:
        print('ABBRUCH: %s enthaelt den Bootloader und gehoert nach 0x08000000.\n'
              '         Ueber diesen Weg nur die Applikation ohne Bootloader flashen.'
              % os.path.basename(args.firmware))
        return 2

    f = LA66UartFlasher(args.port, args.verbose)
    print('Port %s, Ziel 0x%08X' % (args.port, args.address))
    print('  Warte auf den Bootloader (Trigger 123456 / ATZ) ...')
    f.reset_la66()
    f.enter_prog_mode()
    time.sleep(0.5)
    f.ser.baudrate = BAUD_XFER
    f.sync()
    f.download(args.address, args.firmware)
    print('\nNeustart -- Ausgabe der neuen Firmware:')
    for line in f.read_boot_output():
        print('  | %s' % line)
    f.ser.close()
    print('\nFertig.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
