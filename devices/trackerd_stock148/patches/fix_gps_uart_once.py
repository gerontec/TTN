#!/usr/bin/env python3
"""Den GPS-UART je Wachphase nur einmal aufbauen.

`GPS_Init()` ruft ohne jede Bedingung `SerialGPS.begin(9600, SERIAL_8N1, 9, 10)`.
Aufgerufen wird es aus **zwei** Stellen, und welche davon greift, haengt am
Aufwachgrund:

* **Kaltstart** -- `print_wakeup_reason()` setzt `sys.gps_start = 1`. Der Zweig
  `else if(sys.gps_start == 2 && ...)` am Ende von `setup()` wird damit
  uebersprungen. `device_start()` sendet den Statusrahmen und setzt
  `gps_start = 2`; das GPS startet danach **einmal** aus dem
  `exti_flag == 3`-Zweig von `alarm_state()`.

* **Deep-Sleep-Aufwacher** -- `gps_start` steht bereits auf 2 (aus dem EEPROM).
  Jetzt greift der Zweig in `setup()` und ruft `GPS_Init()`/`GPS_boot()`, und
  je nach gespeichertem `exti_flag` ruft `alarm_state()` im selben Wachzyklus
  **noch einmal** `GPS_Init()`.

Ein zweites `begin()` ohne `end()` dazwischen heisst `uart_driver_install()`
auf einen bereits installierten Treiber. Der Arduino-Core, mit dem Draginos
app0 gebaut ist (Arduino IDE 1.8.5, Oktober 2021), spricht den UART
bare-metal an -- im Image ist als einziges UART-Symbol
`uart_enable_intr_mask` einlinkt. Unser Bau mit arduino-esp32 2.0.14 geht
ueber den IDF-Treiber; dort stehen `uart_context`, `uart_event_queue`,
`uart_event_task`, `uart_set_rx_full_threshold` und `uart_set_rx_timeout` im
Image. Dieselbe Quelle, zwei verschiedene UART-Wege.

Das passt auf den gemessenen Befund: **der erste Zyklus nach jedem Kaltstart
traegt eine Position, jeder Deep-Sleep-Zyklus nicht.** Genau die Zyklen, in
denen `begin()` zweimal laufen kann, liefern nichts.

Deshalb hier eine Marke im RAM. Sie ist nach jedem Deep Sleep wieder falsch,
der UART wird also je Wachphase genau einmal aufgebaut und in
`GPS_DeInit()` wieder freigegeben. Die Reihenfolge der Aufrufe bleibt
unveraendert, nur der zweite `begin()` faellt weg.

Traegt die These nicht, kostet der Patch nichts: bei einem einzigen Aufruf je
Wachphase verhaelt er sich wie der Werksstand.
"""
import sys, os

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "GPS.cpp")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

alt = """void GPS_Init(uint8_t power_pin)
{
  pinMode(power_pin,OUTPUT);
  pinMode(GPS_RESET,OUTPUT);
//  SYS();
  SerialGPS.begin(9600, SERIAL_8N1, 9, 10);
}

void GPS_DeInit(void)
{
  SerialGPS.flush();
  SerialGPS.end();
}"""

neu = """/* Wird je Wachphase genau einmal wahr. Liegt im RAM, ist nach jedem
   Deep Sleep also wieder falsch -- gewollt, denn der UART ist dann ohnehin
   weg und muss neu aufgebaut werden. */
static bool gps_uart_offen = false;

void GPS_Init(uint8_t power_pin)
{
  pinMode(power_pin,OUTPUT);
  pinMode(GPS_RESET,OUTPUT);
//  SYS();
  /* GPS_Init() kommt auf dem Aufwachweg zweimal: einmal aus setup()
     (gps_start == 2) und einmal aus alarm_state() (exti_flag == 3). Ein
     zweites begin() ohne end() dazwischen ist uart_driver_install() auf einen
     schon installierten Treiber. */
  if(gps_uart_offen)
  {
    Serial.println(F("GPS: UART schon offen, begin() uebersprungen"));
    return;
  }
  SerialGPS.begin(9600, SERIAL_8N1, 9, 10);
  gps_uart_offen = true;
}

void GPS_DeInit(void)
{
  if(!gps_uart_offen)
    return;
  SerialGPS.flush();
  SerialGPS.end();
  gps_uart_offen = false;
}"""

if s.count(alt) != 1:
    sys.exit("GPS_Init/GPS_DeInit nicht eindeutig gefunden (%d)" % s.count(alt))
s = s.replace(alt, neu, 1)
open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
print("gepatcht:", p)
