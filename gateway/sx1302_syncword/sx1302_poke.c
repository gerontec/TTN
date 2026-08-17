/*
 * sx1302_poke -- read/write single SX1302 registers over /dev/spidev1.0 while
 * the packet forwarder is running.
 *
 * Safe to use alongside fwd: the SX1302 has no page register (unlike the
 * SX1301), so a register access is fully described by its address, and each
 * access is a single ioctl(SPI_IOC_MESSAGE) which the kernel serialises
 * against the forwarder's own transfers. Nothing is left half-written.
 *
 * Its reason to exist: sweeping a value normally means restarting the
 * forwarder for every candidate. Poking the register live turns a 16-restart
 * hunt into one short measurement window.
 *
 * Frame format taken from libloragw/src/loragw_spi.c:
 *   write  [mux, 0x80 | (addr>>8)&0x7F, addr&0xFF, data]            4 bytes
 *   read   [mux,        (addr>>8)&0x7F, addr&0xFF, 0x00, 0x00]      5 bytes,
 *          result in the 5th received byte
 *
 * Usage:
 *   sx1302_poke <addr>                 read one register     (addr is hex)
 *   sx1302_poke <addr> <value>         write one register
 *   sx1302_poke syncword <sw>          set the LoRa Service sync word 0x00..0xFF
 *
 * Build: see Makefile target sx1302_poke
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>

#define SPI_DEV             "/dev/spidev1.0"
#define SPI_SPEED           2000000
#define MUX_SX1302          0x00
#define WRITE_ACCESS        0x80

/* LoRa Service modem (chan_Lora_std) sync word peak positions */
#define REG_SERVICE_PEAK1   0x5B2E
#define REG_SERVICE_PEAK2   0x5B2F

static int spi_fd = -1;

static int reg_read(uint16_t addr, uint8_t * out) {
    uint8_t tx[5], rx[5];
    struct spi_ioc_transfer k;

    tx[0] = MUX_SX1302;
    tx[1] = (addr >> 8) & 0x7F;     /* READ_ACCESS = 0x00 */
    tx[2] = (addr >> 0) & 0xFF;
    tx[3] = 0x00;
    tx[4] = 0x00;

    memset(&k, 0, sizeof k);
    k.tx_buf = (unsigned long)tx;
    k.rx_buf = (unsigned long)rx;
    k.len = 5;
    k.speed_hz = SPI_SPEED;
    k.bits_per_word = 8;

    if (ioctl(spi_fd, SPI_IOC_MESSAGE(1), &k) != 5) {
        return -1;
    }
    *out = rx[4];
    return 0;
}

static int reg_write(uint16_t addr, uint8_t data) {
    uint8_t tx[4];
    struct spi_ioc_transfer k;

    tx[0] = MUX_SX1302;
    tx[1] = WRITE_ACCESS | ((addr >> 8) & 0x7F);
    tx[2] = (addr >> 0) & 0xFF;
    tx[3] = data;

    memset(&k, 0, sizeof k);
    k.tx_buf = (unsigned long)tx;
    k.len = 4;
    k.speed_hz = SPI_SPEED;
    k.bits_per_word = 8;

    return (ioctl(spi_fd, SPI_IOC_MESSAGE(1), &k) == 4) ? 0 : -1;
}

int main(int argc, char ** argv) {
    uint8_t val;
    int rc = 0;

    if (argc < 2) {
        fprintf(stderr, "usage: %s <addr_hex> [value] | syncword <sw>\n", argv[0]);
        return 2;
    }

    spi_fd = open(SPI_DEV, O_RDWR);
    if (spi_fd < 0) {
        perror("open " SPI_DEV);
        return 1;
    }

    if (strcmp(argv[1], "syncword") == 0) {
        long sw;
        if (argc < 3) {
            fprintf(stderr, "syncword needs a value\n");
            close(spi_fd);
            return 2;
        }
        sw = strtol(argv[2], NULL, 0);
        if ((sw < 0) || (sw > 255)) {
            fprintf(stderr, "sync word out of range 0x00..0xFF\n");
            close(spi_fd);
            return 2;
        }
        /* peak position = nibble * 2, 5-bit field, rest of the byte unused */
        rc |= reg_write(REG_SERVICE_PEAK1, (uint8_t)(((sw >> 4) & 0x0F) * 2));
        rc |= reg_write(REG_SERVICE_PEAK2, (uint8_t)(((sw >> 0) & 0x0F) * 2));
        printf("service sync word = 0x%02X (peak1=%ld peak2=%ld)%s\n",
               (unsigned)sw, ((sw >> 4) & 0x0F) * 2, (sw & 0x0F) * 2,
               rc ? "  SPI ERROR" : "");
    } else {
        uint16_t addr = (uint16_t)strtol(argv[1], NULL, 16);
        if (argc >= 3) {
            uint8_t data = (uint8_t)strtol(argv[2], NULL, 0);
            rc = reg_write(addr, data);
            printf("0x%04X <- 0x%02X%s\n", addr, data, rc ? "  SPI ERROR" : "");
        } else {
            rc = reg_read(addr, &val);
            if (rc == 0) {
                printf("0x%04X = 0x%02X (%u)\n", addr, val, val);
            } else {
                printf("0x%04X  SPI ERROR\n", addr);
            }
        }
    }

    close(spi_fd);
    return rc ? 1 : 0;
}
