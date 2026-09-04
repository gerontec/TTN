#!/usr/bin/env python3
"""GPS_POWER und GPS_RESET mit definiertem Pegel in den Schlaf schicken.

**Der Werksstand laesst beide Pads im Deep Sleep floaten.** Der Schlafpfad
raeumt so auf:

    GPS_shutdown();            // digitalWrite(GPS_POWER, LOW); GPS_RESET bleibt
    ...
    gpio_reset();              // gpio_reset_pin(12), (25), ... -> Eingang + Pull-up
    esp_deep_sleep_start();

`gpio_reset_pin()` macht aus beiden Ausgaengen wieder Eingaenge mit Pull-up.
Der Pull-up liegt in der digitalen Domaene, und die wird im Deep Sleep
abgeschaltet -- **im Schlaf haengt an beiden Pads nichts mehr.**

Zwei Folgen, und die zweite ist die teure:

* **GPIO 25 ist GPS_RESET** (`GPS.h:7`). Der Reset-Eingang des GNSS-Moduls
  liegt die ganze Schlafphase auf einem undefinierten Pegel. Was das Modul
  daraus macht, steht in keinem Datenblatt.

* **GPIO 12 ist GPS_POWER** (`GPS.h:6`) -- und zugleich **MTDI**, der
  Strapping-Pin fuer die Flash-Spannung. Am 04.09.2026 am Geraet ausgelesen:

      XPD_SDIO_FORCE (BLOCK0)  Ignore MTDI pin (GPIO12) for VDD_SDIO on reset = False
      Flash voltage (VDD_SDIO) determined by GPIO12 on reset
                               (High for 1.8V, Low/NC for 3.3V)

  Die eFuse ist **nicht** gebrannt, der ROM-Bootlader liest MTDI also bei
  jedem Reset -- und ein Deep-Sleep-Aufwacher ist ein Reset. Ein floatender
  MTDI entscheidet damit bei jedem Aufwachen neu, ob der eingebaute 3,3-V-Flash
  des PICO-D4 mit 3,3 V oder mit 1,8 V betrieben wird.

Genau diese Stelle trennt Draginos ausgeliefertes app0 vom veroeffentlichten
Quelltext. In app0 sind `gpio_hold_en`/`gpio_hold_dis` und
`rtc_gpio_hold_en`/`rtc_gpio_hold_dis` einlinkt -- nachgewiesen ueber den
Pruefstring `Only output-capable GPIO support this function`, der in IDF v4.4
ausschliesslich im Rumpf von `gpio_hold_en()` steht und im Eigenbau fehlt.
Der Quelltext auf GitHub ruft keine dieser Funktionen auf; er kennt nur
`rtc_gpio_isolate(GPIO_NUM_27)` fuer MOSI. app0 meldet sich als v1.4.8 und hat
mit `AT+CHS` und `AT+GF` zwei AT-Befehle, die es im Quelltext nicht gibt --
das Binary ist nicht dieser Quelltext.

Deshalb hier: beide Pads vor dem Schlafen als Ausgang auf **LOW** legen und
halten. LOW ist fuer beide der richtige Wert -- GPS aus, und MTDI LOW heisst
laut eFuse-Zeile 3,3 V, also genau die Spannung, die der Flash braucht.
Geweckt wird der Halt ganz vorn in `setup()` wieder geloest, neben dem
bestehenden Loesen von GPIO 27 aus `fix_holds.py`.

Das ist kein Funktionsumbau: der Schlafstrom aendert sich nicht (beide Pads
liegen auf LOW statt zu floaten), und im Wachbetrieb greift `GPS_Init()` /
`GPS_boot()` unveraendert.

Warum GPIO 12 **nicht** HIGH gehalten wird -- die naheliegende Idee, das
GNSS-Modul ueber den Schlaf warm zu halten, damit der naechste Zyklus ein
Hot Start wird: sie ist wegen derselben eFuse-Zeile unmoeglich. MTDI HIGH beim
Aufwachen heisst 1,8 V an einem 3,3-V-Flash. Das kann app0 auch nicht tun.

`fix_holds.py` ist Voraussetzung -- dort haengt das Loesen der Holds.
"""
import sys, os

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

# --- 1. Vor dem Schlafen: Pegel setzen und halten -------------------------
alt = "    gpio_reset();"
neu = """    gpio_reset();
    /* gpio_reset_pin() hat GPS_POWER (12) und GPS_RESET (25) gerade zu
       Eingaengen mit Pull-up gemacht; der Pull-up faellt im Deep Sleep weg.
       GPIO 12 ist zugleich MTDI: floatend entscheidet er bei jedem Aufwacher
       neu ueber die Flash-Spannung (eFuse XPD_SDIO_FORCE ist nicht gebrannt,
       am 04.09.2026 ausgelesen). LOW = 3,3 V, GPS aus, Reset definiert. */
    rtc_gpio_init(GPIO_NUM_12);
    rtc_gpio_set_direction(GPIO_NUM_12, RTC_GPIO_MODE_OUTPUT_ONLY);
    rtc_gpio_set_level(GPIO_NUM_12, 0);
    rtc_gpio_hold_en(GPIO_NUM_12);
    rtc_gpio_init(GPIO_NUM_25);
    rtc_gpio_set_direction(GPIO_NUM_25, RTC_GPIO_MODE_OUTPUT_ONLY);
    rtc_gpio_set_level(GPIO_NUM_25, 0);
    rtc_gpio_hold_en(GPIO_NUM_25);"""
if s.count(alt) != 2:
    sys.exit("gpio_reset()-Anker nicht zweimal gefunden (%d)" % s.count(alt))
s = s.replace(alt, neu)

# --- 2. Beim Aufwachen: Halt wieder loesen --------------------------------
alt2 = """  rtc_gpio_hold_dis(GPIO_NUM_27);
  rtc_gpio_deinit(GPIO_NUM_27);"""
neu2 = """  rtc_gpio_hold_dis(GPIO_NUM_27);
  rtc_gpio_deinit(GPIO_NUM_27);
  /* Gegenstueck zum Halt aus dem Schlafpfad: erst loesen, dann darf
     GPS_Init()/GPS_boot() die Pads wieder normal schalten. */
  rtc_gpio_hold_dis(GPIO_NUM_12);
  rtc_gpio_deinit(GPIO_NUM_12);
  rtc_gpio_hold_dis(GPIO_NUM_25);
  rtc_gpio_deinit(GPIO_NUM_25);"""
if s.count(alt2) != 1:
    sys.exit("Loeseblock aus fix_holds.py nicht gefunden -- fix_holds.py "
             "muss vor diesem Patch laufen (%d)" % s.count(alt2))
s = s.replace(alt2, neu2)

open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
print("gepatcht:", p)
