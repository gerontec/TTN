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
// Rundruf hebelt den NETID-Filter aus (Handbuch-Prioritaetsregel).
#define ADRESSE         {0x00, 0xFF, 0xFF}
// Dieselbe Rundruf-Adresse, aber NETID BB (jenseits des E90-Relais). Der
// PONG geht mit beiden NETIDs raus, damit keiner der beiden Filter greift.
#define ADRESSE_NETIDBB {0xBB, 0xFF, 0xFF}

// --- Antwortverhalten ------------------------------------------------------
// Der E22 ist nach eigener Aussendung ~1-2 s taub (gemessen: 0/8 bei
// 0,3-1,0 s). Eine sofortige Antwort faellt deshalb in dieses Fenster;
// die Verzoegerung schiebt den PONG dahinter.
#define PONG_VERZOEGERUNG_MS  2500

#endif // LORAPARMS_H
