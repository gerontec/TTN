// lorawanparms.h -- die LoRaWAN-Seite des Pico-Knotens.
//
// Der Knoten kann zwei Betriebsarten, aber immer nur eine zur Zeit -- beide
// teilen sich denselben SX1262:
//
//   MODUS_LORA     roher Ebyte-Kanal, Parameter in loraparms.h
//                  868.125 MHz SF11 BW500 Syncword 0x55, eigener Rahmen
//   MODUS_LORAWAN  LoRaWAN Class A, EU868, Parameter hier
//                  867.1-868.5 MHz Syncword 0x34, OTAA gegen ChirpStack
//
// Beides ist am Gateway gleichzeitig hoerbar: der DLOS8N 10.9.0.9 hoert die
// acht MultiSF-Kanaele unveraendert auf 0x34 (-> ChirpStack auf dem dell,
// 192.168.5.23:1700) und den Rohkanal chan_Lora_std auf 0x55 (-> lora_raw.py,
// Port 1702). Die Umschaltung ist also allein eine Sache des Knotens, am
// Gateway muss dafuer nichts angefasst werden -- Einzelheiten in
// TTN/gateway/RAWKANAL.md.
//
// Der Stack ist RadioLibs eigene LoRaWAN-Implementierung, nicht Sandeep
// Mistrys pico-lorawan: dessen Glue-Schicht (src/lorawan.c,
// src/boards/rp2040/sx1276-board.c) spricht ausschliesslich den SX1276 an
// (SX1276Read(REG_LR_VERSION) != 0x12 -> Abbruch) und ist ein reines
// pico-sdk/CMake-Projekt. Fuer den SX1262 muesste eine komplette Board-
// Schicht neu geschrieben werden, und in ein Arduino-Binary mit dem
// bestehenden Rohkanal-Betrieb liesse es sich ohnehin nicht bringen. Begruendung
// ausfuehrlich in README.md, Abschnitt "Warum nicht pico-lorawan".

#ifndef LORAWANPARMS_H
#define LORAWANPARMS_H

// --- Betriebsart nach dem allerersten Start --------------------------------
// Danach gilt, was im Flash steht (speicher.h): die zuletzt per USB-Kommando
// `modus lora|lorawan` oder per Downlink gewaehlte Betriebsart ueberlebt
// Neustart und Stromausfall.
#define STARTMODUS  MODUS_LORA

// --- Netz ------------------------------------------------------------------
#define LW_BAND     EU868
#define LW_SUBBAND  0            // EU868 kennt keine Sub-Baender

// --- Kennung ---------------------------------------------------------------
// JoinEUI/AppEUI: im privaten Netz ohne Join-Server bedeutungslos, ChirpStack
// prueft sie nicht. DevEUI ist frei gewaehlt ("PICO" + laufende Nummer) --
// eine herstellerseitige EUI hat der Pico nicht.
#define LW_JOIN_EUI  0x0000000000000000ULL
#define LW_DEV_EUI   0x5049434F00000E22ULL
// Die letzten vier Hexstellen (0E22) sind zugleich die Stationskennung auf dem
// rohen Kanal -- eine Adresse, zwei Betriebsarten.

// Der AppKey steht NICHT hier, sondern in src/lorawan_geheim.h -- die Datei
// ist nicht im Git (Vorlage: lorawan_geheim.h.vorlage) und wird auch nicht in
// den Quelltext im Flash eingebettet. Ohne sie baut die Firmware trotzdem,
// joint dann aber nicht: der Platzhalter unten ist lauter Nullen.
#if defined(__has_include)
#  if __has_include("lorawan_geheim.h")
#    include "lorawan_geheim.h"
#  endif
#endif
#ifndef LW_APP_KEY
#define LW_APP_KEY { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, \
                     0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 }
#endif

// --- Betrieb ---------------------------------------------------------------
#define LW_PORT          1        // Nutzdaten (Zaehlerstand des Knotens)
#define LW_STEUERPORT   10        // Downlink-Kommandos, siehe README
#define LW_INTERVALL_MS  (15UL * 60UL * 1000UL)   // Uplink-Abstand
#define LW_DATENRATE     3        // DR3 = SF9 BW125; ADR verschiebt das spaeter
#define LW_ADR           true
#define LW_BESTAETIGT    false    // unbestaetigte Uplinks, spart Downlink-Zeit

// Der erste Join-Versuch kommt sofort, danach waechst die Pause bis
// LW_JOIN_PAUSE_MAX_MS. Ein Join belegt bei DR3 rund 1,5 s Sendezeit; das
// 1-%-Duty-Cycle-Limit von 868.0-868.6 MHz erzwingt ohnehin Abstand.
#define LW_JOIN_PAUSE_MS      (60UL * 1000UL)
#define LW_JOIN_PAUSE_MAX_MS  (30UL * 60UL * 1000UL)

// Die Sitzung wird nicht nach jedem Uplink in den Flash geschrieben, sondern
// nur jeden n-ten -- ein Flash-Sektor haelt rund 100 000 Loeschungen aus.
// Geht dazwischen der Strom weg, springt der Zaehler beim naechsten Start
// hoechstens um n zurueck; ChirpStack nimmt aufsteigende Luecken an, ein
// Ruecksprung kostet nur diese wenigen Uplinks.
#define LW_SITZUNG_ALLE  8

#endif // LORAWANPARMS_H
