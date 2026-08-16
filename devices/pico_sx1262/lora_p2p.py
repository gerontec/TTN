"""Rohes LoRa auf dem Raspberry Pi Pico mit Waveshare Pico-LoRa-SX1262.

Sendet auf dem Rohkanal des DLOS8N (868.125 MHz, SF7, BW125, CR 4/5,
Preamble 8, CRC an, expliziter Header) und wird dort als `rxpk.data` an
`192.168.5.23:1702` weitergereicht -- siehe gateway/RAWKANAL.md.

Das entscheidende Detail ist das **Syncword 0x34**. Der SX1302 im Gateway kennt
nur ein Syncword fuer den ganzen Chip (`lorawan_public: true`); ein Node mit dem
Werkswert 0x12 wird schlicht nicht gehoert. Beim SX1262 sitzt es in den
Registern 0x0740/0x0741, und zwar als 0x34,0x44 -- nicht 0x34,0x00.

Zwei weitere Fallen dieses Boards, beide nachgemessen:

  * Der SPI laeuft im **Mode 0** (polarity=0, phase=0), nicht Mode 3.
  * Das Modul hat einen **TCXO an DIO3**. Ohne `SetDIO3AsTCXOCtrl` meldet
    `GetDeviceErrors` 0x0020 (XOSC_START_ERR), der Oszillator laeuft nicht und
    es geht nichts raus. Gemessen: jede Spannung ab 1.6V raeumt den Fehler ab,
    genommen wird der Referenzwert 1.8V.
  * DIO2 steuert den **Antennenschalter**. Ohne `SetDIO2AsRfSwitchCtrl(1)`
    sendet der Chip zwar, aber nichts erreicht die Antenne.

  import lora_p2p
  lora_p2p.beacon()                    # alle 30 s ein Paket
  lora_p2p.send("hallo")               # einmal senden
  lora_p2p.listen()                    # empfangen, z.B. lora_raw.py --send
"""
from machine import Pin, SPI
import utime

# --- Funkparameter, muessen zum Rohkanal des Gateways passen ---------------
FREQ_HZ   = 868125000
SF        = 7
BW_HZ     = 125000
CR        = 1          # 1..4 = 4/5..4/8
PREAMBLE  = 8
SYNCWORD  = 0x34       # oeffentlich; 0x12 waere privat und wird nicht gehoert
CRC_ON    = True
POWER_DBM = 14         # 25 mW ERP, das Limit in 868.0-868.6 MHz
BEACON_S  = 30

# --- Verdrahtung des Waveshare Pico-LoRa-SX1262 ---------------------------
PIN_SCK, PIN_MOSI, PIN_MISO = 10, 11, 12
PIN_CS, PIN_BUSY, PIN_RESET, PIN_DIO1 = 3, 2, 15, 20

# --- SX1262 Opcodes -------------------------------------------------------
SET_STANDBY, SET_TX, SET_RX          = 0x80, 0x83, 0x82
SET_PACKET_TYPE                      = 0x8A
SET_RF_FREQUENCY                     = 0x86
SET_MODULATION_PARAMS                = 0x8B
SET_PACKET_PARAMS                    = 0x8C
SET_BUFFER_BASE                      = 0x8F
SET_PA_CONFIG, SET_TX_PARAMS         = 0x95, 0x8E
SET_DIO_IRQ_PARAMS                   = 0x08
GET_IRQ_STATUS, CLEAR_IRQ_STATUS     = 0x12, 0x02
SET_DIO2_RF_SWITCH                   = 0x9D
SET_DIO3_TCXO                        = 0x97
SET_REGULATOR_MODE                   = 0x96
CALIBRATE, CALIBRATE_IMAGE           = 0x89, 0x98
CLEAR_DEVICE_ERRORS, GET_DEVICE_ERR  = 0x07, 0x17
WRITE_BUFFER, READ_BUFFER            = 0x0E, 0x1E
WRITE_REGISTER, READ_REGISTER        = 0x0D, 0x1D
GET_RX_BUFFER_STATUS                 = 0x13
GET_PACKET_STATUS                    = 0x14

IRQ_TX_DONE, IRQ_RX_DONE = 0x0001, 0x0002
IRQ_TIMEOUT, IRQ_CRC_ERR = 0x0200, 0x0040

REG_SYNCWORD = 0x0740
XTAL = 32000000

