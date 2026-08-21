// loraparms.h -- die einzigen LoRa-Parameter des Pico-Knotens.
//
// Nach jedem Start (auch nach Stromausfall) liest die Firmware diese Werte;
// eine Konfiguration von aussen gibt es nicht. Aenderungen hier erfordern
// einen Neubau und das Einspielen der firmware.uf2.
//
// Alle On-Air-Werte sind an der Luft gemessen, nicht aus Handbuechern --
// belegt in TTN/devices/pico_sx1262/e22spec.md.

#ifndef LORAPARMS_H
#define LORAPARMS_H

// --- Verdrahtung des Waveshare Pico-LoRa-SX1262 ---------------------------
#define PIN_SCK    10
#define PIN_MOSI   11
#define PIN_MISO   12
#define PIN_CS     3
#define PIN_BUSY   2
#define PIN_RST    15
#define PIN_DIO1   20

// --- On-Air-Profil (Ebyte-Werkswerte) -------------------------------------
#define FREQ_MHZ   868.125f   // Kanal 18: 850.125 + 18
#define BW_KHZ     500.0f     // die Ebyte-Leiter ist durchgehend BW500
#define LORA_SF    11
#define LORA_CR    5          // RadioLib-Kodierung: 5 = 4/5
#define SYNCWORD   0x55       // Register 0x0740 liest danach 54 54
#define POWER_DBM  14         // 25 mW ERP, Grenze 868.0-868.6 MHz
#define PREAMBLE   8
#define TCXO_V     1.8f       // TCXO an DIO3; ohne Spannung kein Oszillator
#define LDRO_ON    true       // gemessen: mit LDRO 0 nur CRC-Fehler

// --- Ebyte-Rahmen ----------------------------------------------------------
#define MAGIC0     0x2C
#define MAGIC1     0x12       // 0x12 = Kanal 18
#define XORKEY     0x12
// NETID 00 + Rundruf FFFF: Standard, auch fuer den Parameter-Beacon.
#define ADRESSE         {0x00, 0xFF, 0xFF}
// Dieselbe Rundruf-Adresse, aber NETID BB (jenseits des E90-Relais). Der
// PONG geht mit beiden NETIDs raus, damit mindestens eine durchkommt.
// Gemessen 19.08.: der Rundruf hebelt den NETID-Filter NICHT aus --
// der E22 (NETID 00) hat ausschliesslich die N00-Kopien angenommen.
#define ADRESSE_NETIDBB {0xBB, 0xFF, 0xFF}

// --- Antwortverhalten ------------------------------------------------------
// Der PONG kommt verzoegert: eine fruehere Messreihe sah Antworten in der
// ersten Sekunde nach einer E22-Aussendung bei 0/8 (e22spec.md, Abschnitt 4).
// Sicher ist die Taubheit nicht -- am 19.08. wurde ein Relais-Rahmen nur
// 0,1 s nach der eigenen Aussendung des E22 von ihm empfangen. Die
// Verzoegerung bleibt einstweilen, sie schadet nicht.
#define PONG_VERZOEGERUNG_MS  2500

// --- Eigene Stationskennung ------------------------------------------------
// Vier Hexstellen, und zwar die letzten vier der Geraeteadresse (DevEUI in
// lorawanparms.h) -- genau wie der TrackerD seine 076C aus a840414f1188076c
// ableitet und das Gateway seine E09C aus der MAC. Die Kennung wird deshalb
// nicht hier festgelegt, sondern in main.cpp aus LW_DEV_EUI gerechnet; sie
// steht in jeder Fernwirk-Antwort (A><ID>>...).

// --- Relais (Ebyte-Name fuer diese Funktion) -------------------------------
// Wenn an, sendet der Pico jeden empfangenen Rahmen einmal weiter, mit
// einem "R" vor der Nutzlast. Das "R" kennzeichnet die Weitergabe: das
// Gateway erkennt daran einen Forward, und Rahmen, die schon mit "R"
// beginnen, werden nicht nochmal weitergeleitet (Schleifenschutz).
// Zur Laufzeit umschaltbar ueber USB: relais | relais on | relais off
#define RELAIS_ENABLE  true

#endif // LORAPARMS_H
