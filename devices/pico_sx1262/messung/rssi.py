import lora_p2p, utime

r = lora_p2p.radio()
r.cmd([0x80, 0x00])                      # Standby
r._packet_params(255)
r.cmd([0x08, 0x02, 0x42, 0x02, 0x42, 0, 0, 0, 0])
r.cmd([0x02, 0xFF, 0xFF])                # ClearIrqStatus
r.cmd([0x82, 0xFF, 0xFF, 0xFF])          # SetRx dauerhaft
utime.sleep_ms(20)

lo, hi, n = 0, -200, 0
t = utime.ticks_ms()
while utime.ticks_diff(utime.ticks_ms(), t) < 30000:
    v = r.cmd([0x15, 0x00], 1)[0]        # GetRssiInst
    d = -v / 2.0
    if n == 0:
        lo = d
    lo = min(lo, d); hi = max(hi, d); n += 1
    if d > -100:
        print("Traeger! RSSI %.1f dBm nach %d ms"
              % (d, utime.ticks_diff(utime.ticks_ms(), t)))
    irq = r.irq()
    if irq & 0x0002:
        print("RxDone, IRQ 0x%04X" % irq)
        r.cmd([0x02, 0xFF, 0xFF])
    utime.sleep_ms(20)

print("Proben: %d   RSSI min %.1f  max %.1f dBm" % (n, lo, hi))
print("Rauschflur allein sagt: Antenne/Frontend still" if hi < -100
      else "HF kommt an -> Demodulation pruefen")
