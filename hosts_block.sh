#!/bin/sh
# Traegt die drei Rechner des LoRa-Notfallpfads gegenseitig in /etc/hosts ein.
#
# Bewusst ueber ULAs: 192.168.5.x und 192.168.178.x sind zwei getrennte
# IPv4-Netze, ueber IPv6 aber dasselbe Segment. Und anders als die GUAs aus dem
# FritzBox-Praefix wechseln ULAs nie, wenn der Provider das Praefix dreht.
#
# Der Block ist zwischen Markierungen eingefasst und wird bei jedem Lauf
# ersetzt statt angehaengt — mehrfaches Ausfuehren aendert also nichts.
set -e

START="# >>> lora-notfallpfad >>>"
END="# <<< lora-notfallpfad <<<"
TMP=/tmp/hosts.neu.$$

# Vorhandenen Block herausschneiden, Rest behalten.
sed "/$START/,/$END/d" /etc/hosts > "$TMP"

cat >> "$TMP" <<EOF
$START
fd00::23        dell-3660 dell
fd00::106       dragino-27e318 dragino gateway
fd00::27        gh-hpi7 laptop
$END
EOF

cp /etc/hosts /etc/hosts.bak-lora
cat "$TMP" > /etc/hosts
rm -f "$TMP"
echo "--- /etc/hosts ---"
sed -n "/$START/,/$END/p" /etc/hosts