# Bildkalibrierung, SX1262-Datenblatt Tabelle 9-2: (untere MHz, obere MHz, f1, f2)
KALIBRIERBAENDER = (
    (430, 440, 0x6B, 0x6F),
    (470, 510, 0x75, 0x81),
    (779, 787, 0xC1, 0xC5),
    (863, 870, 0xD7, 0xDB),
    (902, 928, 0xE1, 0xE9),
)


def kalibrierband(hz):
    """Die beiden CalibrateImage-Bytes fuer diese Frequenz.

    Die Tabelle deckt nur die im Datenblatt genannten Baender ab und laesst
    Luecken (z.B. 856 MHz). Dahinter steht aber eine schlichte Regel: die Bytes
    sind die Bandgrenzen in Schritten von 4 MHz. Gegenprobe an der Tabelle:
    0xD7 = 215 -> 860 MHz, 0xDB = 219 -> 876 MHz, also das 863-870-Band.
    Ausserhalb der Tabelle wird deshalb gerechnet statt abgebrochen.
    """
    mhz = hz / 1000000.0
    for unten, oben, f1, f2 in KALIBRIERBAENDER:
        if unten <= mhz <= oben:
            return f1, f2
    f1 = int(mhz / 4)
    f2 = -(-int(mhz) // 4) + 1
    return f1 & 0xFF, f2 & 0xFF

BW_TABLE = {7800: 0x00, 10400: 0x08, 15600: 0x01, 20800: 0x09, 31250: 0x02,
            41700: 0x0A, 62500: 0x03, 125000: 0x04, 250000: 0x05, 500000: 0x06}


class SX1262:
    def __init__(self):
        self.spi = SPI(1, baudrate=2000000, polarity=0, phase=0, bits=8,
                       sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI), miso=Pin(PIN_MISO))
        self.cs = Pin(PIN_CS, Pin.OUT, value=1)
        self.busy = Pin(PIN_BUSY, Pin.IN)
        self.rst = Pin(PIN_RESET, Pin.OUT, value=1)
        self.sf, self.bw, self.cr = SF, BW_HZ, CR   # bis set_modulation laeuft
        self.dio1 = Pin(PIN_DIO1, Pin.IN)

    # -- Bustransport ------------------------------------------------------
    def _wait(self, ms=100):
        t = utime.ticks_ms()
        while self.busy.value():
            if utime.ticks_diff(utime.ticks_ms(), t) > ms:
                raise OSError("SX1262 BUSY bleibt hoch")
            utime.sleep_us(100)

    def cmd(self, data, nread=0):
        self._wait()
        out = bytearray(len(data) + nread)
        self.cs.value(0)
        self.spi.write_readinto(bytearray(data) + bytearray(nread), out)
        self.cs.value(1)
        return out[len(data):]

    def wrreg(self, addr, vals):
        self.cmd([WRITE_REGISTER, addr >> 8, addr & 0xFF] + list(vals))

    def rdreg(self, addr, n=1):
        return self.cmd([READ_REGISTER, addr >> 8, addr & 0xFF, 0x00], n)

    def errors(self):
        r = self.cmd([GET_DEVICE_ERR, 0x00], 2)
        return (r[0] << 8) | r[1]

    # -- Aufbau ------------------------------------------------------------
    def reset(self):
        self.rst.value(0); utime.sleep_ms(20)
        self.rst.value(1); utime.sleep_ms(20)
        self._wait()

    def begin(self):
        self.reset()
        self.cmd([SET_STANDBY, 0x00])                     # STDBY_RC
        # TCXO an DIO3, 1.8 V, 5 ms Anlaufzeit (Schritte zu 15.625 us)
        self.cmd([SET_DIO3_TCXO, 0x02, 0x00, 0x01, 0x40])
        self.cmd([CLEAR_DEVICE_ERRORS, 0x00, 0x00])
        self.cmd([CALIBRATE, 0x7F])
        utime.sleep_ms(50)
        e = self.errors()
        if e:
            raise OSError("SX1262 DeviceErrors 0x%04X nach Calibrate" % e)

        self.cmd([SET_DIO2_RF_SWITCH, 0x01])              # Antennenschalter
        self.cmd([SET_REGULATOR_MODE, 0x01])              # DC-DC
        self.cmd([SET_PACKET_TYPE, 0x01])                 # LoRa
        self.set_frequency(FREQ_HZ)
        self.set_power(POWER_DBM)
        self.set_modulation(SF, BW_HZ, CR)
        self.set_syncword(SYNCWORD)
        self.cmd([SET_BUFFER_BASE, 0x00, 0x00])

    def set_frequency(self, hz):
        # Bildkalibrierung passend zum Band vor dem Frequenzwechsel. Die
        # Konstanten sind bandgebunden (SX1262-Datenblatt Tab. 9-2); mit den
        # 868er-Werten auf 433 MHz bleibt die Bildunterdrueckung unkalibriert.
        self.cmd([CALIBRATE_IMAGE] + list(kalibrierband(hz)))
        pll = (hz << 25) // XTAL
        self.cmd([SET_RF_FREQUENCY, (pll >> 24) & 0xFF, (pll >> 16) & 0xFF,
                  (pll >> 8) & 0xFF, pll & 0xFF])

    def set_power(self, dbm):
        # SX1262: Hochleistungs-PA. Werte aus der Datenblatt-Tabelle 13-21.
        if dbm >= 22:
            duty, hpmax = 0x04, 0x07
        elif dbm >= 20:
            duty, hpmax = 0x03, 0x05
        elif dbm >= 17:
            duty, hpmax = 0x02, 0x03
        else:
            duty, hpmax = 0x02, 0x02
        self.cmd([SET_PA_CONFIG, duty, hpmax, 0x00, 0x01])
        self.cmd([SET_TX_PARAMS, dbm & 0xFF, 0x04])       # Rampe 200 us

    def set_modulation(self, sf, bw, cr):
        # Low Data Rate Optimize ist Pflicht, sobald ein Symbol > 16 ms dauert
        ldro = 1 if (1 << sf) / (bw / 1000.0) > 16.0 else 0
        self.cmd([SET_MODULATION_PARAMS, sf, BW_TABLE[bw], cr, ldro])
        # merken, damit send() seine Zeitschranke an die Luftzeit anpassen kann
        self.sf, self.bw, self.cr = sf, bw, cr

    def set_syncword(self, sw):
        # 0x34 -> 0x3444, 0x12 -> 0x1424: das untere Nibble wird auf 4 gezogen
        self.wrreg(REG_SYNCWORD, [(sw & 0xF0) | 0x04,
                                  ((sw & 0x0F) << 4) | 0x04])

    def _packet_params(self, length, rx=False):
        self.cmd([SET_PACKET_PARAMS,
                  (PREAMBLE >> 8) & 0xFF, PREAMBLE & 0xFF,
                  0x00,                       # expliziter Header
                  length & 0xFF,
                  0x01 if CRC_ON else 0x00,
                  0x00])                      # IQ normal, nicht invertiert

    # -- Senden und Empfangen ---------------------------------------------
    def send(self, payload):
        if isinstance(payload, str):
            payload = payload.encode()
        payload = payload[:255]
        self.cmd([SET_STANDBY, 0x00])
        self._packet_params(len(payload))
        self.cmd([SET_BUFFER_BASE, 0x00, 0x00])
        self.cmd([WRITE_BUFFER, 0x00] + list(payload))
        self.cmd([SET_DIO_IRQ_PARAMS,
                  0x02, 0x01, 0x02, 0x01, 0x00, 0x00, 0x00, 0x00])
        self.cmd([CLEAR_IRQ_STATUS, 0xFF, 0xFF])

        # Notbremse aus der Luftzeit ableiten, nicht fest verdrahten: ein
        # SF12-Paket dauert ueber 1,5 s und wuerde von einer starren 1-s-Schranke
        # mitten im Senden abgebrochen. Einheit sind 15.625 us, also ms * 64.
        luft = airtime_ms(len(payload), sf=self.sf, bw=self.bw, cr=self.cr)
        schritte = min(0xFFFFFF, int(luft * 3 * 64))
        self.cmd([SET_TX, (schritte >> 16) & 0xFF,
                  (schritte >> 8) & 0xFF, schritte & 0xFF])

        grenze = int(luft * 3) + 1000
        t = utime.ticks_ms()
        while True:
            irq = self.irq()
            if irq & IRQ_TX_DONE:
                self.cmd([CLEAR_IRQ_STATUS, 0xFF, 0xFF])
                return True
            if irq & IRQ_TIMEOUT or utime.ticks_diff(utime.ticks_ms(), t) > grenze:
                self.cmd([CLEAR_IRQ_STATUS, 0xFF, 0xFF])
                return False
            utime.sleep_ms(2)

    def irq(self):
        r = self.cmd([GET_IRQ_STATUS, 0x00], 2)
        return (r[0] << 8) | r[1]

    def recv(self, timeout_ms=0):
        """Ein Paket abwarten. timeout_ms=0 heisst unbegrenzt."""
        self.cmd([SET_STANDBY, 0x00])
        self._packet_params(255, rx=True)
        self.cmd([SET_DIO_IRQ_PARAMS,
                  0x02, 0x42, 0x02, 0x42, 0x00, 0x00, 0x00, 0x00])
        self.cmd([CLEAR_IRQ_STATUS, 0xFF, 0xFF])
        self.cmd([SET_RX, 0xFF, 0xFF, 0xFF])              # Dauerempfang
        t = utime.ticks_ms()
        while True:
            irq = self.irq()
            if irq & IRQ_RX_DONE:
                self.cmd([CLEAR_IRQ_STATUS, 0xFF, 0xFF])
                # cmd() schneidet die gesendeten Bytes ab, die Antwort beginnt
                # also bei Index 0 -- gegengeprueft an GetRssiInst, das damit
                # einen plausiblen Rauschflur von -113 dBm liefert.
                st = self.cmd([GET_RX_BUFFER_STATUS, 0x00], 3)
                n, start = st[0], st[1]
                data = self.cmd([READ_BUFFER, start, 0x00], n)
                ps = self.cmd([GET_PACKET_STATUS, 0x00], 4)
                rssi, snr = -ps[0] / 2.0, (ps[1] if ps[1] < 128 else ps[1] - 256) / 4.0
                return bytes(data), rssi, snr, bool(irq & IRQ_CRC_ERR)
            if timeout_ms and utime.ticks_diff(utime.ticks_ms(), t) > timeout_ms:
                return None
            utime.sleep_ms(5)


