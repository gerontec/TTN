/*
 * sx1302_syncword_preload.c -- per-demodulator LoRa sync word for the SX1302
 *
 * Interposes sx1302_lora_syncword() in Dragino's libsx1302hal.so so that each
 * of the four independent RX demodulator blocks can be given an arbitrary sync
 * word, instead of the stock 0x12 / 0x34 pair selected by "lorawan_public".
 *
 * Why interposition instead of replacing the library:
 * Dragino moved the SX1302 chip reset into libsx1302hal.so (it links against
 * libgpio.so; /etc/init.d/lora_gw calls no reset script for sx1302). Swapping
 * in an upstream-built HAL would drop that reset. Interposing replaces exactly
 * one function and leaves Dragino's board-specific code untouched.
 *
 * Registers are addressed by absolute SX1302 address through lgw_com_rmw(),
 * not by register-table ID, so this does not depend on Dragino's register
 * enumeration matching upstream's.
 *
 * ---------------------------------------------------------------------------
 * WHAT THE HARDWARE CAN AND CANNOT DO
 *
 * The SX1302 has exactly four RX sync word register pairs:
 *
 *   RX_TOP       SF5        0x588A/0x588B   all 8 multi-SF IF channels, SF5
 *   RX_TOP       SF6        0x588C/0x588D   all 8 multi-SF IF channels, SF6
 *   RX_TOP       SF7TO12    0x588E/0x588F   all 8 multi-SF IF channels, SF7-12
 *   LORA_SERVICE            0x5B2E/0x5B2F   chan_Lora_std only
 *
 * There is NO per-IF-channel register. The 8 multi-SF channels share one
 * demodulator block whose sync word is split by spreading factor only, so a
 * single one of those 8 channels cannot be given its own sync word. The LoRa
 * Service modem (chan_Lora_std) is the one channel that can, and is therefore
 * the channel to use for a private link alongside the 8 LoRaWAN channels.
 *
 * A sync word 0xHL is carried by the two preamble sync symbols. The SX1302
 * stores each symbol as symbol_value/4, i.e. peak_pos = nibble * 2. Each field
 * is 5 bits and lgw_com_rmw() masks to that width, so the full 0x00..0xFF sync
 * word range is reachable -- 0x12/0x34 is a software convention, not a limit.
 *
 * Build:  make
 * Deploy: see README.md
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <time.h>
#include <dlfcn.h>

/* Provided by the already-loaded libsx1302hal.so */
extern int lgw_com_rmw(uint8_t spi_mux_target, uint16_t address, uint8_t offs, uint8_t leng, uint8_t data);

/*
 * TX sync word.
 *
 * sx1302_send() rewrites the transmit sync word for EVERY packet, immediately
 * before keying the PA, derived from lorawan_public -- so a downlink always
 * goes out as 0x12 or 0x34 no matter what the RX side is set to. A peer on a
 * different sync word (an Ebyte repeater on 0x55, say) would never hear the
 * gateway.
 *
 * Interposing sx1302_send() itself is not an option: its signature carries
 * struct pointers, so it would tie us to Dragino's struct layout. Instead we
 * interpose lgw_com_rmw() -- the register write goes through it, because the
 * peak position fields are 5 bits at offset 0 and therefore a read-modify-write
 * -- and substitute the value only for the four TX FRAME_SYNCH addresses.
 * Address-based again, so no ABI coupling.
 */
#define REG_TX_A_PEAK1          0x526D      /* TX_TOP_A base 0x5200 + 109 */
#define REG_TX_A_PEAK2          0x526E
#define REG_TX_B_PEAK1          0x546D      /* TX_TOP_B base 0x5400 + 109 */
#define REG_TX_B_PEAK2          0x546E

/*
 * Telling the two kinds of downlink apart.
 *
 * A gateway that also serves LoRaWAN must not send join accepts and ADR on a
 * private sync word -- no end device would accept them. So the substitution is
 * made conditional on the transmit frequency: only downlinks on the raw
 * channel get the private sync word, everything else keeps the HAL's value.
 *
 * sx1302_send() writes the TX frequency at loragw_sx1302.c:2604-2608, before
 * the sync word at :2710, so the frequency is already known when we need to
 * decide. Those three registers are 8 bits at offset 0, which reg_w() sends
 * down the direct-write path -- hence we watch lgw_com_w(), not lgw_com_rmw().
 *
 *   freq_reg = freq_hz * 2^18 / 32e6   ->   122.07 Hz per LSB
 *
 * That resolution easily separates the raw channel on 868.125 MHz from
 * chan_multiSF_0 on 868.100 MHz, 25 kHz away, so a tight window is safe.
 */
