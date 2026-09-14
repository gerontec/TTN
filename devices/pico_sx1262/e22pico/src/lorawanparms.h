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
#define LW_INTERVAL_MS   (20UL * 60UL * 1000UL)   // uplink spacing (default)
// Changeable at runtime without a new build: AT+TDC=<ms> at the console, or
// the downlink LW_TDC_CMD HH LL (minutes) on LW_CONTROL_PORT over the air.
// Kept in whole minutes in the spare byte of Zustand (storage.h), so the
// struct length stays and no saved sector is invalidated; 0 = the default.
#define LW_TDC_CMD        0x04    // downlink command: uplink interval
#define LW_TDC_MAX_MIN    255
// How well the node hears the gateway can only be measured on a downlink.
// Every uplink after at least this many minutes carries a LinkCheckReq; the
// LinkCheckAns comes back as a downlink and brings RSSI/SNR at the node plus
// the margin at the gateway. Time-based so that a short AT+TDC does not
// multiply the downlinks: 150 min = at most 9.6 a day, below the TTN fair
// use of about 10.
#define LW_LINKCHECK_MIN  150
#define LW_DATARATE       3       // DR3 = SF9 BW125; ADR moves this later
#define LW_ADR            true
#define LW_CONFIRMED      false   // unconfirmed uplinks, saves downlink time

// Class C keeps the receiver open between uplinks, so a downlink no longer has
// to wait for the node to speak first -- that is what makes the node pollable
// over the air: send 0x03 on LW_CONTROL_PORT, get an uplink back within
// seconds instead of up to LW_INTERVAL_MS. It costs permanent receive current
// (a few mA on the SX1262), which is why the TrackerD stays class A on its
// battery while this node, sitting on a supply, can afford it.
// The ChirpStack device profile must have supports_class_c = True as well,
// otherwise the server keeps queueing downlinks until the next uplink.
#define LW_CLASS_C        true
#define LW_POLL_CMD       0x03    // downlink command: send the payload now

// Measured value that travels with every uplink. GP26 = ADC0 is free on the
// Waveshare Pico-LoRa: the radio occupies GP2, 3, 10, 11, 12, 15 and 20 only.
// Sent as millivolts against the 3.3 V reference, 12 bit resolution.
// For the supply voltage instead, use A3 (GP29 = VSYS/3 on the classic Pico)
// and multiply by three in the decoder -- one line here, one there.
#define LW_ADC_PIN        A0
#define LW_ADC_REF_MV     3300

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

// --- repeater (MODE_REPEAT) -------------------------------------------------
// The third operating mode: the node listens on one EU868 default channel for
// LoRaWAN uplinks and retransmits every frame it hears bit-for-bit (the whole
// PHYPayload, 1:1) on a second LoRaWAN frequency, LWRPT_DELAY_MS later.
//
// No session, no identity, no duty-cycle bookkeeping of the LoRaWAN stack is
// involved -- this is raw LoRa with the LoRaWAN sync word. The MIC of the
// original frame stays valid, so the network server accepts the copy as a
// normal uplink of that device; a double reception (original + repeat) is
// merged by the gateway's deduplication. That is what a repeater is for:
// range, not a second identity. A second LoRaWAN identity instead would need
// its own DevNonce/session in flash (Zustand layout change) and would be
// locked by the 1 % duty cycle after every forward -- deliberately not done.
//
// Receive and transmit frequency are far enough apart that the node cannot
// hear its own forward (one radio chip, one antenna) -- that is the whole
// loop protection, the same argument RELAIS.md makes for the Brauneck relay.
// Listening works on exactly one spreading factor at a time: LWRPT_SF is the
// operating rate of the devices to be repeated (DR3 here). OTAA join requests
// (DR0 = SF12) are not heard; for that the value would have to be 12.
// TX on 867.1: the DLOS8N hears that channel (radio_0), so a forward can be
// checked in the gateway DB. The band 869.4-869.65 would allow 10 % duty
// cycle and 500 mW, but the DLOS8N does not listen there.
#define LWRPT_RX_FREQ_MHZ  868.1f    // EU868 default channel g0
#define LWRPT_TX_FREQ_MHZ  867.1f    // EU868 channel c4
#define LWRPT_SF           9         // DR3 = SF9/BW125
#define LWRPT_BW_KHZ       125.0f
#define LWRPT_CR           5         // RadioLib encoding: 5 = 4/5
#define LWRPT_SYNCWORD     0x34      // LoRaWAN, as the stack sets it too
#define LWRPT_PREAMBLE     8
#define LWRPT_POWER_DBM    14        // 25 mW ERP, the limit of 867.0-868.6
#define LWRPT_DELAY_MS     2000      // the fixed pause before the forward
#define LWRPT_QUEUE        4         // forwards waiting at most

