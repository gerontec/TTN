#include "tracklog.h"
#include "esp_partition.h"

static const esp_partition_t *trk_part = NULL;
static uint32_t trk_slots_total = 0;

/* Ueber den Deep-Sleep hinweg: der Scan ueber 192 KB lohnt nur beim Kaltstart. */
RTC_DATA_ATTR static uint32_t trk_magic    = 0;
RTC_DATA_ATTR static uint32_t trk_head_w   = 0;   /* naechster freier Slot   */
RTC_DATA_ATTR static uint32_t trk_head_r   = 0;   /* aeltester offener Slot  */
RTC_DATA_ATTR static uint32_t trk_pending  = 0;
RTC_DATA_ATTR static uint32_t trk_lost     = 0;
RTC_DATA_ATTR static int32_t  trk_live     = -1;
RTC_DATA_ATTR static uint8_t  trk_on       = 1;

#define TRK_MAGIC 0x54524B31   /* "TRK1" */

static uint32_t slot_addr(uint32_t slot)
{
  return (slot / TRK_SLOTS_SECTOR) * TRK_SECTOR_SIZE
       + (slot % TRK_SLOTS_SECTOR) * TRK_SLOT_SIZE;
}

static uint8_t crc8(const uint8_t *p, uint8_t len)
{
  uint8_t crc = 0xFF;
  for (uint8_t i = 0; i < len; i++)
  {
    crc ^= p[i];
    for (uint8_t b = 0; b < 8; b++)
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x31) : (uint8_t)(crc << 1);
  }
  return crc;
}

static bool slot_read(uint32_t slot, uint8_t *buf)
{
  return esp_partition_read(trk_part, slot_addr(slot), buf, TRK_SLOT_SIZE) == ESP_OK;
}

static uint8_t slot_state(uint32_t slot)
{
  uint8_t b = TRK_FREE;
  esp_partition_read(trk_part, slot_addr(slot), &b, 1);
  return b;
}

/* Fremdinhalt (SPIFFS-Reste ab Werk) erkennen: dann einmal komplett loeschen. */
static bool looks_like_tracklog(void)
{
  uint8_t buf[TRK_SLOT_SIZE];
  for (uint32_t s = 0; s < trk_slots_total; s += 37)   /* Stichprobe */
  {
    if (!slot_read(s, buf))
      return false;
    if (buf[0] != TRK_FREE && buf[0] != TRK_PENDING && buf[0] != TRK_SENT)
      return false;
  }
  return true;
}

static void trk_format(void)
{
  Serial.println("tracklog: Puffer wird formatiert");
  esp_partition_erase_range(trk_part, 0, trk_part->size);
  trk_head_w  = 0;
  trk_head_r  = 0;
  trk_pending = 0;
}

/* Der Ring sieht immer so aus: [zugestellt...][offen...][frei...] - zyklisch.
   Gesucht ist der Anfang der belegten Strecke, daraus folgen beide Koepfe.

   Gelesen wird sektorweise: 48 Bloecke statt 20 000 Einzelzugriffe. Der Scan
   laeuft nur beim Kaltstart, aber der faellt auf einem Akkugeraet trotzdem
   auf. Die Zustaende landen als 2 Bit je Slot in trk_map (2,4 KB). */
static uint8_t trk_map[(48 * TRK_SLOTS_SECTOR + 3) / 4];

static inline void map_set(uint32_t slot, uint8_t v)
{
  uint8_t sh = (slot & 3) * 2;
  trk_map[slot >> 2] = (uint8_t)((trk_map[slot >> 2] & ~(3 << sh)) | ((v & 3) << sh));
}

static inline uint8_t map_get(uint32_t slot)
{
  return (trk_map[slot >> 2] >> ((slot & 3) * 2)) & 3;
}

#define M_FREE    0
#define M_PENDING 1
#define M_SENT    2

