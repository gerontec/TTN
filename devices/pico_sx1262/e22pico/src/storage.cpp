// storage.cpp -- a ring buffer across four flash sectors, see storage.h.

#include "storage.h"

extern "C" {
#include "hardware/flash.h"
#include "hardware/sync.h"
#include "hardware/regs/addressmap.h"
}

#ifndef PICO_FLASH_SIZE_BYTES
// The Raspberry Pi Pico has 2 MB; the mbed core does not define the size.
#define PICO_FLASH_SIZE_BYTES (2u * 1024u * 1024u)
#endif

#define SEKTOREN  4
#define MAGIC     0x50494B4Fu   // "PIKO"
#define VERSION   1

// What actually sits in the flash.
struct Block {
  uint32_t magic;
  uint16_t version;
  uint16_t laenge;   // sizeof(Zustand) -- catches later struct changes
  uint32_t folge;    // increasing, decides which sector is the youngest
  uint32_t pruef;    // CRC32 over z
  Zustand  z;
};

static_assert(sizeof(Block) <= FLASH_SECTOR_SIZE, "block does not fit into a sector");

// flash_range_program wants full 256-byte pages from RAM.
static uint8_t puffer[((sizeof(Block) + FLASH_PAGE_SIZE - 1) / FLASH_PAGE_SIZE) * FLASH_PAGE_SIZE];

static uint32_t letzteFolge = 0;
static uint8_t  naechsterSektor = 0;
static bool     gelesen = false;

static uint32_t sektorOffset(uint8_t i) {
  return PICO_FLASH_SIZE_BYTES - (uint32_t)(SEKTOREN - i) * FLASH_SECTOR_SIZE;
}

// CRC32 (IEEE, as in zlib) bitwise -- no table, 300 bytes cost nothing.
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
  if (!gelesen) {                 // without loading first the sequence would
    Zustand egal;                 // be 0 and we would overwrite the youngest
    zustandLaden(egal);           // state
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
  // While erasing and programming, no code may run from flash -- the XIP bus
  // is dead during that time. Disabling interrupts is the prescribed way on
  // the RP2040 (about 40 ms in which the USB console stands still).
  const uint32_t ints = save_and_disable_interrupts();
  flash_range_erase(off, FLASH_SECTOR_SIZE);
  flash_range_program(off, puffer, sizeof(puffer));
  restore_interrupts(ints);

  const Block *frisch = sektor(naechsterSektor);   // read back from flash
  if (!gueltig(frisch) || frisch->folge != b.folge) return false;

  letzteFolge = b.folge;
  naechsterSektor = (uint8_t)((naechsterSektor + 1) % SEKTOREN);
  return true;
}

uint32_t zustandFolge() { return letzteFolge; }
