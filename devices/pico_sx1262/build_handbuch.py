#!/usr/bin/env python3
"""Baut das Relais-Handbuch als PDF: HTML + eingebettetes SVG -> Chromium."""
import re
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
ZIEL = HIER

svg = (HIER / "netz.svg").read_text()
svg = re.sub(r'<\?xml[^>]*\?>|<!DOCTYPE[^>]*>', '', svg, flags=re.S)
svg = re.sub(r'width="\d+pt" height="\d+pt"', 'width="100%"', svg, count=1)

html = """<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>Relais Brauneck — Handbuch</title>
<style>
@page { size: A4; margin: 16mm 14mm; }
body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
       font-size: 10.5pt; line-height: 1.45; color: #222; }
h1 { font-size: 20pt; margin: 0 0 2mm 0; }
h2 { font-size: 13pt; margin: 7mm 0 2mm 0; padding-bottom: 1mm;
     border-bottom: 1.5px solid #c8922a; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 4mm 0 1.5mm 0; page-break-after: avoid; }
.unter { color: #666; font-size: 10pt; margin: 0 0 4mm 0; }
table { border-collapse: collapse; width: 100%; margin: 2mm 0 3mm 0;
        font-size: 9.5pt; page-break-inside: avoid; }
th { background: #fdf3e3; text-align: left; padding: 1.4mm 2mm;
     border-bottom: 1.5px solid #c8922a; }
td { padding: 1.2mm 2mm; border-bottom: 0.5px solid #ddd; vertical-align: top; }
code, kbd { font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 9pt;
      background: #f4f4f4; padding: 0.3mm 1mm; border-radius: 2px; }
pre { background: #f7f7f7; border-left: 3px solid #c8922a; padding: 2mm 3mm;
      font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 8.7pt;
      overflow-wrap: anywhere; white-space: pre-wrap; page-break-inside: avoid; }
.merk { background: #fff9e8; border-left: 3px solid #c8922a; padding: 2mm 3mm;
        margin: 3mm 0; page-break-inside: avoid; }
.warn { background: #fdeeee; border-left: 3px solid #c0392b; padding: 2mm 3mm;
        margin: 3mm 0; page-break-inside: avoid; }
.zeichnung { margin: 3mm 0 5mm 0; page-break-inside: avoid; }
.zeichnung svg { max-width: 100%; height: auto; }
.fuss { margin-top: 6mm; padding-top: 2mm; border-top: 0.5px solid #ccc;
        color: #777; font-size: 8.5pt; }
.neu { page-break-before: always; }
</style></head><body>

<h1>Relaisstelle Brauneck</h1>
<p class="unter">Krisennetz Lenggries — Aufbau, Betrieb und Befehle.
Stand 17.08.2026 · Repository <code>gerontec/TTN</code></p>

<div class="zeichnung">__SVG__</div>

<h2>1 Grundgedanke: ein gemeinsamer Kanal</h2>
<p>Alle Teilnehmer arbeiten auf <b>einer</b> Frequenz mit <b>einem</b>
Spreizfaktor. Das ist keine Sparmaßnahme, sondern zwingend: Ein einzelnes
Funkmodul kann immer nur auf einem Kanal lauschen. Nur so hört das Relais
jeden und erreicht jeden. Es ist dasselbe Flutungsverfahren, das Meshtastic und
Ebytes Broadcast-Modus benutzen.</p>

<table>
<tr><th>Parameter</th><th>Wert</th><th>Warum</th></tr>
<tr><td>Frequenz</td><td>868.125 MHz</td><td>Ebyte-Kanal 18 ab Werk (850.125 + 18); liegt im Band 868.0–868.6</td></tr>
<tr><td>Spreizfaktor</td><td>SF11</td><td>Ebyte-Luftrate 2.4k; die Etiketten sind nominal, gemessen ist SF11</td></tr>
<tr><td>Bandbreite</td><td><b>500 kHz</b></td><td>Die Ebyte-Leiter ist durchgehend BW500, nie BW125 — nachgemessen</td></tr>
<tr><td>LDRO</td><td>1</td><td>Ebyte sendet mit 1; die Rechenregel käme bei SF11/BW500 auf 0 und jede Nutzlast bekäme CRC-Fehler</td></tr>
<tr><td>Syncword</td><td><b>0x34</b> (öffentlich)</td><td>Historisch, weil der Rohkanal anfangs das Syncword der LoRaWAN-Kanäle mitbenutzen musste. Seit 17.08.2026 nicht mehr nötig — siehe Kapitel 8.</td></tr>
<tr><td>CRC</td><td>an</td><td>sonst verwirft der Paket-Forwarder</td></tr>
<tr><td>Leistung</td><td>bis 14 dBm ERP</td><td>25 mW ist das Limit in 868.0–868.6</td></tr>
<tr><td>Sendezeit</td><td>1 %</td><td>bei ~144 ms Luftzeit rund <b>14 s</b> Sperre je Paket — der eigentliche Engpass, siehe Kapitel 6</td></tr>
</table>

<div class="merk"><b>Streckenrechnung 10 km, Sichtverbindung.</b>
14 dBm + 2 dBi = 16 dBm EIRP, minus 111 dB Freiraumdämpfung, plus 2 dBi
Empfangsantenne ergibt −93 dBm. Gegen rund −128 dBm Empfindlichkeit bei
SF11/BW500 bleiben etwa <b>35 dB Reserve</b> — SF11 auf 500 kHz ist trotz der
breiteren Bandbreite noch etwa 4 dB empfindlicher als das frühere SF7/BW125. Den Sprung ins Nachbartal trägt der Bergstandort
(~1550 m gegen zwei Täler auf ~650 m), nicht die Sendeleistung.</div>

<h2>2 Was das Relais tut</h2>
<p>Es hört alles auf dem gemeinsamen Kanal und gibt jedes Paket <b>genau
einmal</b> weiter, versehen mit einem Sprungzähler. Damit erreicht ein Knoten,
dessen Direktsignal zu schwach wäre, das Tal trotzdem.</p>

<table>
<tr><th>Nutzlast beginnt mit</th><th>Bedeutung</th><th>Verhalten</th></tr>
<tr><td><code>C&gt;</code></td><td>Fernwirkbefehl</td><td>ausgeführt, Antwort gesendet, <b>nie</b> weitergegeben</td></tr>
<tr><td><code>A&gt;</code></td><td>Antwort einer Station</td><td>ignoriert</td></tr>
<tr><td><code>R&lt;n&gt;&gt;</code></td><td>bereits n-mal weitergegeben</td><td>weiter bis 3 Sprünge, danach verworfen</td></tr>
<tr><td>alles Übrige</td><td>frisches Paket</td><td>als <code>R1&gt;…</code> weitergegeben</td></tr>
</table>

<h3>Eigenecho</h3>
<p>Da alle denselben Kanal teilen, trägt allein die Marker-Logik:</p>
<ul>
<li>Während des Sendens ist der Empfänger taub — die eigene Aussendung hört die Station nie unmittelbar.</li>
<li>Jedes weitergegebene Paket bekommt <code>R&lt;sprung&gt;&gt;</code>. Kommt es über eine zweite Relaisstelle zurück, greift der Zähler.</li>
<li>Der Dublettenspeicher schlüsselt auf den Inhalt <b>ohne</b> Marker und sperrt denselben Text fünf Minuten.</li>
</ul>
<p>Mehrere Relaisstellen sind dadurch möglich: aus <code>R1&gt;</code> wird
<code>R2&gt;</code> und so fort, bis drei Sprünge erreicht sind.</p>

<h2>3 Fernwirken von 192.168.5.23</h2>
<p>Der Pico hat <b>kein WLAN</b> — es ist ein RP2040, kein Pico W; das Modul
<code>network</code> existiert nicht. Auf dem Berg gibt es weder SSH noch OTA.
Der einzige Rückkanal ist der Funk, auf dem das Relais ohnehin arbeitet. Für
ein Krisensystem ist das der richtige Weg: Er trägt genau dann, wenn alles
andere ausgefallen ist.</p>

<pre>python3 /home/gh/python/lora_cmd.py POWER 17
gesendet: C&gt;POWER 17
Antwort: POWER 17 dBm   (RSSI -101, SNR 8.8)</pre>

<table>
<tr><th>Befehl</th><th>Wirkung</th></tr>
<tr><td><code>POWER 2..22</code></td><td>Sendeleistung in dBm — <b>der wichtigste Befehl</b></td></tr>
<tr><td><code>STATUS</code></td><td>weitergegeben / unterdrückt / Laufzeit / Konfiguration</td></tr>
<tr><td><code>RELAY 0|1</code></td><td>Weitergabe aus- oder einschalten</td></tr>
<tr><td><code>TELEM 0|1</code></td><td>Quittungen aus- oder einschalten</td></tr>
<tr><td><code>SAVE</code></td><td>Konfiguration ausdrücklich sichern</td></tr>
<tr><td><code>REBOOT</code></td><td>Neustart des Boards</td></tr>
<tr><td><code>PING</code></td><td>lebt die Station?</td></tr>
</table>

<div class="warn"><b>Frequenz und Spreizfaktor sind bewusst nicht fernstellbar.</b>
In einem Einkanalnetz würde man sich damit den Ast absägen, auf dem man sitzt —
die Station wäre nach dem Wechsel unerreichbar.
<br><br><b>Ohne Authentisierung.</b> Wer in Funkreichweite ist, kann das Relais
umstellen. Bewusste Abwägung zugunsten der Einfachheit.</div>

<p><b>Weg des Befehls:</b> <code>lora-raw.service</code> hält UDP 1702 dauerhaft
und ist der einzige, der senden kann. Er hat deshalb einen Steuereingang auf
<code>127.0.0.1:1703</code>; was dort ankommt, wird beim nächsten
<code>PULL_DATA</code> des Gateways gefunkt. <code>lora_cmd.py</code> schickt den
Befehl dorthin und wartet über MQTT <code>lora/raw</code> auf die Antwort.</p>

<h2 class="neu">4 Betriebsart umschalten</h2>

<h3>TrackerD — LoRaWAN ↔ P2P</h3>
<p>Der TrackerD hat zwei Firmware-Slots: <b>app0</b> trägt die
Dragino-LoRaWAN-Firmware, <b>app1</b> die selbst gebaute P2P-Firmware.
Umgeschaltet wird ausschließlich über <code>otadata</code> — app0, app1 und vor
allem das NVS mit den LoRaWAN-Keys bleiben unangetastet. Der Wechsel ist daher
verlustfrei und beliebig wiederholbar.</p>

<table>
<tr><th>Richtung</th><th>Befehl</th><th>gemessen</th></tr>
<tr><td>LoRaWAN → P2P</td><td><code>switch_app.py p2p --port /dev/ttyACM1</code></td><td><b>1,35 s</b></td></tr>
<tr><td>P2P → LoRaWAN</td><td><code>AT+LORAWAN</code> — am Gerät, ohne PC-Werkzeug</td><td><b>2,24 s</b> inkl. Neustart</td></tr>
<tr><td>P2P → LoRaWAN</td><td><code>switch_app.py lorawan --port /dev/ttyACM1</code></td><td>gleichwertig</td></tr>
<tr><td>Zustand abfragen</td><td><code>switch_app.py status --port /dev/ttyACM1</code></td><td>liest otadata</td></tr>
<tr><td>P2P neu bauen</td><td><code>pio run</code>, dann <code>switch_app.py flash</code></td><td>schreibt nur app1</td></tr>
</table>

<div class="warn"><b>Niemals <code>pio run -t upload</code>.</b> Das würde
Partitionstabelle und app0 überschreiben und die LoRaWAN-Firmware samt Keys
zerstören. Geflasht wird gezielt nach <code>0x1F0000</code> durch
<code>switch_app.py</code>.</div>

<h3>LA66 — LoRaWAN ↔ P2P</h3>
<pre>python3 la66_mode.py status     # Modus am Boot-Banner erkennen
python3 la66_mode.py p2p        # 37640 B, 5,0 s
python3 la66_mode.py lorawan    # 69032 B, 9,1 s</pre>
<p>Beim LA66 wird wirklich geflasht, nicht umgeschaltet: Beide Dragino-Images
sind fest auf <code>0x0800D000</code> gelinkt, ein zweiter Slot ist unmöglich.
Ein Flash setzt die Funkparameter auf Werk zurück — dafür
<code>--apply-rf</code>. Die DevEUI überlebt.</p>

<div class="merk"><b>Im LoRaWAN-Modus ist ein Gerät nicht Teil dieses Netzes.</b>
Nachgemessen: Der LA66 sendet mit <code>AT+DR=0</code> auf SF12 und springt über
alle acht EU868-Kanäle (beobachtet: 867.3 und 868.3 MHz). Der Pico auf
868.125 hörte in 95 s <b>null</b> Pakete (damals auf SF7; mit dem heutigen
SF11/BW500 gilt es unverändert). Spreizfaktoren sind quasi-orthogonal — ein
Empfänger mit festem SF kann einen anderen nicht demodulieren.
<br><br>Daraus folgt grundsätzlich: <b>Ein Knoten mit einem Funkmodul kann kein
LoRaWAN-Relais sein.</b> LoRaWAN wechselt pro Sendung den Kanal und passt per
ADR den Spreizfaktor an; ein Empfänger mit fester Frequenz und festem SF kann
dem nicht folgen. Genau dafür hat das Gateway acht parallele Demodulatoren.
Hinzu kommt: Der Marker <code>R1&gt;</code> würde die MIC-Prüfung eines
LoRaWAN-Rahmens zerstören.</div>

<h2>5 Stromversorgung: reiner Solarbetrieb</h2>
<p>Der Victron-Laderegler schaltet den Verbraucher morgens schlagartig zu und
abends ab. Eine Pufferbatterie gibt es nicht. Das prägt den Betrieb stärker als
jede Funkeinstellung.</p>
<ul>
<li><b>Jeder Morgen ist ein Kaltstart, und niemand ist oben.</b>
<code>main.py</code> startet das Relais, wiederholt bei Fehlern und löst
notfalls <code>machine.reset()</code> aus, statt in den REPL zu fallen.</li>
<li><b>Konfiguration sichert sich sofort</b>, nicht erst auf <code>SAVE</code> —
eine per Funk gesetzte Sendeleistung wäre sonst am nächsten Morgen weg.</li>
<li><b>Beschädigte <code>relais.json</code> wird abgefangen</b>; die Station
kommt dann mit Vorgabewerten hoch, aber sie kommt hoch.</li>
<li><b>Nachts ist die Kette unterbrochen.</b> Eigenschaft des Aufbaus, keine
Störung — wer nachts Reichweite braucht, braucht einen Akku.</li>
</ul>

<h3>Systemtakt 48 MHz</h3>
<p>125 MHz sind sinnlos: Modulation, Timing und Preamble macht der SX1262
selbst, der Prozessor wartet nur. Weniger Takt heißt weniger Strom, und bei
einer Versorgung ohne Puffer weniger Spannungseinbruch unter Last.</p>
<table>
<tr><th>Takt</th><th>Ergebnis der Abtastung</th></tr>
<tr><td>125 / 96 / 64 / 48 / 32 / 24 MHz</td><td>sauber — <code>DevErr 0x0000</code>, Syncword <code>3444</code>, TX ok</td></tr>
<tr><td>18 MHz</td><td><b>SPI liefert Müll</b> — Syncword liest <code>a2a2</code>, TX schlägt fehl</td></tr>
<tr><td>12 MHz</td><td><code>machine.freq()</code> lehnt ab</td></tr>
</table>
<p>Gewählt sind <b>48 MHz</b>: reichlich Abstand zur Ausfallgrenze bei gut
halbiertem Prozessorstrom. Der Takt wird <i>vor</i> dem Aufsetzen des Funkchips
gestellt, weil <code>clk_peri</code> am Systemtakt hängt.</p>

<h2>6 Nachgewiesen über die Luft</h2>
<p>Alle drei Stationen in einem Durchlauf, nach dem Kaltstart der neuen
Firmware und <b>ohne</b> manuelles Nachsetzen des Syncwords:</p>
<pre>TrackerD sendet   "V13-KALTSTART-1"
Pico             weiter: Sprung 1  RSSI -17  SNR 12.0  20 dBm, 51 ms
Gateway hört     RSSI -83  "V13-KALTSTART-1"        &lt;- direkt
Gateway hört     RSSI -84  "R1&gt;V13-KALTSTART-1"     &lt;- über das Relais
Pico-Bilanz      2 gehört, 2 weitergegeben, 0 unterdrückt</pre>
<p>In einem früheren Lauf war der Gewinn deutlicher messbar: Original −92 dBm,
Kopie vom Relais −73 dBm — <b>19 dB stärker</b>. Genau dafür steht die Station
auf dem Berg. Der TrackerD empfing dabei sein eigenes Paket als
<code>R1&gt;…</code> zurück; das Relais gab es <b>nicht</b> erneut weiter.</p>

<h3>Ebyte-Broadcasts, und was sie kosten</h3>
<p>Ein Ebyte-Rahmen wird <b>unverändert</b> weitergereicht — kein
<code>R1&gt;</code> davor. Er trägt einen eigenen 8-Byte-Kopf, und ein
Empfänger liest die ersten acht Byte als eben diesen; ein vorangestelltes
„R" macht den Rahmen unlesbar. Gegen Schleifen trägt hier allein der
Dublettenspeicher, einen Sprungzähler gibt es in diesem Format nicht.</p>
<p>Am Gateway ist beides zu sehen, unterscheidbar am Quarzversatz:</p>
<pre>foff -27673  RSSI -76   Original vom E22
foff   -144  RSSI -88   Kopie vom Relais   (byteweise identisch)</pre>
<div class="warn"><b>Das Sendezeitbudget ist der Engpass, nicht die
Empfindlichkeit.</b> Bei SF11/BW500 dauert ein 16-Byte-Rahmen 144 ms; die
1-%-Regel sperrt danach rund 14 s. Vier Broadcasts im Abstand von 3,5 s:
<pre>weiter: Ebyte, unveraendert  RSSI -23 SNR 8.3  144 ms
  verworfen: Sendezeitbudget, noch 11.0 s gesperrt
  verworfen: Sendezeitbudget, noch  7.5 s gesperrt
  verworfen: Sendezeitbudget, noch  4.0 s gesperrt
Bilanz: 4 gehoert, 1 weitergegeben, 3 unterdrueckt</pre>
Drei von vier fielen nicht am Funk aus, sondern an der Rechtslage. Mit dem
früheren SF7/BW125 waren es 72 ms und rund 7 s — der Umstieg auf das
Ebyte-Profil hat das verdoppelt. Wer auf Durchsatz auslegt, muss hier ansetzen:
kürzere Nutzlasten, seltener senden, oder ein zweites Modul für das Band
869.4–869.65 MHz mit 10 % Sendezeit.</div>

<h2>7 Dateien</h2>
<table>
<tr><th>Ort</th><th>Datei</th><th>Zweck</th></tr>
<tr><td rowspan="4">Pico</td><td><code>main.py</code></td><td>Selbststart nach jedem Sonnenaufgang</td></tr>
<tr><td><code>repeater.py</code></td><td>Flutung, Sprungzähler, Dubletten, Sendezeitbudget</td></tr>
<tr><td><code>fernwirk.py</code></td><td>Befehle, Konfiguration in <code>/relais.json</code></td></tr>
<tr><td><code>lora_p2p.py</code></td><td>SX1262-Treiber</td></tr>
<tr><td rowspan="2">dell 192.168.5.23</td><td><code>lora_raw.py</code></td><td>Roh-Abgriff UDP 1702, Steuereingang 1703, MQTT</td></tr>
<tr><td><code>lora_cmd.py</code></td><td>Fernwirkbefehle absetzen</td></tr>
<tr><td rowspan="2">TrackerD</td><td><code>p2p/src/main.cpp</code></td><td>P2P-Firmware v1.3, Syncword 0x34 ab Werk</td></tr>
<tr><td><code>switch_app.py</code></td><td>otadata-Umschaltung, Flashen nach app1</td></tr>
</table>

<h2 class="neu">8 Anleitung: Ebyte-Rohkanal am eigenen Gateway</h2>
<p>Diese Anleitung richtet sich an andere Besitzer eines Gateways mit
<b>SX1302</b> (Dragino DLOS8N, LPS8v2, RAK7268 und Verwandte), die ein
Ebyte-Modul — E22, E90-DTU — neben dem laufenden LoRaWAN-Betrieb empfangen
wollen. Alle Werte stammen aus eigenen Messungen, nicht aus Datenblättern.</p>

<div class="merk"><b>Der Kern in einem Satz.</b> Der SX1302 hat <b>vier</b>
RX-Syncword-Registerpaare, nicht eines: drei für den gemeinsamen
MultiSF-Block (getrennt nach SF5, SF6 und SF7–12, gültig für alle acht
LoRaWAN-Kanäle) und <b>ein eigenes</b> für den LoRa-Service-Modem hinter
<code>chan_Lora_std</code>. Der Rohkanal kann deshalb ein beliebiges Syncword
tragen, <i>während</i> die acht LoRaWAN-Kanäle unverändert auf 0x34 bleiben.
Nur schreibt der Semtech-HAL dort stur 0x12 oder 0x34, abgeleitet aus
<code>lorawan_public</code>.</div>

<h3>8.1 Was nicht geht</h3>
<p>Einer der acht MultiSF-Kanäle kann <b>kein</b> eigenes Syncword bekommen.
Die acht teilen sich einen Demodulator-Block, dessen Syncword nur nach
Spreizfaktor aufgeteilt ist; ein Register pro IF-Kanal existiert im Chip nicht.
Auch Zeitmultiplex hilft nicht: Umschalten kostet zwar nur 590 µs hin und
zurück, aber es gibt keinen Auslöser — die Paketerkennung <i>ist</i> der
Syncword-Vergleich, und wenn ein Paket auffällt, ist es längst verworfen.</p>

<h3>8.2 Ebyte-Modul auslesen</h3>
<p>Das Modul muss im Konfigurationsmodus stehen (M0 = 1, M1 = 1; bei
USB-Adaptern oft über DTR/RTS). Dann liefert <code>C1 00 09</code> die neun
Konfigurationsbytes:</p>
<pre>C1 00 09 | FF FF 00 62 00 12 80 00 00
           ADDH ADDL NETID REG0 REG1 REG2 REG3 CRYPT_H CRYPT_L</pre>
<table>
<tr><th>Feld</th><th>Beispiel</th><th>Bedeutung</th></tr>
<tr><td>REG2</td><td><code>0x12</code> = 18</td><td>Kanal → <b>Frequenz = 850.125 MHz + Kanal × 1 MHz</b> = 868.125 MHz (900-MHz-Reihe)</td></tr>
<tr><td>REG0 Bits 2–0</td><td><code>2</code></td><td>Luftrate, hier 2.4 k</td></tr>
<tr><td>REG0 Bits 7–5</td><td><code>3</code></td><td>UART-Baudrate, hier 9600</td></tr>
<tr><td>REG3 Bit 6</td><td><code>0</code></td><td>0 = transparent, 1 = Festpunkt mit Adresskopf</td></tr>
</table>

<div class="warn"><b>Die Luftraten-Etiketten sind nominal — nicht rechnen,
messen.</b> Die im Netz kursierende Tabelle übersetzt sie nach BW 125 kHz. Das
ist falsch. Gemessen ist die Ebyte-Leiter durchgehend <b>BW 500 kHz</b>:
Index 2 („2.4k") ist <b>SF11/BW500</b>, Index 5 („19.2k") ist SF7/BW500. Das
Handbuch bestätigt es beiläufig mit „air data rate 2.4kbps@SF11" — 2,4 kbps bei
SF11 gehen rechnerisch nur mit BW 500 auf, bei BW 125 wären es 537 bps.</div>

<h3>8.3 Rohkanal am Gateway einstellen</h3>
<p><code>chan_Lora_std</code> ist der neunte, eigenständige Kanal. Er wird frei
in Frequenz, Spreizfaktor und Bandbreite gesetzt:</p>
<pre>"chan_Lora_std": {"enable": true, "radio": 1, "if": -375000,
                  "bandwidth": 500000, "spread_factor": 11, ...}</pre>
<p>Die Frequenz ergibt sich als <code>radio[n].freq + if</code>; für 868.125 MHz
bei <code>radio1_freq = 868.5 MHz</code> also <code>if = −375000</code>.</p>

<div class="warn"><b>Falle: die Datei, die man editiert, ist die falsche.</b>
<code>init_board()</code> in <code>/etc/init.d/lora_gw</code> ruft bei
<i>jedem</i> Start <code>/usr/bin/generate-config.sh</code>, und das <b>kopiert</b>
<code>/etc/lora/cfg-302/EU-global_conf.json</code> über
<code>/etc/lora/global_conf.json</code>. Änderungen an der zweiten Datei sind
nach dem nächsten Neustart spurlos weg. Zu ändern ist die <b>Vorlage</b>.</div>

<h3>8.4 Syncword freischalten</h3>
<p>Das Werkzeug liegt im Repository unter
<code>gateway/sx1302_syncword/</code>. Es ersetzt per <code>LD_PRELOAD</code>
genau <i>eine</i> HAL-Funktion, <code>sx1302_lora_syncword()</code>, deren
Signatur keine Structs enthält und daher ABI-neutral ist. Die HAL selbst wird
nicht ausgetauscht — bei Dragino steckt der Chip-Reset in
<code>libsx1302hal.so</code>, ein Upstream-Build würde ihn verlieren.</p>
<pre># Cross-Build, OpenWrt-18.06-SDK, mips_24kc, musl
make SDK=/pfad/zu/openwrt-sdk-18.06.9-ar71xx-generic_gcc-7.3.0_musl.Linux-x86_64
make install GW=root@&lt;gateway&gt;</pre>
<p><code>/etc/lora/syncword.conf</code>:</p>
<pre>sf5     = auto      # auto = unverändertes Verhalten aus lorawan_public
sf6     = auto
sf7to12 = auto      # 0x34 -> LoRaWAN bleibt unberührt
service = 0x55      # chan_Lora_std allein: Ebyte-Werkswert
ldro    = 1         # bei BW500 zwingend, siehe unten</pre>
<p>Aktiviert wird der Shim über den Wrapper <code>/usr/bin/fwd_syncword</code>,
<b>nicht</b> über <code>procd_set_param env</code>: procd setzt für die
Zeilenpufferung selbst <code>LD_PRELOAD=/lib/libsetlbf.so</code> und würde einen
so gesetzten Wert überschreiben. Der Wrapper hängt den Shim mit <code>:</code>
getrennt <i>nach</i> procd an.</p>

<div class="warn"><b>LDRO muss von Hand auf 1.</b> Der HAL leitet es aus
<code>SET_PPM_ON(bw, dr)</code> ab, das nur bei BW125 mit SF11/SF12 und BW250
mit SF12 wahr wird — bei <b>BW500 also nie</b>. Ebyte sendet aber mit LDRO 1.
Bei falschem LDRO rastet der Header sauber ein, und <i>jede</i> Nutzlast kommt
mit CRC-Fehler an. Das sieht aus wie „fast richtig" und ist die zeitraubendste
Falle der ganzen Strecke.</div>

<h3>8.5 Das Ebyte-Syncword ist 0x55</h3>
<p>Ebyte lässt das Syncword nicht konfigurieren; es ist ab Werk verdrahtet und
steht in keinem Handbuch. An einem SX126x-Empfänger lässt es sich <b>nicht
vollständig</b> bestimmen: Der wertet nur das erste der beiden
Syncword-Registerbytes aus, weshalb dort alle acht Werte 0x58–0x5F treffen.</p>
<p>Der SX1302 prüft <b>beide</b> Peak-Positionen streng und klärt es deshalb.
Ein Syncword <code>0xHL</code> steckt in den zwei Sync-Symbolen der Präambel;
der SX1302 speichert je Symbol <code>symbolwert / 4</code>, also
<b><code>peak_pos = nibble × 2</code></b>. Das Feld ist 5 Bit breit und wird
vorzeichenlos maskiert — alle 256 Werte sind erreichbar, die Beschränkung auf
0x12/0x34 ist reine Softwarekonvention.</p>
<table>
<tr><th>Register</th><th>Adresse</th><th>gilt für</th></tr>
<tr><td><code>SF5_PEAK1/2</code></td><td><code>0x588A/0x588B</code></td><td>alle 8 MultiSF-Kanäle, nur SF5</td></tr>
<tr><td><code>SF6_PEAK1/2</code></td><td><code>0x588C/0x588D</code></td><td>alle 8 MultiSF-Kanäle, nur SF6</td></tr>
<tr><td><code>SF7TO12_PEAK1/2</code></td><td><code>0x588E/0x588F</code></td><td>alle 8 MultiSF-Kanäle, SF7–12</td></tr>
<tr><td><code>LORA_SERVICE_PEAK1/2</code></td><td><code>0x5B2E/0x5B2F</code></td><td><b>nur <code>chan_Lora_std</code></b></td></tr>
</table>

<h3>8.6 Wenn nichts ankommt: peak2 absuchen</h3>
<p>Fremde Module können ein anderes unteres Nibble benutzen. Statt den
Forwarder sechzehnmal neu zu starten, wird das Register im laufenden Betrieb
gesetzt — der SX1302 hat kein Page-Register, jeder Zugriff ist ein einzelnes
<code>ioctl</code> und wird vom Kernel gegen den Forwarder serialisiert:</p>
<pre>for n in $(seq 0 15); do
    sx1302_poke 0x5B2F $((n*2))
    vorher=$(grep -c '"chan":8' /tmp/fwd.log); sleep 3
    nachher=$(grep -c '"chan":8' /tmp/fwd.log)
    printf 'sw=0x5%X  peak2=%2d  neue Pakete: %d\n' $n $((n*2)) $((nachher-vorher))
done</pre>
<p>Das Sendegerät muss dabei durchgehend funken. Genau so wurde 0x55 gefunden:
Pakete ausschließlich bei <code>peak2 = 10</code>.</p>

<h3>8.7 Prüfen</h3>
<pre>logread | grep syncword
  [syncword] LoRa Service LDRO forced to 1 (HAL rule overridden)
  [syncword] multi-SF ch0-7: SF5=0x12 SF6=0x12 SF7-12=0x34 | Lora_std (SF11): 0x55

sx1302_poke 0x5B2E   -> 0x0A    peak1, oberes Nibble 5
sx1302_poke 0x5B2F   -> 0x0A    peak2, unteres Nibble 5
sx1302_poke 0x5B22   -> 0x98    Bits 4-5 = 1, LDRO aktiv</pre>
<p>Ein empfangenes Paket erscheint als <code>rxpk</code> auf <b>chan 8</b>:</p>
<pre>{"chan":8,"freq":868.125000,"datr":"SF11BW500","rssi":-63,"stat":1,
 "size":15,"data":"LBKHJgD//wdCQF1WPyIh"}</pre>

<h3>8.8 Das Ebyte-Rahmenformat</h3>
<p>Auch im transparenten Modus verpackt das Modul die Nutzlast. Der Kopf ist
acht Byte lang, und die Nutzlast ist mit der <b>Kanalnummer</b> XOR-verweißt —
dieselbe Zahl steht in Byte 1:</p>
<pre>2C 12 87 26 00 FF FF 07 | 42 40 5D 56 3F 22 21
                                  XOR 0x12   -&gt; "PROD-03"

Byte 0    0x2C   Kennung
Byte 1    Kanalnummer
Byte 2-3  xx, xx ^ 0xA1   mit xx = (XOR über alle Nutzlastbytes) ^ 0xA0
Byte 4    NETID
Byte 5-6  **eigene** Adresse des sendenden Moduls
Byte 7    Länge der Nutzlast</pre>
<div class="merk">Byte 2–3 sind eine <b>Prüfsumme, kein Zähler</b> — gleiche
Nutzlast ergibt einen Byte für Byte identischen Rahmen. Und der XOR-Schlüssel
ist konstant <code>0x12</code>, nicht die Kanalnummer; beim 868er fällt beides
zufällig zusammen (Kanal 18 = 0x12), der 433er sendet auf Kanal 23 und weißt
trotzdem mit 0x12. Byte 5–6 tragen die <b>eigene</b> Adresse des Senders —
darauf beruht die Selbsterkennung.</div>

<h3>8.9 Was der Eingriff nicht anfasst</h3>
<p>Nachgemessen mit einem LA66-USB (EU868 v1.3, bereits gejoint): Uplink auf
868.500 MHz bei DR0 kommt unverändert auf <code>chan 2</code> an,
<code>SF12BW125</code>, <code>stat:1</code>, Rahmen sauber — MHDR 0x40,
DevAddr, FPort 2, Nutzlast lesbar. <b>Der LoRaWAN-Betrieb bleibt vollständig
erhalten</b>, weil ausschließlich das Register des Service-Modems verändert
wird.</p>

<h3>8.10 Alles in einem Skript</h3>
<p>Die fünf Handgriffe — Vorlage, <code>syncword.conf</code>, Wrapper,
Init-Skript, Neustart — fasst
<code>gateway/sx1302_syncword/setup_ebyte_rawchannel.sh</code> zusammen. Es
läuft auf dem Gateway, sichert jede angefasste Datei nach <code>.pre-ebyte</code>
und prüft sich am Ende selbst:</p>
<pre>setup_ebyte_rawchannel.sh --apply      # einrichten und pruefen
setup_ebyte_rawchannel.sh --status     # Ist-Zustand inkl. Registern
setup_ebyte_rawchannel.sh --revert     # alles zurueck, Stock-Verhalten</pre>
<p>Vorgaben passen zu einem Ebyte auf Werkskonfiguration; abweichend etwa
<code>--sf 7 --bw 500000 --sync 0x55</code> für Luftrate 19.2k. Ausgabe eines
erfolgreichen Laufs:</p>
<pre>==&gt; Vorlage angepasst (Sicherung: …/EU-global_conf.json.pre-ebyte)
==&gt; Init-Skript angepasst (Sicherung: /etc/init.d/lora_gw.pre-ebyte)
[syncword] LoRa Service LDRO forced to 1 (HAL rule overridden)
[syncword] multi-SF ch0-7: SF5=0x12 SF6=0x12 SF7-12=0x34 | Lora_std (SF11): 0x55
  0x5B2E = 0x0A (10)  peak1
  0x5B2F = 0x0A (10)  peak2</pre>

<h3>8.11 Die Gegenrichtung: Gateway sendet</h3>
<p>Alles oben betrifft den <b>Empfang</b>. Soll das Gateway den Ebyte-Knoten
auch <i>erreichen</i> — etwa einen E90-DTU-Repeater auf dem Berg —, greift eine
andere Stelle im HAL: <code>sx1302_send()</code> schreibt das Sende-Syncword
<b>für jedes Paket neu</b>, unmittelbar vor dem Tasten, wieder abgeleitet aus
<code>lorawan_public</code>. Ein Downlink geht damit stets als 0x34 hinaus, und
eine Gegenstelle auf 0x55 hört ihn nie.</p>
<p>Der Shim kann auch das (<code>tx = 0x55</code> in
<code>syncword.conf</code>); umgesetzt ist es durch Interposition von
<code>lgw_com_rmw()</code> mit Umschreiben der vier TX-Register
<code>0x526D/0x526E</code> und <code>0x546D/0x546E</code> — adressbasiert, also
wieder ohne Bindung an Draginos Strukturen.</p>
<p><code>tx</code> allein würde auf <i>jeden</i> Downlink wirken, auch auf die
von LoRaWAN — Join-Accepts und ADR gingen dann auf einem Syncword hinaus, das
kein Endgerät annimmt. Deshalb gibt es <code>tx_freq</code>:</p>
<pre>tx      = 0x55
tx_freq = 868125000     # nur Downlinks auf dieser Frequenz, Fenster +/- 5 kHz</pre>
<p>Möglich wird das dadurch, dass <code>sx1302_send()</code> die Sendefrequenz
in <code>loragw_sx1302.c:2604-2608</code> schreibt, <b>bevor</b> es in
<code>:2710</code> zum Syncword kommt. Der Shim liest die drei Frequenzbytes im
Vorbeigehen mit (sie laufen als 8-Bit-Direktschreibung über
<code>lgw_com_w()</code>, nicht über <code>lgw_com_rmw()</code>) und entscheidet
dann je Sendekette. Die Auflösung beträgt <code>32 MHz / 2<sup>18</sup></code> =
122 Hz, das trennt den Rohkanal auf 868.125 mühelos von
<code>chan_multiSF_0</code> auf 868.100, 25 kHz daneben.</p>
<table>
<tr><th><code>tx_freq</code></th><th>Downlink auf 868.125</th><th>peak1 / peak2</th><th>Syncword</th></tr>
<tr><td><code>868125000</code></td><td>Rohkanal getroffen</td><td>10 / 10</td><td><b>0x55</b> umgeschrieben</td></tr>
<tr><td><code>869525000</code> (RX2)</td><td>passt nicht</td><td>6 / 8</td><td>0x34, HAL-Wert unberührt</td></tr>
</table>
<div class="merk">Beim Ablesen der Register nicht stolpern: das Peak-Feld sind
die <b>unteren fünf Bit</b>. <code>0x526D = 0xAA</code> heißt
<code>0xAA &amp; 0x1F = 10</code>; die oberen Bits tragen AUTO_SCALE, GAIN und
DROP_ON_SYNCH.</div>

<div class="merk"><b>Funkrechtlich.</b> 868.0–868.6 MHz erlaubt 25 mW ERP bei
1 % Sendezeit. Ein Rohkanal mit BW 500 kHz auf 868.125 MHz belegt
867.875–868.375 MHz und überlappt damit die LoRaWAN-Kanäle 868.1 und 868.3 —
im selben Unterband zulässig, aber beim Sendezeitbudget mitzurechnen.</div>

<h2 class="neu">9 Gruppenkonzept: zwei Netze, eine Brücke</h2>

<p>Das Netz trennt seit dem 17.08.2026 zwei Gerätegruppen, verbunden allein
durch den E90-DTU als Relais. Dahinter stehen <b>zwei voneinander unabhängige
Mechanismen</b>, die sich leicht verwechseln lassen — ich habe sie beim
Erarbeiten mehrfach vermischt.</p>

<table>
<tr><th></th><th>Feld</th><th>Quelle</th></tr>
<tr><td><b>Adressierung</b></td><td>Kanal + Zieladresse</td><td>Handbuch T22U-Serie, 4.1/4.2</td></tr>
<tr><td><b>Weiterleitung</b></td><td>NETID-Paar</td><td>Handbuch, 5.3 Relay Networking</td></tr>
</table>

<h3>9.1 Wie Ebyte adressiert</h3>
<pre>00 03 | 04 | AA BB CC
Ziel-   Ziel- Daten
adresse kanal</pre>
<p>Der <b>Kanal grenzt die Gruppe ab</b>, die <b>Adresse wählt ein Mitglied</b>
darin. Bei Broadcast <code>FF FF</code> geben alle Module auf dem Kanal aus —
eines auf einem anderen Kanal schweigt auch dann.</p>
<div class="warn"><b>Die Adresse im Rahmen ist das Ziel, nicht der Absender.</b>
Die eigene Adresse des Senders taucht im Paket überhaupt nicht auf. Ein
Ebyte-Rahmen sagt also, <i>an wen</i> er geht — nie, <i>von wem</i> er kam.
Frühere Fassungen dieses Handbuchs und von <code>dell/lora_raw.py</code>
beschrifteten Byte 5–6 als Absender; das war falsch.</div>

<h3>9.2 Warum eine Gruppe über Kanäle nicht geht</h3>
<p>Wäre der Kanal die Gruppentrennung, kostete jede Gruppe eine eigene
Frequenz: <code>850.125 MHz + Kanal</code>. Kanal 18 ist unsere 868.125 MHz,
Kanal 19 wäre <b>869.125 MHz</b> — außerhalb von 868.0–868.6. Im nutzbaren
europäischen Unterband ist für eine zweite Gruppe schlicht kein Platz.</p>

<h3>9.3 Deshalb: NETID als Gruppenwähler</h3>
<pre>Kanal 18 (868.125 MHz)      gemeinsame Funkgruppe
Adresse 2201                Netzschlüssel, bewusst <b>kein</b> Broadcast
   ├── NETID 00   E22, dell
   └── NETID BB   Pico
E90-Relais  ADDH=00 ADDL=BB   einzige Brücke, bidirektional
Gateway                       ohne NETID, hört alle Gruppen</pre>
<div class="merk"><b>Die Adresse muss <code>2201</code> sein und darf nicht
<code>FFFF</code> sein.</b> Das Handbuch legt die Rangfolge fest: <i>„Network
code filtering has lower priority than broadcast addresses. Even with differing
network codes, broadcast data can still be received."</i> Mit Broadcast wären
die Gruppen also durchlässig — die NETID filtert nur, solange die Adresse keine
Broadcast-Adresse ist. Die Adresse dient hier deshalb als gemeinsamer
Netzschlüssel, die Trennung leistet allein die NETID.</div>

<h3>9.4 Die Weiterleitungsregel</h3>
<p>Im Relaismodus sind <code>ADDH</code>/<code>ADDL</code> keine Adressen mehr,
sondern das <b>NETID-Paar</b>: <i>„If data is received from one network, it is
forwarded to the other network."</i> Der E90 steht auf
<code>ADDH=00, ADDL=BB</code> und überträgt bidirektional zwischen diesen
beiden — und nur zwischen ihnen.</p>
<p>Er ändert dabei genau <b>ein</b> Byte:</p>
<pre>2c 12 68 c9 <b>00</b> 22 01 03 …    Original
2c 12 68 c9 <b>bb</b> 22 01 03 …    Weitergabe</pre>
<p>Prüfbyte, Zieladresse, Länge und Nutzlast bleiben unangetastet — nur die
NETID wird auf die Gegengruppe gesetzt, sonst verwürfen deren Empfänger den
Rahmen.</p>
<div class="warn">Vorher stand der E90 auf <code>ADDH = ADDL = 0x00</code>,
leitete also von NETID 0 nach NETID 0 zurück. Ebyte warnt davor ausdrücklich:
<i>„Using two or more relays with <b>identical</b> ADDH and ADDL addresses is
not recommended, as it may cause <b>circular forwarding</b>."</i> Das erklärte
das Echo, das der E22 auf seiner seriellen Seite sah — ein Symptom, kein
Merkmal.</div>

<h3>9.5 Nachgewiesen</h3>
<p>Gleiche Adresse, gleicher Kanal, gleiche Modulation — nur die NETID des
Senders verschieden:</p>
<table>
<tr><th>NETID des Pico</th><th>im Relaispaar?</th><th>E22 (NETID 00)</th></tr>
<tr><td><code>BB</code></td><td>ja</td><td><b>empfangen</b>, −23 bis −40 dBm</td></tr>
<tr><td><code>07</code></td><td>nein</td><td><b>Stille</b>, 0 von 4</td></tr>
</table>
<p>Beide Sperren greifen dabei zugleich: direkt, weil <code>07 ≠ 00</code> und
die Adresse kein Broadcast ist; über das Relais, weil <code>07</code> in
keiner Richtung seines Paares liegt.</p>

<h3>9.6 Das Gateway steht außerhalb</h3>
<p>Der Rohkanal des DLOS8N hat <b>keine NETID</b>. Sie ist ein Byte innerhalb
der Ebyte-Nutzlast; der SX1302 demoduliert auf der LoRa-Ebene — Frequenz, SF,
Bandbreite, Syncword — und reicht die Nutzlast unverändert weiter. Er kennt das
Ebyte-Protokoll nicht.</p>
<pre>netid 0x07  ziel 2201  b'FREMD-3'     am Gateway empfangen,
                                       vom E22 zugleich verworfen</pre>
<p>Das Gateway ist damit kein Gruppenmitglied, sondern <b>passiver
Mithörer</b> — praktisch günstig: Die Trennung wirkt zwischen den
Ebyte-Knoten, während die Überwachung über MQTT beide Gruppen sieht. Nur wenn
<code>dell/lora_raw.py</code> sendet, entsteht Gruppenzugehörigkeit, und die
steht dort als <code>EBYTE_NETID</code>.</p>

<h3>9.7 Was damit nicht geht</h3>
<p>Gezielte Einzeladressierung. Ein Rahmen an <code>2201</code> statt an den
Rundruf kam im Test <b>nicht</b> an. Kapitel 4.1 des Handbuchs steht unter der
Voraussetzung <i>„in fixed-point mode"</i> — die Endgeräte laufen aber
transparent (<code>REG3 = 0x80</code>). Im Transparentmodus wertet ein Modul
das Zielfeld nur gegen Broadcast und NETID aus. Für erlaubte Paare über
Einzeladressen müssten die Empfänger auf Fixpunkt (<code>REG3</code> Bit 6)
umgestellt werden — der E90 läuft ohnehin schon so, weil der Relaisbetrieb es
voraussetzt.</p>

<p class="fuss">Erzeugt aus <code>devices/pico_sx1262/</code> im Repository
gerontec/TTN. Zeichnung: <code>relais_uebersicht.dot</code>.</p>
</body></html>"""

html = html.replace("__SVG__", svg)
(HIER / "handbuch.html").write_text(html)  # Zwischenstand, nicht eingecheckt

pdf = ZIEL / "Relais_Brauneck_Handbuch.pdf"
r = subprocess.run(["chromium", "--headless=new", "--disable-gpu", "--no-sandbox",
                    "--no-pdf-header-footer", "--print-to-pdf=%s" % pdf,
                    "file://%s" % (HIER / "handbuch.html")],
                   capture_output=True, text=True, timeout=180)
if not pdf.exists():
    print(r.stderr[-1500:], file=sys.stderr)
    sys.exit(1)
print("erzeugt: %s (%d Byte)" % (pdf, pdf.stat().st_size))
