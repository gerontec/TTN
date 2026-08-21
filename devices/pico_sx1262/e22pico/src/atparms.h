// atparms.h -- the node's AT interface.
//
// On top of its short plain commands the node speaks the AT set of the Dragino
// devices, so it can be integrated like an LA66 stick: a host sends
// "AT+SENDB=0,2,2,00ff" and gets "OK". The template is the AT+CFG dump of our
// own LA66 in TTN/devices/la66_p2p/la66_lorawan_v1.3_cfg.txt; Dragino's
// firmware for it is public (github.com/dragino/LA66, ASR6601 SDK).
//
// The deviations are deliberate and documented in the README:
//   * AT+APPKEY answers masked -- the key stays inside the device.
//   * The raw channel parameters (FRE, SF, BW, CR, POWER, SYNCWORD, PREAMBLE)
//     are read-only; they come from loraparms.h and apply unchanged after
//     every start. A write attempt answers AT_ERROR.
//   * AT+LORAWAN=0|1 switches the operating mode -- the same language the
//     TrackerD firmware uses for its two applications. The second parameter is
//     the number of minutes until an automatic return.
//
// Both interfaces are equal: the USB console and the real UART on GP0 (TX) /
// GP1 (RX). The UART is the actual point -- a host without a USB stack (an
// ESP, a PLC, a Pi with no free port) hangs on the node with two wires.

#ifndef ATPARMS_H
#define ATPARMS_H

// Answer to AT+VER / AT+VERSION. Shaped like the LA66's ("EU868 v1.3"): band,
// firmware level, then the device and what it can do.
#define AT_VERSION  "EU868 v2.0.0 pico-e22 LoRa+LoRaWAN"

#define AT_UART_AN    true    // also serve the UART on GP0/GP1
#define AT_UART_BAUD  9600    // as the LA66 stick ships from the factory

// Report receptions unsolicited (in the LA66 format AT+RECVB=<port>:<hex>).
// Turn off when the host only wants to see answers to its own questions.
#define AT_RECV_MELDEN  true

#endif // ATPARMS_H
