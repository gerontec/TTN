// loraparms.h -- the only LoRa parameters of the Pico node.
//
// After every start (a power cut included) the firmware reads these values;
// there is no configuration from the outside. Changing something here means a
// rebuild and flashing a new firmware.uf2.
//
// All on-air values were measured on the air, not taken from manuals -- the
// evidence is in TTN/devices/pico_sx1262/e22spec.md.

#ifndef LORAPARMS_H
#define LORAPARMS_H

// --- wiring of the Waveshare Pico-LoRa-SX1262 ------------------------------
#define PIN_SCK    10
#define PIN_MOSI   11
#define PIN_MISO   12
#define PIN_CS     3
#define PIN_BUSY   2
#define PIN_RST    15
#define PIN_DIO1   20

// --- on-air profile (Ebyte factory settings) -------------------------------
#define FREQ_MHZ   868.125f   // channel 18: 850.125 + 18
#define BW_KHZ     500.0f     // the Ebyte data-rate ladder is BW500 throughout
#define LORA_SF    11
#define LORA_CR    5          // RadioLib encoding: 5 = 4/5
#define SYNCWORD   0x55       // register 0x0740 then reads 54 54
#define POWER_DBM  14         // 25 mW ERP, the limit for 868.0-868.6 MHz
#define PREAMBLE   8
#define TCXO_V     1.8f       // TCXO on DIO3; without voltage no oscillator
#define LDRO_ON    true       // measured: with LDRO 0 nothing but CRC errors

// --- Ebyte framing ---------------------------------------------------------
#define MAGIC0     0x2C
#define MAGIC1     0x12       // 0x12 = channel 18
#define XORKEY     0x12
// NETID 00 + broadcast FFFF: the standard, parameter beacon included.
#define ADDRESS         {0x00, 0xFF, 0xFF}
// The same broadcast address, but NETID BB (beyond the E90 relay). The PONG
// goes out with both NETIDs so that at least one of them gets through.
// Measured 19 Aug 2026: the broadcast does NOT override the NETID filter --
// the E22 (NETID 00) accepted the N00 copies exclusively.
#define ADDRESS_NETIDBB {0xBB, 0xFF, 0xFF}

// --- reply behaviour -------------------------------------------------------
// The PONG is delayed: an earlier measurement series saw 0 out of 8 answers
// within the first second after an E22 transmission (e22spec.md, section 4).
// The deafness is not certain -- on 19 Aug a relayed frame was received by the
// E22 only 0.1 s after its own transmission. The delay stays for now, it does
// no harm.
#define PONG_DELAY_MS  2500

// --- own station id --------------------------------------------------------
// Four hex digits, namely the last four of the device address (DevEUI in
// lorawanparms.h) -- exactly the way the TrackerD derives its 076C from
// a840414f1188076c and the gateway its E09C from the MAC. The id is therefore
// not defined here but computed in main.cpp from LW_DEV_EUI; it appears in
// every remote-control answer (A><id>>...).

// --- relay (Ebyte's name for this function) --------------------------------
// When on, the Pico forwards every received frame once, with an "R" in front
// of the payload. The "R" marks the forward: the gateway recognises it, and
// frames whose payload already starts with "R" are not forwarded again (loop
// protection). Switchable at runtime over USB: relay | relay on | relay off
#define RELAY_ENABLE  true

#endif // LORAPARMS_H
