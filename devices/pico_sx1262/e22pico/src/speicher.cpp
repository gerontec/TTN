// speicher.cpp -- Ringpuffer ueber vier Flash-Sektoren, siehe speicher.h.

#include "speicher.h"

extern "C" {
#include "hardware/flash.h"
#include "hardware/sync.h"
#include "hardware/regs/addressmap.h"
}

#ifndef PICO_FLASH_SIZE_BYTES
// Der Raspberry Pi Pico hat 2 MB; der mbed-Kern definiert die Groesse nicht.
#define PICO_FLASH_SIZE_BYTES (2u * 1024u * 1024u)
#endif

#define SEKTOREN  4
#define MAGIC     0x50494B4Fu   // "PIKO"
#define VERSION   1

// Was tatsaechlich im Flash steht.
struct Block {
  uint32_t magic;
  uint16_t version;
  uint16_t laenge;   // sizeof(Zustand) -- faengt spaetere Strukturaenderungen
  uint32_t folge;    // hochzaehlend, bestimmt den juengsten Sektor
  uint32_t pruef;    // CRC32 ueber z
  Zustand  z;
};

static_assert(sizeof(Block) <= FLASH_SECTOR_SIZE, "Block passt nicht in einen Sektor");

// flash_range_program will volle 256-Byte-Seiten aus dem RAM.
static uint8_t puffer[((sizeof(Block) + FLASH_PAGE_SIZE - 1) / FLASH_PAGE_SIZE) * FLASH_PAGE_SIZE];

static uint32_t letzteFolge = 0;
static uint8_t  naechsterSektor = 0;
static bool     gelesen = false;

static uint32_t sektorOffset(uint8_t i) {
  return PICO_FLASH_SIZE_BYTES - (uint32_t)(SEKTOREN - i) * FLASH_SECTOR_SIZE;
}

// CRC32 (IEEE, wie zlib) bitweise -- ohne Tabelle, 300 Byte kosten nichts.
static uint32_t crc32(const void *daten, size_t len) {
  const uint8_t *p = (const uint8_t *)daten;
  uint32_t c = 0xFFFFFFFFu;
  for (size_t i = 0; i < len; i++) {
    c ^= p[i];
    for (int b = 0; b < 8; b++) c = (c >> 1) ^ (0xEDB88320u & (uint32_t)(-(int32_t)(c & 1)));
  }
  return c ^ 0xFFFFFFFFu;
}

static const Block *sektor(uint8_t i) {
  return (const Block *)(XIP_BASE + sektorOffset(i));
}

static bool gueltig(const Block *b) {
  return b->magic == MAGIC && b->version == VERSION &&
         b->laenge == sizeof(Zustand) && b->pruef == crc32(&b->z, sizeof(Zustand));
}

bool zustandLaden(Zustand &z) {
  int bester = -1;
  for (uint8_t i = 0; i < SEKTOREN; i++) {
    const Block *b = sektor(i);
    if (!gueltig(b)) continue;
    if (bester < 0 || b->folge > sektor(bester)->folge) bester = i;
  }
  gelesen = true;
  if (bester < 0) {
    letzteFolge = 0;
    naechsterSektor = 0;
    return false;
  }
  const Block *b = sektor(bester);
  memcpy(&z, &b->z, sizeof(Zustand));
  letzteFolge = b->folge;
  naechsterSektor = (uint8_t)((bester + 1) % SEKTOREN);
  return true;
}

bool zustandSichern(const Zustand &z) {
  if (!gelesen) {                 // ohne vorheriges Laden waere die Folge 0
    Zustand egal;                 // und wir wuerden den juengsten Stand
    zustandLaden(egal);           // ueberschreiben
  }

  Block b;
  memset(&b, 0, sizeof(b));
  b.magic = MAGIC;
  b.version = VERSION;
  b.laenge = sizeof(Zustand);
  b.folge = letzteFolge + 1;
  b.z = z;
  b.pruef = crc32(&b.z, sizeof(Zustand));

  memset(puffer, 0xFF, sizeof(puffer));
  memcpy(puffer, &b, sizeof(b));

  const uint32_t off = sektorOffset(naechsterSektor);
  // Waehrend Loeschen und Schreiben darf kein Code aus dem Flash laufen --
  // der XIP-Bus ist dann tot. Interrupts sperren ist auf dem RP2040 der
  // vorgeschriebene Weg (rund 40 ms, in denen die USB-Konsole steht).
  const uint32_t ints = save_and_disable_interrupts();
  flash_range_erase(off, FLASH_SECTOR_SIZE);
  flash_range_program(off, puffer, sizeof(puffer));
  restore_interrupts(ints);

  const Block *frisch = sektor(naechsterSektor);   // Rueckprobe aus dem Flash
  if (!gueltig(frisch) || frisch->folge != b.folge) return false;

  letzteFolge = b.folge;
  naechsterSektor = (uint8_t)((naechsterSektor + 1) % SEKTOREN);
  return true;
}

uint32_t zustandFolge() { return letzteFolge; }