def airtime_ms(payload_len, sf=SF, bw=BW_HZ, cr=CR, crc=CRC_ON, preamble=PREAMBLE):
    """Sendedauer nach der Semtech-Formel -- fuer das Duty-Cycle-Budget."""
    tsym = (1 << sf) / float(bw)
    de = 1 if tsym > 0.016 else 0
    num = 8 * payload_len - 4 * sf + 28 + (16 if crc else 0)
    den = 4 * (sf - 2 * de)
    n = 8 + max(0, -(-num // den) * (cr + 4))
    return ((preamble + 4.25) * tsym + n * tsym) * 1000.0


_radio = None


def radio():
    global _radio
    if _radio is None:
        _radio = SX1262()
        _radio.begin()
    return _radio


def send(msg):
    r = radio()
    ok = r.send(msg)
    print("%s  %r  (%.0f ms Luftzeit)"
          % ("gesendet" if ok else "TIMEOUT", msg,
             airtime_ms(len(msg if isinstance(msg, bytes) else msg.encode()))))
    return ok


def beacon(interval=BEACON_S, prefix="PICO"):
    """Dauerbetrieb. Bei 1 % Duty Cycle in 868.0-868.6 MHz und ~60 ms
    Luftzeit waeren 6 s Abstand das Minimum -- 30 s sind reichlich Reserve."""
    r = radio()
    print("Rohkanal %.3f MHz  SF%d  BW%d  Sync 0x%02X  %d dBm  alle %d s"
          % (FREQ_HZ / 1e6, SF, BW_HZ // 1000, SYNCWORD, POWER_DBM, interval))
    n = 0
    while True:
        n += 1
        msg = "%s %d %d" % (prefix, n, utime.ticks_ms() // 1000)
        ok = r.send(msg)
        print("%4d  %s  %r" % (n, "ok " if ok else "ERR", msg))
        utime.sleep(interval)


def listen(timeout_ms=0):
    r = radio()
    print("empfange auf %.3f MHz SF%d BW%d Sync 0x%02X"
          % (FREQ_HZ / 1e6, SF, BW_HZ // 1000, SYNCWORD))
    while True:
        got = r.recv(timeout_ms)
        if got is None:
            print("-- nichts --")
            continue
        data, rssi, snr, crcbad = got
        print("RSSI %.0f  SNR %.1f  %s %d B  %s  %r"
              % (rssi, snr, "CRC-FEHLER" if crcbad else "CRC ok",
                 len(data), data.hex(), data))
