// speicher.h -- Betriebsart und LoRaWAN-Sitzung ueber den Stromausfall retten.
//
// Der Pico hat kein EEPROM; das einzige, was einen Neustart ueberlebt, ist der
// Programmflash. Gespeichert wird deshalb in die letzten vier 4-KB-Sektoren
// der 2 MB, und zwar reihum: jede Sicherung nimmt den naechsten Sektor und
// traegt eine hochzaehlende Folgenummer ein, gelesen wird der Sektor mit der
// hoechsten Folgenummer und gueltiger Pruefsumme. Das viertelt den Verschleiss
// und laesst bei einem Stromausfall mitten im Schreiben den vorherigen Stand
// unangetastet -- der neue Sektor ist dann ungueltig, der alte gilt weiter.
//
// Warum die LoRaWAN-Sitzung ueberhaupt in den Flash muss:
//
//   * Der DevNonce eines OTAA-Joins darf sich nie wiederholen. Ein
//     Netzwerkserver weist einen Join mit bereits gesehenem DevNonce als
//     Replay ab -- ohne Sicherung waere nach einem Stromausfall Schluss.
//   * Ohne gesicherte Sitzung wuerde jeder Neustart einen neuen Join
//     ausloesen: Sendezeit, Downlink und eine neue DevAddr fuer nichts.

#ifndef SPEICHER_H
#define SPEICHER_H

#include <Arduino.h>
#include <RadioLib.h>

#define MODUS_LORA     0    // roher Ebyte-Kanal (loraparms.h)
#define MODUS_LORAWAN  1    // LoRaWAN Class A (lorawanparms.h)

// Alles, was den Neustart ueberleben muss. Wird als Ganzes geschrieben.
struct Zustand {
  uint8_t modus;        // MODUS_LORA oder MODUS_LORAWAN
  uint8_t hatNonces;    // 1 = nonces[] traegt einen gueltigen Stand
  uint8_t hatSitzung;   // 1 = sitzung[] traegt eine gueltige Sitzung
  uint8_t reserve;
  uint8_t nonces[RADIOLIB_LORAWAN_NONCES_BUF_SIZE];
  uint8_t sitzung[RADIOLIB_LORAWAN_SESSION_BUF_SIZE];
};

// Liest den juengsten gueltigen Sektor. false = noch nie geschrieben oder
// alles unbrauchbar; z bleibt dann unveraendert.
bool zustandLaden(Zustand &z);

// Schreibt in den naechsten Sektor und liest zur Probe zurueck.
bool zustandSichern(const Zustand &z);

// Folgenummer der letzten gueltigen Sicherung (0 = noch keine). Nur fuer die
// Anzeige in `lwstat`.
uint32_t zustandFolge();

#endif // SPEICHER_H