#define REG_TX_A_FREQ_H         0x5225      /* TX_TOP_A base + 37 */
#define REG_TX_A_FREQ_M         0x5226
#define REG_TX_A_FREQ_L         0x5227
#define REG_TX_B_FREQ_H         0x5425      /* TX_TOP_B base + 37 */
#define REG_TX_B_FREQ_M         0x5426
#define REG_TX_B_FREQ_L         0x5427

#define FREQ_FENSTER_HZ         5000        /* +/- 5 kHz around tx_freq */

/*
 * TX LDRO. sx1302_send() derives it from the same SET_PPM_ON(bw, dr) rule as
 * the receive path, so a BW500 downlink always goes out with LDRO = 0 while
 * Ebyte peers transmit and expect 1. Measured: a gateway downlink reached the
 * node at -105 dBm but only decoded with the receiver forced to LDRO 0 --
 * header locks, payload fails, the same trap as on the RX side.
 *
 * Offset 4, length 2, so this write also goes through lgw_com_rmw().
 */
#define REG_TX_A_LDRO           0x5261      /* TX_TOP_A base 0x5200 + 97 */
#define REG_TX_B_LDRO           0x5461      /* TX_TOP_B base 0x5400 + 97 */
#define TX_LDRO_OFFS            4
#define TX_LDRO_LENG            2

static int (*real_com_rmw)(uint8_t, uint16_t, uint8_t, uint8_t, uint8_t) = NULL;
static int (*real_com_w)(uint8_t, uint16_t, uint8_t) = NULL;
static int sw_tx = -1;                      /* -1 = leave the HAL's value alone */
static long sw_tx_freq = -1;                /* -1 = apply to every downlink */
static int sw_tx_ldro = -1;                 /* -1 = leave the HAL's value alone */

/* letzte je Kette geschriebene Frequenz, Index 0 = TX_TOP_A, 1 = TX_TOP_B */
static uint32_t tx_freq_reg[2] = { 0, 0 };

static long freq_reg_to_hz(uint32_t reg) {
    return (long)(((uint64_t)reg * 32000000U) >> 18);
}

static int call_real_rmw(uint8_t mux, uint16_t addr, uint8_t offs, uint8_t leng, uint8_t data) {
    if (real_com_rmw == NULL) {
        real_com_rmw = dlsym(RTLD_NEXT, "lgw_com_rmw");
        if (real_com_rmw == NULL) {
            return -1;
        }
    }
    return real_com_rmw(mux, addr, offs, leng, data);
}

/*
 * Should this downlink carry the private sync word? Yes if no frequency filter
 * is configured, otherwise only when the chain is tuned to it.
 */
static int tx_gilt_fuer(int kette) {
    long hz;

    if (sw_tx_freq < 0) {
        return 1;                       /* kein Filter -> jeder Downlink */
    }
    if ((kette < 0) || (kette > 1)) {
        return 0;
    }
    hz = freq_reg_to_hz(tx_freq_reg[kette]);
    return ((hz >= sw_tx_freq - FREQ_FENSTER_HZ) &&
            (hz <= sw_tx_freq + FREQ_FENSTER_HZ)) ? 1 : 0;
}

/*
 * Interposed direct register write. Only used to watch the three TX frequency
 * bytes go by; everything is passed through untouched.
 */
