#!/usr/bin/env python3
"""Im Bewegungstakt auch wirklich suchen: GPS nicht mehr an interrupts_flag haengen.

`print_wakeup_reason()` setzt im Timer-Zweig

    if(sys.Intwk == 1 && button_Count1 != 0 && sys.pedometer == 0 && TDC_flag == 1)
      interrupts_flag = 1;

und die Suche in `setup()` verlangt

    else if(sys.gps_start == 2 && sys.loggpsdata_send == 0 && interrupts_flag == 0)

`button_Count1` wird bei jedem Bewegungs-Weckruf gesetzt, `TDC_flag` bei jedem
Schlaf im MTDC-Takt, und beide ueberleben im RTC-Speicher. Beim Gehen ist die
Bedingung deshalb **dauernd** erfuellt: der Positionsrahmen geht alle MTDC
Sekunden hinaus, aber ohne dass ueberhaupt gesucht wurde -- mit der alten oder
gar keiner Position. Ausgerechnet im einzigen Betriebsfall, fuer den der
Bewegungsmodus da ist.

`interrupts_flag` ist dabei gar nicht als GPS-Schalter gedacht: `loop()`
schaerft ueber `interrupts_flag == 1` den Beschleunigungssensor neu und fuehrt
die MTDC-Buchhaltung. Wer die Zuweisung streicht, nimmt der Bewegungserkennung
die Grundlage. Deshalb wird hier nicht der Zaehler geaendert, sondern die
**Entscheidung ueber die Suche davon getrennt**: ein eigener Merker, gesetzt
allein an der Bewegungsstelle.

Der Alarmzweig (`print_wakeup_reason()`, EXT1) setzt `interrupts_flag` ebenfalls
auf 1 und bleibt bewusst unberuehrt -- ein Alarm muss sofort hinaus und darf
nicht bis zu `AT+FTIME` Sekunden auf einen Fix warten.

**Der Preis:** der Takt in Bewegung ist danach nicht mehr MTDC, sondern MTDC
plus die tatsaechliche Suchzeit. Warm gelaufen sind das wenige Sekunden; ohne
Empfang deckelt `AT+FTIME` es auf 180 s, dann werden aus 3 Minuten bis zu 6.
Wem das zu traege ist, setzt FTIME herunter (Downlink `AA 003C` = 60 s) --
lieber ein kurzer Suchlauf je Takt als gar keiner.
"""
import os
import re
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

if "gps_trotz_bewegung" in s:
    sys.exit("schon gepatcht")

# --- 1. eigener Merker neben interrupts_flag --------------------------------
anker = "int interrupts_flag = 0;"
if s.count(anker) != 1:
    sys.exit("Deklaration nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, anker + """
/* Der Weckruf kam im Bewegungstakt: gesucht wird trotzdem. Eigener Merker,
   weil interrupts_flag in loop() die Neuschaerfung des Sensors steuert und
   im Alarmzweig dieselbe 1 traegt -- dort soll gerade nicht gesucht werden. */
int gps_trotz_bewegung = 0;""")

# --- 2. an der Bewegungsstelle mitsetzen ------------------------------------
muster = re.compile(
    r"(if\(sys\.Intwk == 1 && button_Count1 != 0 && sys\.pedometer == 0 && TDC_flag == 1\)\s*\n"
    r"\s*\{\s*\n)(\s*)(interrupts_flag = 1;)")
if len(muster.findall(s)) != 1:
    sys.exit("Bewegungsstelle nicht eindeutig (%d)" % len(muster.findall(s)))
s = muster.sub(lambda m: "%s%s%s\n%sgps_trotz_bewegung = 1;"
               % (m.group(1), m.group(2), m.group(3), m.group(2)), s)

# --- 3. Suche auch dann zulassen --------------------------------------------
anker = ("  else if(sys.gps_start == 2 && sys.loggpsdata_send == 0 && "
         "interrupts_flag == 0)")
if s.count(anker) != 1:
    sys.exit("GPS-Bedingung nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker,
              "  else if(sys.gps_start == 2 && sys.loggpsdata_send == 0 &&\n"
              "          (interrupts_flag == 0 || gps_trotz_bewegung == 1))")

open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
print("gepatcht:", p)