// --- repeater with an identity (MODE_REPEAT_ID) -----------------------------
// The fourth mode does everything MODE_REPEAT does and says afterwards which
// frame it carried. The identification lies NEXT TO the frame, never inside
// it, and that is not a matter of taste:
//
//   MIC = AES-CMAC(NwkSKey, B0 | MHDR | MACPayload)[0:4]
//
// The CMAC runs over the whole message, and the B0 block carries its length.
// A single byte added anywhere breaks it, and the repeater has neither
// NwkSKey nor AppSKey of the foreign device to recompute anything -- if it
// had them it would not be a repeater but a man in the middle. A network
// server answers a modified frame with "No device-session exists for
// dev_addr", which is exactly what a stale ABP session produces: the mistake
// would be indistinguishable from the failure of 28 Aug 2026.
//
// What can be read without any key is the header. DevAddr sits in bytes 1-4
// (little endian), FCnt in 6-7, the message type in the top three bits of
// byte 0. Together with RSSI and SNR that is enough to say afterwards which
// frame took which path -- the join happens in the database over
// DevAddr + FCnt + time.
//
// The report goes out as the repeater's OWN LoRaWAN uplink, with its own ABP
// session, on the same frequency and spreading factor as the forwards. It is
// built by hand (RadioLib's AES, see main.cpp) instead of through the LoRaWAN
// stack: the stack would open RX1/RX2 and keep the radio busy for seconds,
// and it would insist on its own duty-cycle bookkeeping. Built by hand the
// report costs exactly one transmission, the same as a forward.
//
// It is a separate mode and not a switch inside MODE_REPEAT so that the
// return ticket protects it: `C>MODE REPEAT_ID 30` comes back on its own if
// the reports turn out to cost more than they are worth.
#define LWRPT_LOG_TIEFE    16        // records kept in the ring buffer
#define LWRPT_LOG_JEDE     3         // report after n forwards, 0 = no report
#define LWRPT_ID_PORT      20        // FPort of the report

// The ABP session of the repeater itself. Like the AppKey it belongs in
// lorawan_secret.h and not into git; without it the node repeats but stays
// silent about it (checked at runtime, an all-zero key sends nothing).
//
// The uplink counter of this session lives in RAM only -- deliberately. A
// counter in flash would mean a fourth field in Zustand, and a changed struct
// invalidates every saved sector (storage.cpp checks the length): the node
// would lose mode, DevNonces and LoRaWAN session in one go, and the next OTAA
// join would be rejected as a replay. Instead the device carries
// `skip_fcnt_check` in ChirpStack, which is what that flag is for. The price
// is that this one device has no replay protection -- for a diagnostic in a
// private network that is the cheaper side of the trade.
// lorawan_secret.h is already pulled in above (for LW_APP_KEY); a second
// include would only repeat every definition. What is missing there falls
// back to zero here.
#ifndef LWRPT_ID_DEVADDR
#define LWRPT_ID_DEVADDR   0x00000000UL
#define LWRPT_ID_NWKSKEY   { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, \
                             0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 }
#define LWRPT_ID_APPSKEY   { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, \
                             0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 }
#endif

#endif // LORAWANPARMS_H
