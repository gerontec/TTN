// atparms.h -- die AT-Schnittstelle des Knotens.
//
// Der Knoten spricht zusaetzlich zu seinen kurzen Klartext-Kommandos das
// AT-Set der Dragino-Geraete, damit er sich wie ein LA66-Stick einbinden
// laesst: ein Host schickt "AT+SENDB=0,2,2,00ff" und bekommt "OK". Vorlage ist
// der AT+CFG-Abzug des eigenen LA66 in
// TTN/devices/la66_p2p/la66_lorawan_v1.3_cfg.txt; Draginos Firmware dazu liegt
// offen (github.com/dragino/LA66, ASR6601-SDK).
//
// Abweichungen sind bewusst und stehen im README:
//   * AT+APPKEY antwortet maskiert -- der Schluessel bleibt im Geraet.
//   * Die Parameter des rohen Kanals (FRE, SF, BW, CR, POWER, SYNCWORD,
//     PREAMBLE) sind nur lesbar; sie kommen aus loraparms.h und gelten nach
//     jedem Start unveraendert. Ein Schreibversuch antwortet AT_ERROR.
//   * AT+LORAWAN=0|1 schaltet die Betriebsart -- dieselbe Sprache, die die
//     TrackerD-Firmware fuer ihre beiden Anwendungen benutzt. Zweiter
//     Parameter sind Minuten bis zur automatischen Rueckkehr.
//
// Beide Schnittstellen sind gleichwertig: die USB-Konsole und die echte UART
// auf GP0 (TX) / GP1 (RX). Die UART ist der eigentliche Zweck -- ein Host ohne
// USB-Stack (ESP, SPS, Pi ohne freien USB-Port) haengt sich mit zwei Draehten
// an den Knoten.

#ifndef ATPARMS_H
#define ATPARMS_H

// Antwort auf AT+VER / AT+VERSION. Form wie beim LA66 ("EU868 v1.3"): Band,
// Firmwarestand, dahinter das Geraet und was es kann.
#define AT_VERSION  "EU868 v2.0.0 pico-e22 LoRa+LoRaWAN"

#define AT_UART_AN    true    // UART auf GP0/GP1 mitbedienen
#define AT_UART_BAUD  9600    // wie der LA66-Stick ab Werk

// Unaufgefordert gemeldete Empfaenge (im LA66-Format AT+RECVB=<Port>:<Hex>).
// Aus, wenn der Host nur auf eigene Anfragen antworten sehen will.
#define AT_RECV_MELDEN  true

#endif // ATPARMS_H
