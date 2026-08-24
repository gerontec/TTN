#pragma once
#include <cstdint>
#include <cstring>
#define ESP_OK 0
#define ESP_PARTITION_TYPE_DATA 1
#define ESP_PARTITION_SUBTYPE_DATA_SPIFFS 0x82
typedef struct { uint32_t size; } esp_partition_t;
extern uint8_t FLASH[];
extern esp_partition_t PART;
static inline const esp_partition_t *esp_partition_find_first(int,int,const char*){ return &PART; }
static inline int esp_partition_read(const esp_partition_t*, uint32_t off, void *dst, uint32_t n){
  memcpy(dst, FLASH+off, n); return ESP_OK; }
static inline int esp_partition_write(const esp_partition_t*, uint32_t off, const void *src, uint32_t n){
  const uint8_t *s=(const uint8_t*)src;
  for(uint32_t i=0;i<n;i++) FLASH[off+i] &= s[i];   /* NOR: nur Bits loeschen */
  return ESP_OK; }
static inline int esp_partition_erase_range(const esp_partition_t*, uint32_t off, uint32_t n){
  memset(FLASH+off, 0xFF, n); return ESP_OK; }
