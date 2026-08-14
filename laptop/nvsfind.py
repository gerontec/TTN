#!/usr/bin/env python3
"""Sucht die LoRaWAN-Schluessel im Flash-Abzug des TrackerD.

Zwei Wege, weil unklar ist, wie Dragino die Schluessel ablegt: die
Partitionstabelle wird gelesen und das NVS regulaer geparst, und unabhaengig
davon wird roh nach DevEUI/JoinEUI gesucht — der AppKey liegt bei solchen
Firmwares fast immer direkt daneben.
"""
import struct
import sys

DUMP = sys.argv[1] if len(sys.argv) > 1 else "trackerd_flash.bin"
DEV_EUI = bytes.fromhex("a840414f1188076c")
JOIN_EUI = bytes.fromhex("a840410000000102")

flash = open(DUMP, "rb").read()
print(f"Abzug: {len(flash)} Byte\n")

# --- Partitionstabelle -------------------------------------------------------
TYPES = {0: "app", 1: "data"}
parts = []
print("== Partitionen ==")
for off in range(0x8000, 0x9000, 32):
    e = flash[off:off + 32]
    if e[:2] != b"\xaa\x50":
        break
    t, st, o, s = e[2], e[3], *struct.unpack("<II", e[4:12])
    label = e[12:28].rstrip(b"\x00").decode("ascii", "replace")
    parts.append((label, t, st, o, s))
    print(f"  {label:<12} typ={TYPES.get(t, t)}/{st:#04x}  @{o:#010x}  {s // 1024:>5} KiB")

# --- NVS ---------------------------------------------------------------------
def nvs(data, base):
    """ESP-IDF-NVS: 32-Byte-Eintraege in 4-KiB-Seiten, 32 Byte Kopf + Bitmap."""
    for page in range(0, len(data), 4096):
        p = data[page:page + 4096]
        if len(p) < 4096 or p[:4] == b"\xff\xff\xff\xff":
            continue
        i = 64                      # 32 Byte Seitenkopf + 32 Byte Zustandsbitmap
        while i + 32 <= 4096:
            e = p[i:i + 32]
            ns, typ, span, _chunk = e[0], e[1], e[2], e[3]
            key = e[8:24].rstrip(b"\x00")
            if ns == 0 or ns == 0xFF or not key or not key.isascii():
                i += 32
                continue
            span = max(1, min(span, 32))
            if typ == 0x21:                      # Zeichenkette
                ln = struct.unpack("<H", e[24:26])[0]
                val = p[i + 32:i + 32 + ln].rstrip(b"\x00")
                out = val.decode("utf-8", "replace")
            elif typ == 0x42:                    # Blob
                ln = struct.unpack("<H", e[24:26])[0]
                out = p[i + 32:i + 32 + ln].hex()
            elif typ in (0x01, 0x11):
                out = str(e[24])
            elif typ in (0x04, 0x14):
                out = str(struct.unpack("<I", e[24:28])[0])
            elif typ in (0x08, 0x18):
                out = str(struct.unpack("<Q", e[24:32])[0])
            else:
                out = e[24:32].hex()
            print(f"  ns={ns:<3} {key.decode('ascii', 'replace'):<16} typ={typ:#04x} {out[:120]}")
            i += 32 * span
    print()


for label, t, st, o, s in parts:
    if t == 1 and st == 2:          # data/nvs
        print(f"== NVS '{label}' @{o:#x} ==")
        nvs(flash[o:o + s], o)

# --- Rohsuche ----------------------------------------------------------------
print("== Rohsuche nach DevEUI/JoinEUI ==")
for name, pat in (("DevEUI", DEV_EUI), ("JoinEUI", JOIN_EUI),
                  ("DevEUI rev", DEV_EUI[::-1]), ("JoinEUI rev", JOIN_EUI[::-1]),
                  ("DevEUI ascii", DEV_EUI.hex().upper().encode())):
    start = 0
    treffer = 0
    while True:
        p = flash.find(pat, start)
        if p < 0:
            break
        treffer += 1
        # 48 Byte Umfeld — ein AppKey ist 16 Byte und steht meist unmittelbar dabei.
        umfeld = flash[max(0, p - 32):p + 64]
        print(f"  {name} @{p:#010x}")
        for z in range(0, len(umfeld), 16):
            print(f"    {max(0, p - 32) + z:#010x}  {umfeld[z:z + 16].hex()}")
        start = p + 1
        if treffer >= 4:
            break
    if not treffer:
        print(f"  {name}: nicht gefunden")
