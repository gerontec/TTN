#!/bin/sh
#
# setup_ebyte_rawchannel.sh -- richtet auf einem SX1302-Gateway den Rohkanal
# chan_Lora_std mit eigenem Syncword ein, ohne den LoRaWAN-Betrieb anzufassen.
#
# Läuft AUF dem Gateway (OpenWrt/ash). Voraussetzung: libsx1302syncword.so und
# sx1302_poke sind bereits nach /usr/lib bzw. /usr/bin kopiert (make install).
#
#   ./setup_ebyte_rawchannel.sh --apply     einrichten und prüfen
#   ./setup_ebyte_rawchannel.sh --status    Ist-Zustand zeigen
#   ./setup_ebyte_rawchannel.sh --revert    alles zurücknehmen
#
# Optionen vor der Aktion, Vorgaben passen zu einem Ebyte E22/E90 auf Werk:
#   --sync 0x55     Syncword des Rohkanals (Ebyte-Werkswert, ausgemessen)
#   --sf 11         Spreizfaktor   (Ebyte-Luftrate 2.4k = SF11)
#   --bw 500000     Bandbreite     (die Ebyte-Leiter ist durchgehend BW500)
#   --if -375000    Ablage zum Radio: Zielfrequenz minus radio1_freq
#   --ldro 1        LDRO erzwingen (bei BW500 zwingend, der HAL setzt es nie)
#
# Es werden drei Dinge angefasst, jeweils mit Sicherung .pre-ebyte:
#   1. /etc/lora/cfg-302/EU-global_conf.json   die VORLAGE, nicht global_conf.json
#   2. /etc/init.d/lora_gw                     Start über den Preload-Wrapper
#   3. /usr/bin/fwd_syncword                   der Wrapper selbst (neu angelegt)
# dazu neu: /etc/lora/syncword.conf

set -e

SYNC=0x55
SF=11
BW=500000
IFOFF=-375000
LDRO=1
AKTION=""

VORLAGE=/etc/lora/cfg-302/EU-global_conf.json
INIT=/etc/init.d/lora_gw
WRAPPER=/usr/bin/fwd_syncword
CONF=/etc/lora/syncword.conf
SHIM=/usr/lib/libsx1302syncword.so
SUFFIX=.pre-ebyte

while [ $# -gt 0 ]; do
    case "$1" in
        --sync)   SYNC="$2"; shift 2 ;;
        --sf)     SF="$2"; shift 2 ;;
        --bw)     BW="$2"; shift 2 ;;
        --if)     IFOFF="$2"; shift 2 ;;
        --ldro)   LDRO="$2"; shift 2 ;;
        --apply|--status|--revert) AKTION="$1"; shift ;;
        *) echo "unbekannte Option: $1" >&2; exit 2 ;;
    esac
done

