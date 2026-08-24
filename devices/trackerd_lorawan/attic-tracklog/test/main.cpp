#include "tracklog.h"
#include <cstdio>
#include <cassert>
#include "esp_partition.h"

uint8_t FLASH[0x30000];
esp_partition_t PART = { 0x30000 };

static void rec_fill(uint8_t *r, int n)
{
  for (int i = 0; i < 15; i++) r[i] = (uint8_t)(n + i);
}

int main()
{
  memset(FLASH, 0xFF, sizeof(FLASH));
  assert(tracklog_begin(true));
  printf("-- leer: offen=%u\n", tracklog_pending());
  assert(tracklog_pending() == 0);

  uint8_t r[17], out[256];
  uint32_t first;

  /* 1) Live-Betrieb: anhaengen, sofort quittieren */
  for (int n = 0; n < 5; n++) {
    rec_fill(r, n);
    int32_t s = tracklog_append(r, 15);
    assert(s >= 0);
    tracklog_mark_sent(s);
  }
  printf("-- 5 live zugestellt: offen=%u\n", tracklog_pending());
  assert(tracklog_pending() == 0);

  /* 2) Funkloch: 500 Fixes ohne Quittung */
  for (int n = 0; n < 500; n++) { rec_fill(r, n); assert(tracklog_append(r, 15) >= 0); }
  printf("-- Funkloch: offen=%u\n", tracklog_pending());
  assert(tracklog_pending() == 500);

  /* 3) Nachliefern in Buendeln zu zwoelf */
  int runden = 0, geliefert = 0;
  while (tracklog_pending() > 0) {
    uint16_t c = tracklog_batch(out, 12 * 15 + 1, &first);
    assert(c > 0 && out[0] == 15);
    /* Reihenfolge pruefen: erster Datensatz des ersten Buendels ist Fix 0 */
    if (runden == 0) assert(out[1] == 0 && out[2] == 1);
    tracklog_mark_batch(first, c);
    geliefert += c; runden++;
    assert(runden < 100);
  }
  printf("-- nachgeliefert: %d Datensaetze in %d Uplinks, offen=%u\n",
         geliefert, runden, tracklog_pending());
  assert(geliefert == 500);

  /* 4) Kaltstart: der Scan muss denselben Zustand finden */
  for (int n = 0; n < 40; n++) { rec_fill(r, n); assert(tracklog_append(r, 15) >= 0); }
  assert(tracklog_begin(true));
  printf("-- nach Kaltstart: offen=%u\n", tracklog_pending());
  assert(tracklog_pending() == 40);
  uint16_t c = tracklog_batch(out, 12 * 15 + 1, &first);
  assert(c == 12 && out[1] == 0);

  /* 5) Ring: ueber die Kapazitaet hinaus schreiben */
  uint32_t vorher = tracklog_pending();
  for (int n = 0; n < 10000; n++) { rec_fill(r, n & 0xff); tracklog_append(r, 15); }
  printf("-- Ring: offen=%u, ueberschrieben=%u\n", tracklog_pending(), tracklog_lost());
  assert(tracklog_lost() > 0);
  assert(tracklog_pending() <= 48 * 204);
  c = tracklog_batch(out, 12 * 15 + 1, &first);
  assert(c == 12);
  tracklog_mark_batch(first, c);
  printf("-- Ring, nach einem Buendel: offen=%u\n", tracklog_pending());

  /* 6) Fremdinhalt im spiffs-Bereich wird erkannt und formatiert */
  for (unsigned i = 0; i < sizeof(FLASH); i++) FLASH[i] = (uint8_t)(i * 7 + 3);
  assert(tracklog_begin(true));
  printf("-- Fremdinhalt: offen=%u\n", tracklog_pending());
  assert(tracklog_pending() == 0);
  rec_fill(r, 1); assert(tracklog_append(r, 15) >= 0);
  assert(tracklog_pending() == 1);

  printf("\nalle Faelle bestanden\n");
  return 0;
}