static void trk_scan(void)
{
  static uint8_t sec[TRK_SECTOR_SIZE];
  uint32_t sectors = trk_part->size / TRK_SECTOR_SIZE;
  bool any_used = false, any_free = false;

  memset(trk_map, 0, sizeof(trk_map));
  for (uint32_t sc = 0; sc < sectors; sc++)
  {
    if (esp_partition_read(trk_part, sc * TRK_SECTOR_SIZE, sec, TRK_SECTOR_SIZE) != ESP_OK)
      return;
    for (uint32_t i = 0; i < TRK_SLOTS_SECTOR; i++)
    {
      uint8_t st = sec[i * TRK_SLOT_SIZE];
      uint8_t m  = (st == TRK_PENDING) ? M_PENDING : (st == TRK_SENT ? M_SENT : M_FREE);
      map_set(sc * TRK_SLOTS_SECTOR + i, m);
      if (m == M_FREE)
        any_free = true;
      else
        any_used = true;
    }
  }

  if (!any_used)
  {
    trk_head_w = trk_head_r = trk_pending = 0;
    return;
  }

  uint32_t start = 0;
  if (any_free)
  {
    for (uint32_t s = 0; s < trk_slots_total; s++)
    {
      uint32_t prev = (s == 0) ? (trk_slots_total - 1) : (s - 1);
      if (map_get(s) != M_FREE && map_get(prev) == M_FREE)
      {
        start = s;
        break;
      }
    }
  }

  uint32_t s = start, used = 0, pending = 0;
  uint32_t first_pending = 0xFFFFFFFF;
  while (used < trk_slots_total && map_get(s) != M_FREE)
  {
    if (map_get(s) == M_PENDING)
    {
      if (first_pending == 0xFFFFFFFF)
        first_pending = s;
      pending++;
    }
    s = (s + 1) % trk_slots_total;
    used++;
  }

  trk_head_w  = s;
  trk_head_r  = (first_pending == 0xFFFFFFFF) ? s : first_pending;
  trk_pending = pending;
}

bool tracklog_begin(bool cold_boot)
{
  if (trk_part == NULL)
    trk_part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                                        ESP_PARTITION_SUBTYPE_DATA_SPIFFS, "spiffs");
  if (trk_part == NULL)
  {
    Serial.println("tracklog: keine spiffs-Partition - Puffer aus");
    return false;
  }
  trk_slots_total = (trk_part->size / TRK_SECTOR_SIZE) * TRK_SLOTS_SECTOR;

  if (cold_boot || trk_magic != TRK_MAGIC)
  {
    if (!looks_like_tracklog())
      trk_format();
    else
      trk_scan();
    trk_lost  = 0;
    trk_magic = TRK_MAGIC;
    Serial.printf("tracklog: %u Slots, offen %u, Schreibkopf %u\r\n",
                  trk_slots_total, trk_pending, trk_head_w);
  }
  return true;
}

int32_t tracklog_append(const uint8_t *rec, uint8_t len)
{
  if (trk_part == NULL || !trk_on || len == 0 || len > TRK_REC_MAX)
    return -1;

  /* Sektorgrenze: der Sektor muss vor dem ersten Slot leer sein. Was dort noch
     offen lag, ist damit weg - der aelteste Teil der Spur faellt hinten runter. */
  if (trk_head_w % TRK_SLOTS_SECTOR == 0)
  {
    uint32_t sector = (trk_head_w / TRK_SLOTS_SECTOR) * TRK_SECTOR_SIZE;
    uint32_t drop   = 0;
    for (uint32_t i = 0; i < TRK_SLOTS_SECTOR; i++)
      if (slot_state(trk_head_w + i) == TRK_PENDING)
        drop++;
    if (drop || slot_state(trk_head_w) != TRK_FREE)
    {
      esp_partition_erase_range(trk_part, sector, TRK_SECTOR_SIZE);
      if (drop)
      {
        trk_lost    += drop;
        trk_pending -= (trk_pending >= drop) ? drop : trk_pending;
        if (trk_head_r >= trk_head_w && trk_head_r < trk_head_w + TRK_SLOTS_SECTOR)
          trk_head_r = (trk_head_w + TRK_SLOTS_SECTOR) % trk_slots_total;
        Serial.printf("tracklog: Ring voll, %u Datensaetze ueberschrieben\r\n", drop);
      }
    }
  }

  uint8_t slot[TRK_SLOT_SIZE];
  memset(slot, 0, sizeof(slot));
  slot[0] = TRK_PENDING;
  slot[1] = len;
  memcpy(&slot[2], rec, len);
  slot[TRK_SLOT_SIZE - 1] = crc8(&slot[1], TRK_SLOT_SIZE - 2);

  if (esp_partition_write(trk_part, slot_addr(trk_head_w), slot, TRK_SLOT_SIZE) != ESP_OK)
    return -1;

  int32_t written = (int32_t)trk_head_w;
  if (trk_pending == 0)
    trk_head_r = trk_head_w;
  trk_pending++;
  trk_head_w = (trk_head_w + 1) % trk_slots_total;
  return written;
}

