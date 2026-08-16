"""Selbststart der Relaisstelle Brauneck.

Die Station laeuft rein solar: der Victron-Laderegler schaltet den Verbraucher
morgens **schlagartig** zu und abends wieder ab. Es gibt also keine langsam
ansteigende Versorgung und keinen Brown-out beim Hochlauf -- dafuer aber jeden
Tag einen harten Kaltstart, bei dem niemand oben ist. Deshalb ist dieses main.py
Pflicht und nicht Kuer.

Was daraus folgt:

* Ein Absturz darf die Station nicht bis zum naechsten Morgen stilllegen, also
  wird wiederholt und notfalls das Board neu gestartet, statt in den REPL zu
  fallen.
* Harte Abschaltungen koennen einen laufenden Flash-Schreibvorgang treffen.
  `fernwirk.konf_laden()` faengt eine beschaedigte /relais.json ab und faellt
  auf die Vorgaben zurueck -- die Station kommt dann mit Standardwerten hoch,
  aber sie kommt hoch.
"""
import machine
import utime

VERSUCHE = 5


def start():
    for versuch in range(1, VERSUCHE + 1):
        try:
            import repeater
            repeater.run()
            return
        except Exception as e:          # noqa: BLE001 -- oben hilft niemand
            print("Start %d/%d fehlgeschlagen: %r" % (versuch, VERSUCHE, e))
            utime.sleep(5)
    print("kein Start moeglich, Neustart des Boards")
    utime.sleep(5)
    machine.reset()


start()
