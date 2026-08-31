/*
 * tracklog - Positionen ueberleben den Funkausfall.
 *
 * Die Werksfirmware wirft jeden Fix weg, der nicht sofort raus kann: das
 * Datalog von Dragino haengt komplett an AT+PNACKMD=1, also an bestaetigten
 * Uplinks, und fasst nur 4 KB im NVS (~240 Datensaetze, ein Datensatz pro
 * Uplink beim Nachliefern). Am 23.08.2026 waren dadurch 8 h 38 min Fahrt
 * spurlos weg.
 *
 * Dieses Modul legt jeden Fix zuerst in den ungenutzten spiffs-Bereich
 * (0x3D0000, 192 KB) und markiert ihn erst als erledigt, wenn die Zustellung
 * bewiesen ist. Kommt die Verbindung zurueck, gehen die offenen Datensaetze
 * gebuendelt raus - so viele, wie die aktuelle Datenrate traegt.
 *
 * Aufbau: ein Slot ist 20 Byte, 4-Byte-ausgerichtet, 204 Slots je 4-KB-Sektor,
 * 48 Sektoren = 9792 Slots (~6,8 Tage im Minutentakt).
 *
 *   [0]      Zustand: 0xFF frei, 0xA5 offen, 0x00 zugestellt
 *   [1]      Laenge des Datensatzes (15 bei sensor_type 13, 17 bei 22)
 *   [2..18]  Datensatz (lat4 lon4 jahr2 mon tag std min sek [+ bat2])
 *   [19]     CRC8 ueber [1..18]
 *
 * Der Zustand wandert nur in eine Richtung (0xFF -> 0xA5 -> 0x00), und das
 * sind reine Bit-Loeschungen - NOR-Flash kann das ohne Sektor-Erase. Deshalb
 * kostet "zugestellt" keinen Schreibzyklus des ganzen Sektors.
 */
#ifndef _tracklog_h_
#define _tracklog_h_

#include <Arduino.h>

#define TRK_SLOT_SIZE     20
#define TRK_REC_MAX       17
#define TRK_SECTOR_SIZE   4096
#define TRK_SLOTS_SECTOR  (TRK_SECTOR_SIZE / TRK_SLOT_SIZE)   /* 204 */

#define TRK_FREE          0xFF
#define TRK_PENDING       0xA5
#define TRK_SENT          0x00

/* Partition suchen und Kopf-Zeiger bestimmen. false = kein Puffer verfuegbar,
   dann verhaelt sich die Firmware wie das Original. */
bool     tracklog_begin(bool cold_boot);

/* Fix anhaengen. Rueckgabe: Slot-Nummer oder -1. */
int32_t  tracklog_append(const uint8_t *rec, uint8_t len);

/* Offene Datensaetze. */
uint32_t tracklog_pending(void);

/* Aelteste offene Datensaetze einsammeln. out bekommt [reclen][rec][rec]...,
   Rueckgabe ist die Anzahl der Datensaetze. */
uint16_t tracklog_batch(uint8_t *out, uint16_t out_max, uint32_t *first_slot);

/* Zustellung quittieren. */
void     tracklog_mark_sent(int32_t slot);
void     tracklog_mark_batch(uint32_t first_slot, uint16_t count);

/* Puffer leeren (AT+TRKCLR). */
void     tracklog_clear(void);

/* Zustand auf die Konsole (AT+TRK=?). */
void     tracklog_status(void);

/* Ein-/Ausschalten zur Laufzeit (AT+TRK=0|1). Der Schalter liegt im
   RTC-Speicher, ein Kaltstart schaltet den Puffer wieder ein. */
void     tracklog_enable(uint8_t on);
uint8_t  tracklog_enabled(void);

/* Wie viele Datensaetze der Ring seit dem letzten Start ueberschrieben hat. */
uint32_t tracklog_lost(void);

/* Slot des zuletzt live gesendeten Fixes - GPS.cpp merkt ihn an, der
   TX-Complete-Zweig quittiert ihn, wenn die Verbindung bewiesen ist. */
void     tracklog_set_live(int32_t slot);
int32_t  tracklog_get_live(void);

#endif
