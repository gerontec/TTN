// lorawanparms.h -- the LoRaWAN side of the Pico node.
//
// The node has two operating modes, but only ever one at a time -- both share
// the same SX1262:
//
//   MODE_LORA     raw Ebyte channel, parameters in loraparms.h
//                 868.125 MHz SF11 BW500 sync word 0x55, own framing
//   MODE_LORAWAN  LoRaWAN class A, EU868, parameters here
//                 867.1-868.5 MHz sync word 0x34, OTAA against ChirpStack
//
// The gateway hears both at the same time: the DLOS8N at 10.9.0.9 listens to
// its eight multi-SF channels unchanged on 0x34 (-> ChirpStack on the dell,
// 192.168.5.23:1700) and to the raw channel chan_Lora_std on 0x55 (->
// lora_raw.py, port 1702). Switching is therefore a matter for the node
// alone; nothing has to be touched at the gateway -- details in
// TTN/gateway/RAWKANAL.md.
//
// The stack is RadioLib's own LoRaWAN implementation, not Sandeep Mistry's
// pico-lorawan: its glue layer (src/lorawan.c,
// src/boards/rp2040/sx1276-board.c) talks to the SX1276 exclusively
// (SX1276Read(REG_LR_VERSION) != 0x12 -> abort) and is a pure pico-sdk/CMake
// project. For the SX1262 an entire board layer would have to be written, and
// it could not be brought into one Arduino binary together with the existing
// raw-channel operation anyway. The full reasoning is in README.md, section
// "Why not pico-lorawan".

#ifndef LORAWANPARMS_H
#define LORAWANPARMS_H

// --- mode after the very first start ---------------------------------------
// After that whatever is in flash applies (storage.h): the mode last chosen
// by the console command `mode lora|lorawan`, by AT+LORAWAN or over the air
// survives restart and power cut.
#define START_MODE  MODE_LORA

// --- network ---------------------------------------------------------------
#define LW_BAND     EU868
#define LW_SUBBAND  0            // EU868 has no sub-bands

// --- identity --------------------------------------------------------------
// JoinEUI/AppEUI: meaningless in a private network without a join server,
// ChirpStack does not check them. The DevEUI is freely chosen ("PICO" plus a
// serial number) -- the Pico has no vendor EUI.
#define LW_JOIN_EUI  0x0000000000000000ULL
#define LW_DEV_EUI   0x5049434F00000E22ULL
// The last four hex digits (0E22) double as the station id on the raw
// channel -- one address, two operating modes.

// The AppKey is NOT here but in src/lorawan_secret.h -- that file is kept out
// of git (template: lorawan_secret.h.template) and is not embedded into the
// source carried in flash either. Without it the firmware still builds, but it
// will not join: the placeholder below is all zeros.
#if defined(__has_include)
#  if __has_include("lorawan_secret.h")
#    include "lorawan_secret.h"
#  endif
#endif
#ifndef LW_APP_KEY
#define LW_APP_KEY { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, \
                     0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 }
#endif

// --- operation -------------------------------------------------------------
#define LW_PORT           1       // payload (the node's counters)
#define LW_CONTROL_PORT  10       // downlink commands, see README
#define LW_INTERVAL_MS   (15UL * 60UL * 1000UL)   // uplink spacing
#define LW_DATARATE       3       // DR3 = SF9 BW125; ADR moves this later
#define LW_ADR            true
#define LW_CONFIRMED      false   // unconfirmed uplinks, saves downlink time

// The first join attempt happens immediately, after that the pause grows up to
// LW_JOIN_PAUSE_MAX_MS. A join occupies roughly 1.5 s of air time at DR3; the
// 1 % duty cycle limit of 868.0-868.6 MHz enforces spacing anyway.
#define LW_JOIN_PAUSE_MS      (60UL * 1000UL)
#define LW_JOIN_PAUSE_MAX_MS  (30UL * 60UL * 1000UL)

// The session is not written to flash after every uplink but only every nth --
// a flash sector survives around 100,000 erase cycles. If the power fails in
// between, the counter falls back by at most n uplinks on the next start;
// ChirpStack accepts ascending gaps, a step backwards only costs those few
// uplinks.
#define LW_SESSION_EVERY  8

#endif // LORAWANPARMS_H
