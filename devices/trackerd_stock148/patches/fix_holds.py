#!/usr/bin/env python3
"""Pad-Holds beim Start loesen, bevor LMIC das Funkmodul anspricht.

Vor dem Deep Sleep isoliert die Firmware MOSI (`rtc_gpio_isolate(GPIO_NUM_27)`).
Geloest wird das erst im Kaltstartzweig von print_wakeup_reason() -- und der
bricht auf dem Werksreset-Weg vorher mit `DATA_CLEAR(); ESP.restart();` ab.

Ein frueherer Stand loeste hier zusaetzlich einen Hold auf GPIO 12 (GPS_POWER,
`GPS.h:6`). Das war wirkungslos: im ganzen Quelltext wird nirgends ein Hold
gesetzt, weder `gpio_hold_en` noch `gpio_deep_sleep_hold_en`. GPS_POWER wird
schlicht per `digitalWrite` geschaltet. Die Zeile ist raus, weil sie eine
Wirkung suggerierte, die sie nicht hat. Ein Software-Reset
raeumt RTC-Pad-Holds aber nicht auf: MOSI bleibt abgeklemmt, `radio_init()`
liest die Versionskennung des SX1276 nicht mehr und `os_init()` endet in
ASSERT(0) -- oslmic.c:53, danach schlaegt der Interrupt-Watchdog zu.

Deshalb hier ganz vorn in setup(), vor os_init(): alle Holds loesen.
"""
import sys, os
src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

alt = """void setup() {
// put your setup code here, to run once:
  Wire.begin();
  Serial.begin(115200); """
neu = """void setup() {
// put your setup code here, to run once:
  /* Pad-Holds aus dem Schlafpfad loesen, bevor irgendetwas den Bus benutzt.
     Sonst bleibt MOSI (GPIO 27) nach einem Software-Reset abgeklemmt, der
     SX1276 antwortet nicht, radio_init() scheitert und os_init() bleibt in
     ASSERT(0) stehen (oslmic.c:53). Der Werksstand loest das erst im
     Kaltstartzweig -- der auf dem DATA_CLEAR-Weg vorher neu startet. */
  rtc_gpio_hold_dis(GPIO_NUM_27);
  rtc_gpio_deinit(GPIO_NUM_27);
  Wire.begin();
  Serial.begin(115200); """
if s.count(alt) != 1:
    sys.exit("setup()-Kopf nicht eindeutig gefunden (%d)" % s.count(alt))
s = s.replace(alt, neu)

if "driver/rtc_io.h" not in s:
    marker = "#include <Wire.h>"
    if s.count(marker) == 1:
        s = s.replace(marker, marker + "\n#include \"driver/rtc_io.h\"")
    else:
        s = "#include \"driver/rtc_io.h\"\n" + s
open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
print("gepatcht:", p)