[ -n "$AKTION" ] || { sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

meldung() { echo "==> $*"; }
fehler()  { echo "FEHLER: $*" >&2; exit 1; }

# ---------------------------------------------------------------- status ----
if [ "$AKTION" = "--status" ]; then
    meldung "Vorlage $VORLAGE"
    grep -o '"chan_Lora_std".\{0,120\}' "$VORLAGE" 2>/dev/null || echo "  nicht gefunden"
    meldung "erzeugte Datei /etc/lora/global_conf.json"
    grep -o '"chan_Lora_std".\{0,120\}' /etc/lora/global_conf.json 2>/dev/null || echo "  nicht gefunden"
    meldung "$CONF"
    [ -f "$CONF" ] && grep -vE '^\s*(#|$)' "$CONF" || echo "  fehlt"
    meldung "Shim im laufenden Prozess"
    P=$(ubus call service list '{"name":"lora_gw"}' 2>/dev/null | sed -n 's/.*"pid": \([0-9]*\).*/\1/p')
    if [ -n "$P" ] && [ -r "/proc/$P/maps" ]; then
        grep -o 'libsx1302syncword.so' "/proc/$P/maps" | head -1 || echo "  NICHT geladen"
        tr '\0' '\n' < "/proc/$P/environ" | grep -i preload || true
    else
        echo "  Forwarder läuft nicht"
    fi
    meldung "Register (nur sinnvoll bei laufendem Forwarder)"
    if [ -x /usr/bin/sx1302_poke ]; then
        echo "  0x5B2E peak1 : $(/usr/bin/sx1302_poke 0x5B2E)"
        echo "  0x5B2F peak2 : $(/usr/bin/sx1302_poke 0x5B2F)"
        echo "  0x5B22 LDRO  : $(/usr/bin/sx1302_poke 0x5B22)  (Bits 4-5)"
    else
        echo "  sx1302_poke fehlt"
    fi
    meldung "letzte Syncword-Meldung"
    logread | grep -oE '\[syncword\].*' | tail -2 || echo "  keine"
    exit 0
fi

# ---------------------------------------------------------------- revert ----
if [ "$AKTION" = "--revert" ]; then
    for f in "$VORLAGE" "$INIT"; do
        if [ -f "$f$SUFFIX" ]; then
            cp "$f$SUFFIX" "$f"; meldung "zurückgesetzt: $f"
        else
            meldung "keine Sicherung für $f, übersprungen"
        fi
    done
    [ -f "$CONF" ] && { rm -f "$CONF"; meldung "entfernt: $CONF"; }
    [ -f "$WRAPPER" ] && { rm -f "$WRAPPER"; meldung "entfernt: $WRAPPER"; }
    chmod +x "$INIT"
    "$INIT" restart >/dev/null 2>&1 || true
    meldung "Regeldienst neu gestartet. Ohne Shim, Stock-Verhalten."
    exit 0
fi

# ----------------------------------------------------------------- apply ----
[ -f "$SHIM" ]    || fehler "$SHIM fehlt -- erst 'make install' vom Arbeitsplatz aus"
[ -f "$VORLAGE" ] || fehler "$VORLAGE fehlt -- ist das ein sx1302-Gateway mit EU-Konfiguration?"
[ -f "$INIT" ]    || fehler "$INIT fehlt"

meldung "Rohkanal: Ablage $IFOFF Hz, SF$SF, BW $BW, Syncword $SYNC, LDRO $LDRO"

# 1. Vorlage. Wer /etc/lora/global_conf.json editiert, arbeitet umsonst:
#    init_board() ruft bei jedem Start generate-config.sh, und das kopiert
#    die Vorlage darüber.
[ -f "$VORLAGE$SUFFIX" ] || cp "$VORLAGE" "$VORLAGE$SUFFIX"
sed -i "s|\(\"chan_Lora_std\"[^}]*\"if\": \)-\{0,1\}[0-9]*|\1$IFOFF|" "$VORLAGE"
sed -i "s|\(\"chan_Lora_std\"[^}]*\"bandwidth\": \)[0-9]*|\1$BW|" "$VORLAGE"
sed -i "s|\(\"chan_Lora_std\"[^}]*\"spread_factor\": \)[0-9]*|\1$SF|" "$VORLAGE"
grep -q "\"bandwidth\": $BW" "$VORLAGE" || fehler "Vorlage nicht angepasst -- Format abweichend, bitte von Hand prüfen"
meldung "Vorlage angepasst (Sicherung: $VORLAGE$SUFFIX)"

# 2. syncword.conf
cat > "$CONF" <<KONF
# erzeugt von setup_ebyte_rawchannel.sh
# Die 8 MultiSF-Kanaele teilen sich einen Demodulator-Block -- auto laesst sie
# unveraendert auf dem LoRaWAN-Syncword.
sf5     = auto
sf6     = auto
sf7to12 = auto
# chan_Lora_std hat ein eigenes Registerpaar (0x5B2E/0x5B2F):
service = $SYNC
# Der HAL leitet LDRO aus SET_PPM_ON(bw,dr) ab, das bei BW500 nie greift.
ldro    = $LDRO
# Sendeseite: wirkt auf JEDEN Downlink, auch die von LoRaWAN. Nicht setzen,
# solange ueber dieses Gateway LoRaWAN-Downlinks gehen muessen.
tx      = auto
KONF
meldung "geschrieben: $CONF"

# 3. Wrapper. procd setzt fuer die Zeilenpufferung selbst
#    LD_PRELOAD=/lib/libsetlbf.so und wuerde ein per procd_set_param env
#    gesetztes LD_PRELOAD ueberschreiben -- deshalb haengen wir hier an.
cat > "$WRAPPER" <<'WRAP'
#!/bin/sh
SHIM=/usr/lib/libsx1302syncword.so
if [ -n "$LD_PRELOAD" ]; then
    LD_PRELOAD="$LD_PRELOAD:$SHIM"
else
    LD_PRELOAD="$SHIM"
fi
export LD_PRELOAD
exec /usr/bin/fwd -d sx1302 "$@"
WRAP
chmod +x "$WRAPPER"
meldung "angelegt: $WRAPPER"

# 4. Init-Skript auf den Wrapper zeigen lassen (nur im sx1302-Zweig)
[ -f "$INIT$SUFFIX" ] || cp "$INIT" "$INIT$SUFFIX"
if grep -q "fwd_syncword" "$INIT"; then
    meldung "Init-Skript zeigt bereits auf den Wrapper"
else
    # Das Chip-Argument steht im Wrapper, nicht hier: procd verschluckt bei
    # zwei aufeinanderfolgenden procd_set_param command das Argument, egal ob
    # per procd_append_param oder direkt mitgegeben -- gemessen, procd startete
    # dann nur "fwd_syncword". Im Wrapper ist es unserer Kontrolle unterworfen
    # und wirkt immer.
    sed -i "s|^\(\t*\)procd_append_param command -d sx1302|\1procd_set_param command $WRAPPER|" "$INIT"
    grep -q "fwd_syncword" "$INIT" || fehler "Init-Skript nicht angepasst, bitte von Hand prüfen"
    chmod +x "$INIT"
    meldung "Init-Skript angepasst (Sicherung: $INIT$SUFFIX)"
fi

# 5. Neu starten und nachsehen
meldung "starte Regeldienst neu"
"$INIT" restart >/dev/null 2>&1 || true
sleep 12

echo
meldung "Ergebnis"
grep -o '"chan_Lora_std".\{0,105\}' /etc/lora/global_conf.json || true
logread | grep -oE '\[syncword\].*' | tail -2 || echo "  keine Syncword-Meldung -- Shim nicht aktiv?"
if [ -x /usr/bin/sx1302_poke ]; then
    echo "  0x5B2E = $(/usr/bin/sx1302_poke 0x5B2E | sed 's/.*= //')  peak1"
    echo "  0x5B2F = $(/usr/bin/sx1302_poke 0x5B2F | sed 's/.*= //')  peak2"
fi
echo
meldung "fertig. Rückbau jederzeit mit --revert"