int lgw_com_w(uint8_t spi_mux_target, uint16_t address, uint8_t data) {
    if (real_com_w == NULL) {
        real_com_w = dlsym(RTLD_NEXT, "lgw_com_w");
        if (real_com_w == NULL) {
            return -1;
        }
    }
    switch (address) {
        case REG_TX_A_FREQ_H: tx_freq_reg[0] = (tx_freq_reg[0] & 0x0000FFFF) | ((uint32_t)data << 16); break;
        case REG_TX_A_FREQ_M: tx_freq_reg[0] = (tx_freq_reg[0] & 0x00FF00FF) | ((uint32_t)data <<  8); break;
        case REG_TX_A_FREQ_L: tx_freq_reg[0] = (tx_freq_reg[0] & 0x00FFFF00) | ((uint32_t)data <<  0); break;
        case REG_TX_B_FREQ_H: tx_freq_reg[1] = (tx_freq_reg[1] & 0x0000FFFF) | ((uint32_t)data << 16); break;
        case REG_TX_B_FREQ_M: tx_freq_reg[1] = (tx_freq_reg[1] & 0x00FF00FF) | ((uint32_t)data <<  8); break;
        case REG_TX_B_FREQ_L: tx_freq_reg[1] = (tx_freq_reg[1] & 0x00FFFF00) | ((uint32_t)data <<  0); break;
        default: break;
    }
    return real_com_w(spi_mux_target, address, data);
}

#define SPI_MUX_TARGET_SX1302   0x00

#define REG_SF5_PEAK1           0x588A
#define REG_SF5_PEAK2           0x588B
#define REG_SF6_PEAK1           0x588C
#define REG_SF6_PEAK2           0x588D
#define REG_SF7TO12_PEAK1       0x588E
#define REG_SF7TO12_PEAK2       0x588F
#define REG_SERVICE_PEAK1       0x5B2E
#define REG_SERVICE_PEAK2       0x5B2F

#define PEAK_FIELD_OFFS         0
#define PEAK_FIELD_LENG         5

/*
 * LDRO (low data rate optimisation) for the LoRa Service modem.
 * The HAL derives it from a fixed rule, SET_PPM_ON(bw, dr), which is true only
 * for BW125 with SF11/SF12 and BW250 with SF12 -- never for BW500. Ebyte E22 /
 * E90 modules transmit BW500 with LDRO = 1 (measured, see gerontec/TTN
 * devices/pico_sx1262/EBYTE_E90.md). With the wrong LDRO the header still
 * locks and HeaderValid fires, but every payload arrives with a CRC error --
 * it looks "almost right", which makes it a nasty trap. Overriding it here is
 * safe because sx1302_lora_service_modem_configure() runs at loragw_hal.c:976,
 * before this hook at :993.
 */
#define REG_SERVICE_PPM_OFFSET  0x5B22
#define LDRO_FIELD_OFFS         4
#define LDRO_FIELD_LENG         2

#define SW_AUTO                 (-1)
#define CONF_PATH               "/etc/lora/syncword.conf"

/* Spreading factor codes as used by the HAL's DR_LORA_SFx */
#define SF5                     5
#define SF6                     6

#define PEAK1(sw)   (uint8_t)((((uint8_t)(sw) >> 4) & 0x0F) * 2)
#define PEAK2(sw)   (uint8_t)((((uint8_t)(sw) >> 0) & 0x0F) * 2)

struct syncword_set {
    int sf5;
    int sf6;
    int sf7to12;
    int service;
    int ldro;       /* LoRa Service modem LDRO: SW_AUTO, 0 or 1 */
    int tx;         /* transmit sync word, SW_AUTO = stock */
    int tx_ldro;    /* LDRO fuer Downlinks, SW_AUTO = HAL-Regel */
    long tx_freq;   /* nur Downlinks auf dieser Frequenz, -1 = alle */
};

