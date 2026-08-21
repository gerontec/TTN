// storage.h -- carrying the operating mode and the LoRaWAN session across a
// power cut.
//
// The Pico has no EEPROM; the only thing that survives a restart is the
// program flash. Data is therefore written into the last four 4 KB sectors of
// the 2 MB, and in turn: every save takes the next sector and writes an
// increasing sequence number, and the sector with the highest sequence number
// and a valid checksum is the one that is read back. That divides the wear by
// four and leaves the previous state untouched if the power fails mid-write --
// the new sector is then invalid and the old one still applies.
//
// Why the LoRaWAN session has to go into flash at all:
//
//   * The DevNonce of an OTAA join must never repeat. A network server rejects
//     a join with a DevNonce it has seen before as a replay -- without saving
//     it, a power cut would be the end.
//   * Without a saved session every restart would trigger a new join: air
//     time, a downlink and a fresh DevAddr, all for nothing.

#ifndef STORAGE_H
#define STORAGE_H

#include <Arduino.h>
#include <RadioLib.h>

#define MODE_LORA     0    // raw Ebyte channel (loraparms.h)
#define MODE_LORAWAN  1    // LoRaWAN class A (lorawanparms.h)

// Everything that has to survive a restart. Written as one block.
struct Zustand {
  uint8_t modus;        // MODE_LORA or MODE_LORAWAN
  uint8_t hatNonces;    // 1 = nonces[] holds a valid state
  uint8_t hatSitzung;   // 1 = sitzung[] holds a valid session
  uint8_t reserve;
  uint8_t nonces[RADIOLIB_LORAWAN_NONCES_BUF_SIZE];
  uint8_t sitzung[RADIOLIB_LORAWAN_SESSION_BUF_SIZE];
};

// Reads the youngest valid sector. false = never written or all unusable; z is
// then left unchanged.
bool zustandLaden(Zustand &z);

// Writes into the next sector and reads it back as a check.
bool zustandSichern(const Zustand &z);

// Sequence number of the last valid save (0 = none yet). For the `lwstat`
// display only.
uint32_t zustandFolge();

#endif // STORAGE_H
