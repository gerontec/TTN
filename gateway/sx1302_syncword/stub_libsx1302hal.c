/*
 * Link-time stub only -- never deployed, never loaded.
 *
 * On MIPS the dynamic linker resolves GOT entries eagerly at load time, so an
 * LD_PRELOAD library carrying an undefined symbol fails with "symbol not
 * found" if the library providing it has not been loaded yet. Giving our shim
 * a DT_NEEDED entry on libsx1302hal.so makes the loader pull the real Dragino
 * HAL in first, and the symbol resolves.
 *
 * We only need something to link against to record that DT_NEEDED. At run time
 * the real /usr/lib/libsx1302hal.so provides the symbol; this stub is not
 * shipped to the gateway.
 */

#include <stdint.h>

int lgw_com_rmw(uint8_t spi_mux_target, uint16_t address, uint8_t offs, uint8_t leng, uint8_t data);

int lgw_com_rmw(uint8_t spi_mux_target, uint16_t address, uint8_t offs, uint8_t leng, uint8_t data) {
    (void)spi_mux_target; (void)address; (void)offs; (void)leng; (void)data;
    return 0;
}