static void parse_line(char * line, struct syncword_set * sw) {
    char key[32];
    char val[32];
    int * target;
    long parsed;
    char * end;

    if (sscanf(line, " %31[A-Za-z0-9_] = %31s", key, val) != 2) {
        return; /* comment, blank or malformed */
    }

    if      (strcmp(key, "sf5")     == 0) target = &sw->sf5;
    else if (strcmp(key, "sf6")     == 0) target = &sw->sf6;
    else if (strcmp(key, "sf7to12") == 0) target = &sw->sf7to12;
    else if (strcmp(key, "service") == 0) target = &sw->service;
    else if (strcmp(key, "ldro")    == 0) target = &sw->ldro;
    else if (strcmp(key, "tx")      == 0) target = &sw->tx;
    else if (strcmp(key, "tx_ldro") == 0) target = &sw->tx_ldro;
    else if (strcmp(key, "tx_freq") == 0) {
        if (strcmp(val, "auto") == 0) {
            sw->tx_freq = -1;
            return;
        }
        errno = 0;
        parsed = strtol(val, &end, 0);
        if ((errno != 0) || (end == val) || (*end != '\0') || (parsed < 0)) {
            printf("WARNING: [syncword] ignoring invalid value \"%s\" for key \"tx_freq\"\n", val);
            return;
        }
        sw->tx_freq = parsed;
        return;
    }
    else return;

    if (strcmp(val, "auto") == 0) {
        *target = SW_AUTO;
        return;
    }

    errno = 0;
    parsed = strtol(val, &end, 0); /* base 0 -> accepts 0x.. and decimal */
    if (((target == &sw->ldro) || (target == &sw->tx_ldro))
        && (parsed >= 0) && (parsed <= 1) &&
        (errno == 0) && (end != val) && (*end == '\0')) {
        *target = (int)parsed;
        return;
    }
    if ((errno != 0) || (end == val) || (*end != '\0') || (parsed < 0) || (parsed > 255)) {
        printf("WARNING: [syncword] ignoring invalid value \"%s\" for key \"%s\"\n", val, key);
        return;
    }
    *target = (int)parsed;
}

static void load_conf(struct syncword_set * sw) {
    FILE * f;
    char line[128];

    f = fopen(CONF_PATH, "r");
    if (f == NULL) {
        printf("INFO: [syncword] %s not found, keeping stock behaviour\n", CONF_PATH);
        return;
    }
    while (fgets(line, sizeof line, f) != NULL) {
        char * hash = strchr(line, '#');
        if (hash != NULL) {
            *hash = '\0';
        }
        parse_line(line, sw);
    }
    fclose(f);
}

static int write_pair(uint16_t reg1, uint16_t reg2, int sw) {
    int err = 0;
    err |= call_real_rmw(SPI_MUX_TARGET_SX1302, reg1, PEAK_FIELD_OFFS, PEAK_FIELD_LENG, PEAK1(sw));
    err |= call_real_rmw(SPI_MUX_TARGET_SX1302, reg2, PEAK_FIELD_OFFS, PEAK_FIELD_LENG, PEAK2(sw));
    return err;
}

/*
 * Measure what a sync word change actually costs on this hardware, to judge
 * whether time-multiplexing the multi-SF block is viable. Writes the SF7TO12
 * pair back to the value it already holds, so it is non-destructive.
 * Enabled with SYNCWORD_BENCH=<iterations> in the environment.
 */
static void bench_switch(int sw) {
    const char * env = getenv("SYNCWORD_BENCH");
    struct timespec t0, t1;
    long iterations, i;
    double total_us, per_switch_us;

    if (env == NULL) {
        return;
    }
    iterations = strtol(env, NULL, 0);
    if (iterations <= 0) {
        return;
    }

    /* one "switch" = retune the multi-SF SF7-12 pair, i.e. 2 register RMWs */
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (i = 0; i < iterations; i++) {
        write_pair(REG_SF7TO12_PEAK1, REG_SF7TO12_PEAK2, sw);
    }
    clock_gettime(CLOCK_MONOTONIC, &t1);

    total_us = (double)(t1.tv_sec - t0.tv_sec) * 1e6 + (double)(t1.tv_nsec - t0.tv_nsec) / 1e3;
    per_switch_us = total_us / (double)iterations;

    printf("INFO: [syncword] BENCH %ld switches of the multi-SF pair (2 RMW = 4 SPI xfers each)\n", iterations);
    printf("INFO: [syncword] BENCH %.1f us per switch, %.1f us round trip (there and back)\n",
           per_switch_us, per_switch_us * 2.0);
    fflush(stdout);
}

/*
 * Interposed register write. Everything passes through unchanged except the
 * four TX FRAME_SYNCH peak positions, which carry the transmit sync word.
 */
