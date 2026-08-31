# Ringpuffer auf dem Rechner pruefen

Die Fehler im Spurpuffer stecken im Ring, nicht im Funk: Sektorgrenze,
Kaltstart-Scan, Reihenfolge beim Nachliefern. Das laesst sich ohne Geraet
pruefen — `esp_partition_write` verhaelt sich hier wie NOR-Flash und kann
Bits nur loeschen, genau darauf baut das "zugestellt"-Kennzeichen auf.

    g++ -std=c++17 -I. -I../src -o trktest main.cpp ../src/tracklog.cpp && ./trktest

Geprueft werden: Live-Betrieb mit sofortiger Quittung, 500 Fixes im Funkloch,
Nachliefern in Buendeln (500 Datensaetze in 42 Uplinks), Kaltstart-Scan,
Ueberlauf des Rings und Fremdinhalt im spiffs-Bereich.
