from machine import Pin, SPI
import utime

spi = SPI(1, baudrate=2000000, polarity=0, phase=0, bits=8,
          sck=Pin(10), mosi=Pin(11), miso=Pin(12))
cs = Pin(3, Pin.OUT, value=1)
busy = Pin(2, Pin.IN)
rst = Pin(15, Pin.OUT, value=1)

VOLT = {0x00: "1.6V", 0x01: "1.7V", 0x02: "1.8V", 0x03: "2.2V",
        0x04: "2.4V", 0x05: "2.7V", 0x06: "3.0V", 0x07: "3.3V"}


def wait_busy(t=200):
    s = utime.ticks_ms()
    while busy.value():
        if utime.ticks_diff(utime.ticks_ms(), s) > t:
            return False
    return True


def xfer(data, nread=0):
    wait_busy()
    out = bytearray(len(data) + nread)
    cs.value(0)
    spi.write_readinto(bytearray(data) + bytearray(nread), out)
    cs.value(1)
    return out


def errors():
    r = xfer([0x17, 0x00], 2)
    return (r[2] << 8) | r[3]


for v, name in sorted(VOLT.items()):
    rst.value(0); utime.sleep_ms(20)
    rst.value(1); utime.sleep_ms(20)
    wait_busy()
    xfer([0x80, 0x00])                       # SetStandby(RC)
    utime.sleep_ms(5)
    xfer([0x97, v, 0x00, 0x01, 0x40])        # SetDIO3AsTCXOCtrl, 5 ms
    utime.sleep_ms(10)
    xfer([0x07, 0x00, 0x00])                 # ClearDeviceErrors
    xfer([0x89, 0x7F])                       # Calibrate alles
    utime.sleep_ms(50)
    e = errors()
    print("TCXO %s (0x%02X): DeviceErrors 0x%04X  %s"
          % (name, v, e, "OK" if not (e & 0x0020) else "XOSC_START_ERR"))
