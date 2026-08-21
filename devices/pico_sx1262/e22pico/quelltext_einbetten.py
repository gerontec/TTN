"""Bettet den eigenen Quelltext in die Firmware ein.

Laeuft als PlatformIO-Vorstufe (extra_scripts = pre:quelltext_einbetten.py):
vor jedem Bau wird src/quelltext.h aus main.cpp und loraparms.h neu erzeugt.
Damit gibt das USB-Kommando `src` zwangslaeufig genau den Quelltext aus, aus
dem die laufende Firmware gebaut wurde -- eine Abweichung kann gar nicht erst
entstehen, weil niemand die Einbettung von Hand nachziehen muss.

Der Anlass: der geflashte Stand vom 19.08. lag nur als Arbeitskopie in
/home/gh/e22pico und in keinem Commit. Auf dem Geraet selbst ist er nicht mehr
verlierbar.

Eingebettet wird alles in src/, ausser der erzeugten quelltext.h selbst und
lorawan_geheim.h -- der AppKey soll nicht auch noch ueber `src` an der USB-
Konsole herauskommen. Neue Quelldateien landen also von selbst im Flash,
niemand muss eine Liste nachziehen.
"""
import os

# PlatformIO fuehrt Vorstufen ueber SCons aus, dort gibt es kein __file__ --
# der Projektpfad kommt dann aus der Bauumgebung. Von Hand aufgerufen greift
# der zweite Weg, damit sich quelltext.h auch ohne pio erzeugen laesst.
try:
    Import("env")  # noqa: F821 -- von SCons bereitgestellt
    HIER = env["PROJECT_DIR"]  # noqa: F821
except NameError:
    HIER = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HIER, "src")
ZIEL = os.path.join(SRC, "quelltext.h")
# Begrenzer des Roh-Stringliterals. Darf im Quelltext nicht vorkommen -- wird
# unten geprueft, sonst zerfaellt das Literal und der Bau bricht kryptisch ab.
BEGRENZER = "QUELLE"
# Nicht einbetten: die erzeugte Datei selbst (sonst waechst sie bei jedem Bau)
# und der AppKey.
AUSGENOMMEN = {"quelltext.h", "lorawan_geheim.h"}


def dateien():
    """Alle Quelldateien in src/, in fester Reihenfolge."""
    return sorted(d for d in os.listdir(SRC)
                  if d.endswith((".cpp", ".h")) and d not in AUSGENOMMEN)


def erzeuge():
    teile = [
        "// AUTOMATISCH ERZEUGT von quelltext_einbetten.py -- nicht von Hand aendern.",
        "// Aenderungen gehoeren in die Quellen in src/; der naechste Bau erzeugt",
        "// diese Datei daraus neu.",
        "",
        "#ifndef QUELLTEXT_H",
        "#define QUELLTEXT_H",
        "",
    ]
    liste = dateien()
    for i, datei in enumerate(liste):
        with open(os.path.join(SRC, datei), encoding="utf-8") as f:
            text = f.read()
        if ')%s"' % BEGRENZER in text:
            raise SystemExit("%s enthaelt den Begrenzer -- Literal waere zerstoert" % datei)
        teile.append("static const char QUELLTEXT_%d[] = R\"%s(%s)%s\";" % (i, BEGRENZER, text, BEGRENZER))
        teile.append("")
    teile.append("#define QUELLTEXT_ANZAHL %d" % len(liste))
    teile.append("static const char *const QUELLTEXT_NAMEN[] = {%s};"
                 % ", ".join('"%s"' % d for d in liste))
    teile.append("static const char *const QUELLTEXT_TEXTE[] = {%s};"
                 % ", ".join("QUELLTEXT_%d" % i for i in range(len(liste))))
    teile += ["", "#endif // QUELLTEXT_H", ""]
    neu = "\n".join(teile)

    # Nur schreiben, wenn sich etwas geaendert hat -- sonst baut PlatformIO bei
    # jedem Aufruf alles neu, weil der Zeitstempel der Datei springt.
    alt = None
    if os.path.exists(ZIEL):
        with open(ZIEL, encoding="utf-8") as f:
            alt = f.read()
    if alt != neu:
        with open(ZIEL, "w", encoding="utf-8") as f:
            f.write(neu)
        print("quelltext.h neu erzeugt (%d Dateien, %d Byte eingebettet)"
              % (len(dateien()),
                 sum(os.path.getsize(os.path.join(SRC, d)) for d in dateien())))
    else:
        print("quelltext.h unveraendert")


erzeuge()