int lgw_com_rmw(uint8_t spi_mux_target, uint16_t address, uint8_t offs, uint8_t leng, uint8_t data) {
    if (sw_tx >= 0) {
        switch (address) {
            case REG_TX_A_PEAK1: if (tx_gilt_fuer(0)) data = PEAK1(sw_tx); break;
            case REG_TX_A_PEAK2: if (tx_gilt_fuer(0)) data = PEAK2(sw_tx); break;
            case REG_TX_B_PEAK1: if (tx_gilt_fuer(1)) data = PEAK1(sw_tx); break;
            case REG_TX_B_PEAK2: if (tx_gilt_fuer(1)) data = PEAK2(sw_tx); break;
            default: break;
        }
    }
    if (sw_tx_ldro >= 0) {
        if ((address == REG_TX_A_LDRO) && tx_gilt_fuer(0)) {
            data = (uint8_t)sw_tx_ldro;
        } else if ((address == REG_TX_B_LDRO) && tx_gilt_fuer(1)) {
            data = (uint8_t)sw_tx_ldro;
        }
    }
    return call_real_rmw(spi_mux_target, address, offs, leng, data);
}

/*
 * Interposed HAL entry point. Signature is identical to the original, so the
 * ABI of libsx1302hal.so is untouched -- no struct crosses this boundary.
 */
int sx1302_lora_syncword(bool public, uint8_t lora_service_sf) {
    struct syncword_set sw = { SW_AUTO, SW_AUTO, SW_AUTO, SW_AUTO, SW_AUTO, SW_AUTO, SW_AUTO, -1 };
    int err = 0;

    load_conf(&sw);

    /* Resolve "auto" to the stock values, so an absent or all-auto conf file
       reproduces upstream's register writes exactly. */
    if (sw.sf5     == SW_AUTO) sw.sf5     = 0x12; /* SF5/SF6 are always private upstream */
    if (sw.sf6     == SW_AUTO) sw.sf6     = 0x12;
    if (sw.sf7to12 == SW_AUTO) sw.sf7to12 = public ? 0x34 : 0x12;
    if (sw.service == SW_AUTO) {
        sw.service = ((public == false) || (lora_service_sf == SF5) || (lora_service_sf == SF6)) ? 0x12 : 0x34;
    }

    err |= write_pair(REG_SF5_PEAK1,     REG_SF5_PEAK2,     sw.sf5);
    err |= write_pair(REG_SF6_PEAK1,     REG_SF6_PEAK2,     sw.sf6);
    err |= write_pair(REG_SF7TO12_PEAK1, REG_SF7TO12_PEAK2, sw.sf7to12);
    err |= write_pair(REG_SERVICE_PEAK1, REG_SERVICE_PEAK2, sw.service);

    if (sw.ldro != SW_AUTO) {
        err |= call_real_rmw(SPI_MUX_TARGET_SX1302, REG_SERVICE_PPM_OFFSET,
                             LDRO_FIELD_OFFS, LDRO_FIELD_LENG, (uint8_t)sw.ldro);
        printf("INFO: [syncword] LoRa Service LDRO forced to %d (HAL rule overridden)\n", sw.ldro);
    }

    sw_tx = sw.tx;              /* aktiviert die Umschreibung in lgw_com_rmw() */
    sw_tx_freq = sw.tx_freq;
    sw_tx_ldro = sw.tx_ldro;
    if (sw_tx_ldro >= 0) {
        printf("INFO: [syncword] TX LDRO forced to %d%s\n", sw_tx_ldro,
               (sw_tx_freq >= 0) ? " (nur auf der gefilterten Frequenz)" : " fuer JEDEN Downlink");
    }
    if (sw_tx >= 0) {
        if (sw_tx_freq >= 0) {
            printf("INFO: [syncword] TX sync word 0x%02X, nur fuer Downlinks auf %ld Hz (+/- %d Hz)\n",
                   (uint8_t)sw_tx, sw_tx_freq, FREQ_FENSTER_HZ);
        } else {
            printf("INFO: [syncword] TX sync word 0x%02X fuer JEDEN Downlink -- auch LoRaWAN!\n",
                   (uint8_t)sw_tx);
        }
    }

    bench_switch(sw.sf7to12);

    printf("INFO: [syncword] multi-SF ch0-7: SF5=0x%02X SF6=0x%02X SF7-12=0x%02X | Lora_std (SF%u): 0x%02X\n",
           (uint8_t)sw.sf5, (uint8_t)sw.sf6, (uint8_t)sw.sf7to12, lora_service_sf, (uint8_t)sw.service);
    fflush(stdout);

    return (err == 0) ? 0 : -1;
}
