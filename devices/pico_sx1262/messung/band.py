import lora_p2p, utime

r = lora_p2p.radio()
XTAL = 32000000

print("=== 1) Chip-Kennung, Register 0x0320 (16 Byte)")
v = r.rdreg(0x0320, 16)
print("hex :", " ".join("%02X" % b for b in v))
print("ascii:", "".join(chr(b) if 32 <= b < 127 else "." for b in v))

print()
print("=== 2) PLL-Rastbereich (SetFs, dann PLL_LOCK_ERR in GetDeviceErrors)")


def pll_locks(mhz):
    r.cmd([0x80, 0x00])                      # Standby RC
    r.cmd([0x07, 0x00, 0x00])                # ClearDeviceErrors
    pll = (int(mhz * 1000000) << 25) // XTAL
    r.cmd([0x86, (pll >> 24) & 0xFF, (pll >> 16) & 0xFF,
           (pll >> 8) & 0xFF, pll & 0xFF])
    r.cmd([0xC1])                            # SetFs: Synthesizer an
    utime.sleep_ms(10)
    e = r.errors()
    r.cmd([0x80, 0x00])
    return not (e & 0x0040), e


lo = None
hi = None
for mhz in range(100, 1101, 25):
    ok, e = pll_locks(mhz)
    if ok:
        if lo is None:
            lo = mhz
        hi = mhz
    print("  %4d MHz  %s  (DeviceErrors 0x%04X)"
          % (mhz, "rastet" if ok else "PLL_LOCK_ERR", e))
print("PLL rastet von %s bis %s MHz" % (lo, hi))

print()
print("=== 3) Durchlassbereich des Frontends: Rauschflur ueber der Frequenz")
print("    (RX-only. Wo Anpassung und Filter durchlassen, kommt mehr")
print("     Umgebungsrauschen an; ausserhalb faellt der Pegel ab.)")

CAL = [(430, 440, 0x6B, 0x6F), (470, 510, 0x75, 0x81), (779, 787, 0xC1, 0xC5),
       (863, 870, 0xD7, 0xDB), (902, 928, 0xE1, 0xE9)]


def noise(mhz):
    r.cmd([0x80, 0x00])
    for a, b, f1, f2 in CAL:                 # Bildkalibrierung, wenn passend
        if a - 15 <= mhz <= b + 15:
            r.cmd([0x98, f1, f2])
            break
    pll = (int(mhz * 1000000) << 25) // XTAL
    r.cmd([0x86, (pll >> 24) & 0xFF, (pll >> 16) & 0xFF,
           (pll >> 8) & 0xFF, pll & 0xFF])
    r._packet_params(255)
    r.cmd([0x02, 0xFF, 0xFF])
    r.cmd([0x82, 0xFF, 0xFF, 0xFF])          # RX dauerhaft
    utime.sleep_ms(60)
    s = []
    for _ in range(12):
        s.append(-r.cmd([0x15, 0x00], 1)[0] / 2.0)
        utime.sleep_ms(8)
    r.cmd([0x80, 0x00])
    s.sort()
    return s[len(s) // 2], s[-1]             # Median, Maximum


res = []
for mhz in [150, 200, 250, 300, 350, 400, 434, 470, 500, 550, 600, 650, 700,
            750, 779, 800, 830, 850, 860, 865, 868, 870, 875, 890, 915, 928,
            950, 1000]:
    med, mx = noise(mhz)
    res.append((mhz, med))
    bar = "#" * max(0, int((med + 130) * 1.5))
    print("  %4d MHz  Median %6.1f  Max %6.1f  %s" % (mhz, med, mx, bar))

best = max(res, key=lambda x: x[1])
print()
print("empfindlichster Punkt: %d MHz bei %.1f dBm" % best)
floor = min(x[1] for x in res)
band = [m for m, d in res if d > floor + 6]
if band:
    print("Durchlass (>6 dB ueber dem tiefsten Wert): %d - %d MHz"
          % (min(band), max(band)))
