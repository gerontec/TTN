"""Bettet den eigenen Quelltext in die Firmware ein.

Laeuft als PlatformIO-Vorstufe (extra_scripts = pre:quelltext_einbetten.py):
vor jedem Bau wird src/quelltext.h aus main.cpp und loraparms.h neu erzeugt.
Damit gibt das USB-Kommando `src` zwangslaeufig genau den Quelltext aus, aus
dem die laufende Firmware gebaut wurde -- eine Abweichung kann gar nicht erst
entstehen, weil niemand die Einbettung von Hand nachziehen muss.

Der Anlass: der geflashte Stand vom 19.08. lag nur als Arbeitskopie in
/home/gh/e22pico und in keinem Commit. Auf dem Geraet selbst ist er nicht mehr
verlierbar.
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
DATEIEN = [("QUELLTEXT_MAIN", "main.cpp"), ("QUELLTEXT_PARMS", "loraparms.h")]


def erzeuge():
    teile = [
        "// AUTOMATISCH ERZEUGT von quelltext_einbetten.py -- nicht von Hand aendern.",
        "// Aenderungen gehoeren in main.cpp bzw. loraparms.h; der naechste Bau",
        "// erzeugt diese Datei daraus neu.",
        "",
        "#ifndef QUELLTEXT_H",
        "#define QUELLTEXT_H",
        "",
    ]
    for name, datei in DATEIEN:
        with open(os.path.join(SRC, datei), encoding="utf-8") as f:
            text = f.read()
        if ')%s"' % BEGRENZER in text:
            raise SystemExit("%s enthaelt den Begrenzer -- Literal waere zerstoert" % datei)
        teile.append('static const char %s_NAME[] = "%s";' % (name, datei))
        teile.append("static const char %s[] = R\"%s(%s)%s\";" % (name, BEGRENZER, text, BEGRENZER))
        teile.append("")
    teile += ["#endif // QUELLTEXT_H", ""]
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
        print("quelltext.h neu erzeugt (%d Byte eingebettet)"
              % sum(os.path.getsize(os.path.join(SRC, d)) for _, d in DATEIEN))
    else:
        print("quelltext.h unveraendert")


erzeuge()