void     tracklog_enable(uint8_t on)     { trk_on = on ? 1 : 0; }
uint8_t  tracklog_enabled(void)          { return trk_on; }

void     tracklog_set_live(int32_t slot) { trk_live = slot; }
int32_t  tracklog_get_live(void)         { return trk_live; }

uint32_t tracklog_pending(void) { return trk_pending; }
uint32_t tracklog_lost(void)    { return trk_lost;    }

uint16_t tracklog_batch(uint8_t *out, uint16_t out_max, uint32_t *first_slot)
{
  if (trk_part == NULL || trk_pending == 0 || out_max < 2)
    return 0;

  uint8_t  slot[TRK_SLOT_SIZE];
  uint16_t count = 0, pos = 1;
  uint8_t  reclen = 0;
  uint32_t s = trk_head_r, seen = 0;

  while (seen < trk_slots_total && count < trk_pending)
  {
    if (!slot_read(s, slot))
      break;
    if (slot[0] == TRK_FREE)
      break;
    if (slot[0] == TRK_PENDING)
    {
      uint8_t len = slot[1];
      if (len == 0 || len > TRK_REC_MAX ||
          slot[TRK_SLOT_SIZE - 1] != crc8(&slot[1], TRK_SLOT_SIZE - 2))
      {
        /* kaputter Datensatz: abhaken, nicht senden */
        tracklog_mark_sent((int32_t)s);
      }
      else
      {
        if (count == 0)
        {
          reclen = len;
          *first_slot = s;
        }
        else if (len != reclen)
        {
          break;                 /* Formatwechsel: naechstes Buendel */
        }
        if (pos + reclen > out_max)
          break;
        memcpy(&out[pos], &slot[2], reclen);
        pos += reclen;
        count++;
      }
    }
    s = (s + 1) % trk_slots_total;
    seen++;
  }

  if (count == 0)
    return 0;
  out[0] = reclen;
  return count;
}

void tracklog_mark_sent(int32_t slot)
{
  if (trk_part == NULL || slot < 0)
    return;
  uint8_t buf[4];
  if (esp_partition_read(trk_part, slot_addr((uint32_t)slot), buf, 4) != ESP_OK)
    return;
  if (buf[0] != TRK_PENDING)
    return;
  buf[0] = TRK_SENT;                       /* nur Bits loeschen - kein Erase */
  esp_partition_write(trk_part, slot_addr((uint32_t)slot), buf, 4);
  if (trk_pending)
    trk_pending--;
  if ((uint32_t)slot == trk_head_r)
  {
    uint32_t s = ((uint32_t)slot + 1) % trk_slots_total, seen = 0;
    while (seen < trk_slots_total && slot_state(s) != TRK_PENDING)
    {
      s = (s + 1) % trk_slots_total;
      seen++;
    }
    trk_head_r = s;
  }
}

void tracklog_mark_batch(uint32_t first_slot, uint16_t count)
{
  uint32_t s = first_slot, done = 0, seen = 0;
  while (done < count && seen < trk_slots_total)
  {
    if (slot_state(s) == TRK_PENDING)
    {
      tracklog_mark_sent((int32_t)s);
      done++;
    }
    s = (s + 1) % trk_slots_total;
    seen++;
  }
}

void tracklog_clear(void)
{
  if (trk_part == NULL)
    return;
  trk_format();
  trk_lost = 0;
}

void tracklog_status(void)
{
  Serial.printf("tracklog: Slots %u, offen %u, ueberschrieben %u, Schreibkopf %u, Lesekopf %u\r\n",
                trk_slots_total, trk_pending, trk_lost, trk_head_w, trk_head_r);
}
