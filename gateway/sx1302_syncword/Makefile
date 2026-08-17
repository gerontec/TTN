# Cross-build the SX1302 per-demodulator sync word shim for the Dragino
# DLOS8N (OpenWrt 18.06, ar71xx/generic, mips_24kc big-endian, musl).
#
#   make            build libsx1302syncword.so
#   make install    build + deploy to the gateway (GW=root@10.9.0.9)
#   make clean

SDK  ?= $(HOME)/openwrt-sdk-18.06.9-ar71xx-generic_gcc-7.3.0_musl.Linux-x86_64
TC   := $(SDK)/staging_dir/toolchain-mips_24kc_gcc-7.3.0_musl
CC   := $(TC)/bin/mips-openwrt-linux-musl-gcc
export STAGING_DIR := $(TC)

GW   ?= root@10.9.0.9
SSH  := ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa
SCP  := scp -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa

TARGET := libsx1302syncword.so
POKE   := sx1302_poke
SRC    := sx1302_syncword_preload.c

CFLAGS := -O2 -Wall -Wextra -std=c99 -D_POSIX_C_SOURCE=199309L -fPIC
# MIPS resolves GOT entries eagerly at load time, so the shim must carry a
# DT_NEEDED on libsx1302hal.so or lgw_com_rmw fails to relocate. We link
# against a local stub purely to record that entry; the real HAL provides the
# symbol at run time. The stub is never deployed.
LDFLAGS := -shared
STUB    := libsx1302hal.so

.PHONY: all clean install

all: $(TARGET) $(POKE)

$(STUB): stub_libsx1302hal.c
	$(CC) $(CFLAGS) -shared -o $@ $<

$(TARGET): $(SRC) $(STUB)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $< -L. -l:$(STUB)
	@echo "--- built:"; file $@
	@echo "--- DT_NEEDED:"; readelf -d $@ | grep NEEDED

install: $(TARGET) $(POKE)
	$(SCP) $(TARGET) $(GW):/usr/lib/
	$(SCP) syncword.conf $(GW):/etc/lora/syncword.conf
	@echo "--- deployed; restart with: $(SSH) $(GW) /etc/init.d/lora_gw restart"

$(POKE): sx1302_poke.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGET) $(STUB) $(POKE)
