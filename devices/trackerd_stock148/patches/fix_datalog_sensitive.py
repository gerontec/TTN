#!/usr/bin/env python3
"""Den Datalog empfindlicher machen: beim ersten Verdacht puffern, nie loeschen.

Der Werks-Datalog haengt an genau einem Ereignis -- dem ausbleibenden ACK eines
bestaetigten Uplinks (`TXRX_NACK`). Zwei Luecken darin kosten Spur:

## 1. Ein NACK loescht den Puffer

Im NACK-Zweig steht ab Werk:

    if(sys.addr_gps_write>0 && sys.addr_gps_write<14)
    {
      sys.GPSDATA_CLEAR();          // der ganze Spurpuffer
      sys.addr_gps_write = 0;
    }
    else if(sensor.latitude !=0 && sensor.longitude !=0)
    {
      sys.gps_data_Weite();
    }

Ein Datensatz ist 15 Byte lang (`gps_data_Weite()` in `common.cpp`), der
Schreibzeiger springt also 0, 15, 30, ... Der Bereich 1 bis 13 ist der
Zustand *zwischen* zwei Datensaetzen -- ein abgebrochener Schreibvorgang, ein
halb beschriebener NVS-Bereich, ein Rest aus einem anderen Firmwarestand.
Trifft ein NACK das Geraet in diesem Zustand, wirft der Werksstand **die
gesamte gepufferte Spur weg**, statt den neuen Fix anzuhaengen. Genau in dem
Moment also, in dem der Puffer gebraucht wird.

Hier bleibt nur das Anhaengen uebrig. Der Ring darf ueberlaufen -- das ist
verkraftbar, er behaelt dann die juengsten 273 Fixes --, aber er wird nicht
mehr durch ein einzelnes ungehoertes Paket geleert.

## 2. Kein Join heisst kein NACK

Ist ueberhaupt kein Gateway erreichbar, kommt es gar nicht erst zu einem
bestaetigten Uplink: LMIC bleibt im Join haengen und meldet `EV_JOIN_FAILED`
bzw. `EV_REJOIN_FAILED`. Der ACK, an dem der Werks-Datalog haengt, kann dann
nie ausbleiben, weil nie einer erwartet wird -- **jede Position dieses Zyklus
ist verloren**, obwohl der Verdacht auf ein fehlendes Gateway hier am
deutlichsten ist.

Deshalb wird auch dort gepuffert. Einmal je Wachphase: `datalog_gebuffert`
liegt im RAM und ist nach jedem Deep Sleep wieder falsch, mehrere
Join-Versuche innerhalb eines Zyklus legen also nur einen Datensatz ab.

Beide Aenderungen setzen `AT+PNACKMD=1` voraus -- das setzt
`fix_defaults_on.py` ab Werk.

Was **nicht** geaendert wird: ein Zyklus ohne gueltigen Fix legt weiterhin
keinen Datensatz ab. Ein Null-Datensatz traegt keine Ortsangabe und kostet
einen der 273 Plaetze; im Tunnel waere der Puffer sonst voll, bevor die erste
brauchbare Position darin steht.
"""
import re
import sys
import os

src = sys.argv[1] if len(sys.argv) > 1 else "src"
p = os.path.join(src, "TrackerD.ino")
s = open(p, encoding="utf-8", errors="surrogateescape").read()

# --- 1. NACK-Zweig: nur noch anhaengen, nie loeschen ----------------------
loeschblock = re.compile(
    r"if\(sys\.addr_gps_write>0\s*&&\s*sys\.addr_gps_write<14\)\s*"
    r"\{\s*sys\.GPSDATA_CLEAR\(\);\s*sys\.addr_gps_write\s*=\s*0\s*;\s*\}\s*"
    r"else if\(sensor\.latitude\s*!=\s*0\s*&&\s*sensor\.longitude\s*!=\s*0\)\s*"
    r"\{\s*sys\.gps_data_Weite\(\);\s*sys\.loggpsdata_send\s*=\s*0;\s*\}")
treffer = loeschblock.findall(s)
if len(treffer) != 2:
    sys.exit("NACK-Loeschblock nicht zweimal gefunden (%d)" % len(treffer))
ersatz = """if(sensor.latitude != 0 && sensor.longitude != 0)
                {
                  /* Ungehoerter Uplink: die Position sofort in den Puffer.
                     Der Werksstand loeschte hier bei 0 < addr_gps_write < 14
                     den ganzen Spurpuffer -- also im Zustand zwischen zwei
                     Datensaetzen. Ein einziges ungehoertes Paket warf damit
                     die gesamte gepufferte Spur weg. */
                  sys.gps_data_Weite();
                }"""
s = loeschblock.sub(lambda m: ersatz, s)

# --- 2. Hilfsfunktion vor den Ereignisbehandlern --------------------------
anker = "void LIS3DH_configIntterupts(void);"
helfer = """void LIS3DH_configIntterupts(void);

/* Fruehester Verdacht auf ein fehlendes Gateway: es kommt gar kein Join
   zustande. Dann wird nie ein ACK erwartet, der ausbleiben koennte -- der
   Werks-Datalog haengt aber genau daran und laesst die Position fallen.
   Einmal je Wachphase puffern; die Marke liegt im RAM und ist nach jedem
   Deep Sleep wieder falsch. */
static bool datalog_gebuffert = false;
static void datalog_verdacht(void)
{
  if(datalog_gebuffert)
    return;
  if(sys.PNACKmd == 1 && sensor.latitude != 0 && sensor.longitude != 0)
  {
    datalog_gebuffert = true;
    sys.gps_data_Weite();
    Serial.println(F("Datalog: kein Join -- Position gepuffert"));
  }
}"""
if s.count(anker) != 1:
    sys.exit("Anker fuer die Hilfsfunktion nicht eindeutig (%d)" % s.count(anker))
s = s.replace(anker, helfer, 1)

# --- 3. Join-Fehlschlaege puffern lassen ----------------------------------
for ereignis in ("EV_JOIN_FAILED", "EV_REJOIN_FAILED"):
    alt = ('        case %s:\n'
           '            Serial.println(F("%s"));\n'
           '            break;' % (ereignis, ereignis))
    neu = ('        case %s:\n'
           '            Serial.println(F("%s"));\n'
           '            datalog_verdacht();\n'
           '            break;' % (ereignis, ereignis))
    if s.count(alt) != 2:
        sys.exit("%s nicht zweimal gefunden (%d)" % (ereignis, s.count(alt)))
    s = s.replace(alt, neu)

open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
print("gepatcht:", p)
