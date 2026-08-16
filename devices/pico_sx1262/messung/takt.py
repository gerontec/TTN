import machine
import utime

for mhz in (125, 96, 64, 48, 32, 24, 18, 12):
    try:
        machine.freq(mhz * 1000000)
    except Exception as e:
        print("%3d MHz: freq() abgelehnt: %r" % (mhz, e))
        continue
    ist = machine.freq() // 1000000
    # SX1262 erst NACH dem Taktwechsel aufsetzen: clk_peri haengt an clk_sys,
    # ein vorher erzeugtes SPI-Objekt haette die falsche Teilung.
    try:
        import lora_p2p
        lora_p2p._radio = None
        r = lora_p2p.radio()
        fehler = r.errors()
        sw = bytes(r.rdreg(0x0740, 2)).hex()
        t0 = utime.ticks_ms()
        ok = r.send("TAKT%03d" % ist)
        dauer = utime.ticks_diff(utime.ticks_ms(), t0)
        print("%3d MHz (ist %3d): DevErr 0x%04X  Sync %s  TX %s  %d ms"
              % (mhz, ist, fehler, sw, "ok" if ok else "FEHLER", dauer))
    except Exception as e:
        print("%3d MHz: Funk kaputt: %r" % (mhz, e))
    utime.sleep(6)

machine.freq(125000000)
print("zurueck auf %d MHz" % (machine.freq() // 1000000))
