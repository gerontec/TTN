# e22pico — one SX1262, four operating modes

The Waveshare Pico-LoRa (SX1262 on an RP2040) runs **one** firmware with four
operating modes. Only one runs at a time — one radio chip, four worlds. The
selected mode lives in flash and survives a power cut, and every switch works
**over the air from both sides**, because the node has no WLAN and nobody is
plugged into USB up on the mountain.

| | `0` `MODE_LORA` | `1` `MODE_LORAWAN` | `2` `MODE_REPEAT` | `3` `MODE_REPEAT_ID` |
|---|---|---|---|---|
| **what it is** | the raw Ebyte channel of the crisis network | a normal LoRaWAN node | a repeater that says nothing | the same repeater, and it says what it carried |
| **radio** | 868.125 MHz, SF11/BW500, CR4/5, LDRO 1, sync **0x55** | EU868, 867.1–868.5, SF7–12/BW125, sync **0x34** | listens 868.1, sends 867.1, SF9/BW125, sync **0x34** | as `MODE_REPEAT` |
| **framing** | Ebyte (magic `2c 12`, check bytes, address, XOR `0x12`) | LoRaWAN 1.0.3 class A, OTAA | none — the PHYPayload goes out **unchanged** | unchanged too; the report is a **second, separate** frame |
| **identity** | station id `0E22` = the device address | DevEUI `5049434F00000E22`, OTAA session | **none**, on purpose | its own ABP session, DevAddr `01DE2200`, FPort 20 |
| **peer** | E22 modules, E90 relay, `lora_raw.py` on the dell (UDP 1702) | ChirpStack on the dell (through the DLOS8N, UDP 1700) | any LoRaWAN node in range, and the DLOS8N | as `MODE_REPEAT`, plus its own uplinks |
| **can it be talked to?** | yes, `C>…` over the air | yes, downlink on FPort 10 | **no** — only the return ticket brings it back | **no** — same |
| **parameters** | [`src/loraparms.h`](src/loraparms.h) | [`src/lorawanparms.h`](src/lorawanparms.h) | [`src/lorawanparms.h`](src/lorawanparms.h), “repeater” | same file, “identity” |

The two repeater modes differ in exactly one thing, and it is worth saying
plainly: **neither of them touches the forwarded frame.** `MODE_REPEAT_ID`
does not add a byte to it — it sends a *second* frame of its own afterwards.
Why it cannot be otherwise is in [The repeater](#the-repeater) below.

`MODE_REPEAT_ID` is a separate mode and not a switch inside `MODE_REPEAT` so
that the **return ticket is the way out**: `C>MODE REPEAT_ID 30` reports for
half an hour and then goes back on its own. If the reports turn out to cost
more air time than they are worth, nobody has to climb up the mountain.

The same gateway hears both at the same time: the eight multi-SF channels of
the DLOS8N stay on 0x34, `chan_Lora_std` sits on 0x55 thanks to the sync word
shim (see [`../../../gateway/RAWKANAL.md`](../../../gateway/RAWKANAL.md) and
[`../../../gateway/sx1302_syncword/`](../../../gateway/sx1302_syncword/)).
Nothing has to be changed at the gateway for the switch.

State **21 Aug 2026**, verified on the hardware (section “What has been
measured”).

## Switching — four ways

| way | command | where it is useful |
|---|---|---|
| over the air, raw channel | `C>MODE LORAWAN\|LORA\|REPEAT\|REPEAT_ID [min]` | the real case: a node without WLAN, radio only |
| over the air, LoRaWAN | downlink FPort 10, byte 0 = `0x00` [+ 2 bytes of minutes] | the way back once the node is already on LoRaWAN |
| USB / UART | `mode lora` \| `mode lorawan` \| `mode repeat` \| `mode repeatid`, or `AT+LORAWAN=0|1|2|3[,min]` | at the desk |
| by itself | the minute count above | the return ticket, see below |

The return ticket leads back to **the mode the node came from** — with three
modes “the other one” is no longer defined, and only the mode that answered a
moment ago is proven to be reachable. In the repeater the node answers nobody
at all, so there the minute count is the only way back that does not need a
hand on the USB cable.

**The return ticket.** Both over-the-air commands take optional minutes:
`C>MODE LORAWAN 30` switches over and comes back to the raw channel on its own
after 30 minutes. A failed attempt is therefore not fatal — if nobody answers
on LoRaWAN, the node is back where it can be reached half an hour later. The
note lives in **RAM only**: a power cut in between leaves the node in the last
mode that was written to flash.

A mode change requested over the air runs only once the answer to it has been
sent — otherwise bringing the radio back up would tear the receipt away.

The minute count only takes effect when the mode actually changes. Asking for
the mode the node is already in (`AT+LORAWAN=1,5` on a node already on
LoRaWAN) is a no-op, minutes included.

## AT commands

The node also speaks the command set of the Dragino devices, so it can be
integrated like an LA66 stick. The template is the `AT+CFG` dump of our own
LA66 ([`../../la66_p2p/la66_lorawan_v1.3_cfg.txt`](../../la66_p2p/la66_lorawan_v1.3_cfg.txt));
Dragino's firmware for it is public ([github.com/dragino/LA66](https://github.com/dragino/LA66),
ASR6601 SDK).

Two equal interfaces: the **USB console** (115200) and a real **UART on GP0
(TX) / GP1 (RX)**, 9600 baud as the LA66 ships. The UART is the actual point —
a host without a USB stack (an ESP, a PLC, a Pi with no free port) hangs on the
node with two wires. Running commentary goes to both, answers only to whoever
asked.

Query with `=?`, the answer is the bare value followed by `OK`; errors are
`AT_ERROR`, `AT_PARAM_ERROR`, `AT_NO_NETWORK_JOINED`.

| command | effect | example / answer |
|---|---|---|
| `AT` | is anyone there | `OK` |
| `AT?` | command list | |
| `ATZ` | restart | |
| `AT+CFG` | show everything, lines in LA66 format | `AT+DEUI=50 49 43 4F 00 00 0E 22` … |
| `AT+VER=?` / `AT+VERSION=?` | firmware level | `EU868 v2.0.0 pico-e22 LoRa+LoRaWAN 0E22` |
| `AT+LORAWAN=?` | operating mode | `0` = raw channel, `1` = LoRaWAN |
| `AT+LORAWAN=1,30` | switch, return after 30 min | same language as the TrackerD |
| `AT+SEND=<cfm>,<port>,<len>,<text>` | send | a LoRaWAN uplink **or** an Ebyte frame, depending on the mode |
| `AT+SENDB=<cfm>,<port>,<len>,<hex>` | the same, binary | `AT+SENDB=0,2,2,00ff` |
| `AT+RECV=?` / `AT+RECVB=?` | last reception as text resp. hex | `0:PONG 1 N00 …` |
| `AT+JOIN` | trigger an OTAA join | LoRaWAN mode only |
| `AT+NJS=?` | 1 = session active | |
| `AT+DEUI=?` `AT+APPEUI=?` `AT+DADDR=?` `AT+FCU=?` | identifiers and counters | |
| `AT+ADR=0|1` `AT+DR=<0-5>` | ADR and data rate | |
| `AT+RELAY=0|1` | relay of the raw channel | |
| `AT+ID=?` `AT+RSSI=?` `AT+SNR=?` | station id, last reception | |
| `AT+FRE=?` `AT+SF=?` `AT+BW=?` `AT+CR=?` `AT+POWER=?` `AT+SYNCWORD=?` `AT+PREAMBLE=?` | raw channel parameters | **read-only**, see below |

Deliberate deviations from the LA66:

* **`AT+APPKEY` answers `<in device>`.** The key comes out neither over the
  console nor in the embedded source (`src`).
* **The raw channel parameters are read-only.** They live in `loraparms.h` and
  apply unchanged after every start — moving frequency or spreading factor by
  radio makes a station unreachable, exactly as `fernwirk.py` argues for the
  Brauneck relay. A write attempt answers `AT_ERROR`.
* **Receptions are reported unsolicited**, in the LA66 format
  `AT+RECVB=<port>:<hex>` (can be turned off with `AT_RECV_MELDEN` in
  [`src/atparms.h`](src/atparms.h)). Pure MAC downlinks (FPort 0, no payload)
  are not reported.

A host must not echo back what it receives: the node answers every line
starting with `AT` — including its own. (On a Linux terminal therefore
`stty -F /dev/ttyACM0 115200 raw -echo`, otherwise the two feed each other.)

The LA66 itself **cannot** switch between LoRaWAN and P2P by AT command: there
it is a firmware swap, see [`../../la66_p2p/README.md`](../../la66_p2p/README.md)
and `la66_mode.py`. The Pico can, because both stacks live in one binary.

## Short console commands

`diag` · `tx` · `relay [on|off]` · `mode [lora|lorawan|repeat|repeatid]` ·
`lwstat` · `lwsend <text>` · `lwreset` · `rptstat` · `rptlog` · `rpttx <hex>` ·
`src` · `boot`

`rptstat` prints the repeater's two channels, its counters and its identity.
`rptlog` shows the collected forwarding records that have not been reported
yet. `rpttx <hex>` injects bytes into the repeater queue as if they had been
received — the transmit side is checkable without a second LoRaWAN transmitter
in range.

`src` prints the node's own source — it ships inside the flash, generated by
`embed_source.py` before every build, by now over **all** files in `src/`
except `lorawan_secret.h`. `lwreset` drops session and DevNonce (after that the
network server has to be reset too, otherwise it rejects the repeated DevNonce
as a replay).

## Remote control over the raw channel

Same language as the Brauneck relay station ([`../fernwirk.py`](../fernwirk.py)):
command `C>NAME [value]`, answer `A><id>>text`. The id is **four hex digits and
at the same time the device address**: the last four digits of the DevEUI, here
`0E22` — the way the TrackerD derives its `076C` from `a840414f1188076c`.

| command | effect |
|---|---|
| `C>MODE` | query the operating mode |
| `C>MODE LORAWAN [min]` / `C>MODE LORA [min]` | switch, optionally with a return |
| `C>STATUS` | id, mode, counters, uptime, relay, uplinks |
| `C>RELAY 0\|1` | switch the relay |
| `C>ID` | read the id (not settable — it is the device address) |
| `C>PING` | is it alive |

From the dell: `./lora_cmd.py MODE LORAWAN 5`. Deliberately **without
authentication**, the same trade `fernwirk.py` makes: whoever is in radio range
can reconfigure the node. For a crisis system radio is the path that carries
when nothing else does.

Commands (`C>`) and answers (`A>`) are **never** forwarded, as in
`repeater.py`. A command that came through a relay (`RC>…`) still counts —
otherwise nobody behind a relay could be reached.

## The repeater

The third mode makes the node a plain LoRaWAN repeater: it listens on one
EU868 default channel and puts every frame it hears out again, **bit for bit**,
on a second frequency, `LWRPT_DELAY_MS` later.

| | value | why |
|---|---|---|
| listens | 868.1 MHz, SF9/BW125, CR4/5, sync 0x34, preamble 8 | EU868 default channel g0, DR3 = the operating rate of the devices to be repeated |
| sends | 867.1 MHz, 14 dBm | EU868 channel c4; the DLOS8N listens there (radio_0), so a forward shows up in the gateway |
| delay | 2000 ms | fixed, `LWRPT_DELAY_MS` |
| queue | 4 frames | `LWRPT_QUEUE`; anything beyond is dropped and counted |

Nothing is parsed and nothing is altered — that is the whole point. The MIC of
the original device stays valid, so the network server accepts the copy as a
normal uplink **of that device**. No session, no second identity, no
duty-cycle bookkeeping of the LoRaWAN stack: this is raw LoRa that merely
carries the LoRaWAN sync word.

**Why not a second TTN/ChirpStack identity for the repeater.** It looks like
the simpler road and is the more expensive one: the repeater has none of the
foreign device's keys, so it could only wrap the frame as the payload of an
uplink of its own. That costs the payload limit (115 bytes at DR3 — a full
LoRaWAN frame does not even fit), the 1 % duty cycle (the stack blocks the
node for about a hundred times the airtime after every forward, so a burst is
lost), a DevNonce/session of its own in flash — and on top of it something on
the server side that unpacks the frame again and feeds it back in. The
bit-identical copy needs none of that: gateway and network server see the
original device, and nothing has to be changed at either.

Loop protection is the frequency spacing: receive and transmit channel are far
enough apart that the node cannot hear its own forward — one radio chip, one
antenna. The same argument `RELAIS.md` makes for the Brauneck relay.

Listening works on exactly **one** spreading factor at a time. `LWRPT_SF 9`
therefore repeats DR3; OTAA join requests (DR0 = SF12) are not heard, that
would take a 12 there.

The node cannot be talked to in the repeater: it answers neither `C>` commands
(that is the raw channel) nor downlinks (that is LoRaWAN). Either the minute
count brings it back, or somebody puts a hand on the USB cable.

### Why the forwarded frame must not be touched

The obvious wish is to stamp a repeater id into the frame. It cannot be done,
and the reason is arithmetic:

```
MIC = AES-CMAC(NwkSKey, B0 | MHDR | MACPayload)[0:4]
```

The CMAC runs over the **whole** message, and the `B0` block carries its
**length**. One byte appended anywhere breaks it — and the repeater has
neither the `NwkSKey` nor the `AppSKey` of the foreign device to recompute
anything. If it had them it would not be a repeater but a man in the middle.

Worse than failing, it would fail *invisibly*: a network server answers a
modified frame with `No device-session exists for dev_addr` — the very message
a stale ABP session produces. The mistake would be indistinguishable from the
failure that cost us the morning of 28 Aug 2026.

### `MODE_REPEAT_ID`: the identification goes next to the frame

What can be read **without any key** is the header: `DevAddr` in bytes 1–4
(little endian), `FCnt` in 6–7, the message type in the top three bits of byte
0. That is enough to say afterwards which frame took which path; the join
happens in the database, over DevAddr + FCnt + time.

Every forward is recorded (DevAddr, FCnt, RSSI, SNR, MType), and after
`LWRPT_LOG_JEDE` forwards the node sends **its own LoRaWAN uplink** on FPort
20 with its own ABP session. Four bytes of header, nine per record — 31 bytes
at three records, far below the 115 an SF9 uplink may carry.

The uplink is built **by hand** (RadioLib's AES-ECB and AES-CMAC, see
`rptUplinkBauen()` in `main.cpp`) instead of through the LoRaWAN stack. The
stack would open RX1/RX2 and hold the radio for seconds, insist on its own
duty-cycle bookkeeping, and share a frame counter with the OTAA session. Built
by hand the report costs exactly one transmission — the same as a forward, on
the same frequency and spreading factor, **through the same queue**. And it is
only ever asked for when that queue is empty: the payload path comes first.

The identity lives in `src/lorawan_secret.h` (not in git,
[`cs_repeater.py`](../../../dell/cs_repeater.py) creates it and prints the
three lines). Left at zero the node repeats but stays silent about it.

**`skip_fcnt_check` on that device is deliberate.** The report's uplink counter
lives in RAM only. Keeping it in flash would mean a fourth field in `Zustand`,
and a changed struct invalidates every saved sector (`storage.cpp` checks the
length): the node would lose mode, DevNonces and LoRaWAN session in one go,
and the next OTAA join would be rejected as a replay. The price is that this
one device has no replay protection — for a diagnostic in a private network
that is the cheaper side of the trade.

## The LoRaWAN side

**Registration in ChirpStack** (on the dell, 192.168.5.23):
[`../../../dell/cs_pico.py`](../../../dell/cs_pico.py) creates application,
device profile (EU868, **LoRaWAN 1.0.3**, class A, OTAA) and device, and files
the AppKey:

```bash
APPKEY=<32 hex> /home/gh/.venv-chirpstack/bin/python cs_pico.py
```

1.0.3 and not 1.1, because the firmware hands RadioLib the AppKey only
(`nwkKey = NULL`); with a second key RadioLib would switch to 1.1 and the join
would fail against the profile.

**Uplink**, FPort 1, 8 bytes big endian, every 15 minutes (the duty cycle is
enforced by RadioLib on top of that):

| byte | content |
|---|---|
| 0–1 | uptime in minutes |
| 2–3 | frames received on the raw channel |
| 4–5 | frames answered |
| 6 | RSSI of the last raw packet (dBm, signed) |
| 7 | SNR (dB, signed) |

The decoder for it sits in the device profile (`cs_pico.py`, `CODEC`).

**Downlink control port 10**, enqueued with
[`../../../dell/cs_pico_mode.py`](../../../dell/cs_pico_mode.py):

| bytes | effect |
|---|---|
| `00` [`HH LL`] | back to the raw channel, optionally returning after `HHLL` minutes |
| `01` | stay on LoRaWAN, clear a pending return |
| `02 00\|01` | relay off/on |

```bash
./cs_pico_mode.py lora 30      # 30 minutes of raw channel, then back on its own
./cs_pico_mode.py lorawan
```

Class A: the command waits in the queue until the node transmits next. If you
do not want to wait, trigger an uplink (`lwsend x` or `AT+SEND=0,1,1,x`).

The encoding of that payload is covered by a unit test,
[`../../../dell/test_cs_pico_mode.py`](../../../dell/test_cs_pico_mode.py)
(`python3 -m unittest test_cs_pico_mode -v`).

## What survives a power cut

[`src/storage.h`](src/storage.h) / [`src/storage.cpp`](src/storage.cpp):
operating mode, DevNonce and LoRaWAN session live in the **last four flash
sectors**, written in turn with an increasing sequence number and a CRC32. The
youngest valid sector is the one that is read; a power cut mid-write only
invalidates the new sector, the old one still applies. In turn, because a
sector survives around 100,000 erase cycles and the session is rewritten
regularly during operation.

Why at all: an OTAA DevNonce must never repeat (the network server would treat
that as a replay), and without a saved session every restart would be a new
join. Saving happens on every mode change, after every join and every
`LW_SESSION_EVERY` uplinks (default 8).

**When leaving LoRaWAN mode the session is saved explicitly.** Without that the
uplink counter fell back to the last saved state when switching back, and
ChirpStack silently discarded the next uplinks as replays — measured exactly
like that on 21 Aug 2026.

## Building and flashing (remotely, no button)

```bash
pio run -d ~/e22pico                     # -> .pio/build/pico/firmware.uf2
printf "boot\n" > /dev/ttyACM0           # firmware command "boot" -> BOOTSEL
sleep 2
DEV=$(lsblk -lnp -o NAME,LABEL | awk '$2=="RPI-RP2"{print $1}')
udisksctl mount -b "$DEV"                # or: sudo mount -t vfat -o uid=gh …
cp ~/e22pico/.pio/build/pico/firmware.uf2 /media/$USER/RPI-RP2/
sync && sleep 2                          # the drive vanishes, the Pico reboots
```

The AppKey lives in `src/lorawan_secret.h` — **not in git**, the template is
[`src/lorawan_secret.h.template`](src/lorawan_secret.h.template). Without the
file the firmware still builds but will not join (the zero placeholder). Create
the key first, then build: a build before that flashes the placeholder, and the
network server reports nothing but a terse `Invalid MIC` — a trap we walked
into on 21 Aug 2026.

## Why not pico-lorawan

[Sandeep Mistry's pico-lorawan](https://github.com/sandeepmistry/pico-lorawan)
is the obvious reference, but it was the wrong road here — checked, not
assumed:

* The project's glue layer is **SX1276-only**: `src/lorawan.c` includes
  `sx1276-board.h`, talks to `SX1276.Spi`, `SX1276.DIO0/DIO1` and aborts in
  `lorawan_init()` on `SX1276Read(REG_LR_VERSION) != 0x12`. Its CMakeLists.txt
  pulls in exactly `radio/sx1276/sx1276.c` and
  `src/boards/rp2040/sx1276-board.c`. The SX126x driver does sit in the
  LoRaMac-node submodule, but without an rp2040 board layer (BUSY, DIO1, TCXO
  on DIO3, antenna switch on DIO2) it is of no use — that layer would have to
  be written from scratch.
* It is a pure **pico-sdk/CMake** project. This firmware is an
  Arduino/PlatformIO binary in which the raw channel has been running for
  months. Switching at runtime requires both stacks in *one* binary; two build
  systems and two radio drivers on the same chip would be a step back from
  what already works.

What was taken instead is the LoRaWAN stack of **RadioLib 7.7.1** — the same
library that already drives the raw channel. Both modes share one `Module`; the
LoRaWAN stack sets frequency, SF, sync word, preamble and IQ itself before
every uplink.

One trap in that: the raw channel forces `forceLDRO(1)` (the Ebyte factory
value). LoRaWAN needs the automatic setting, otherwise DR5 (SF7/BW125) would
carry an LDRO bit the gateway does not expect. On every switch `autoLDRO()` is
therefore set explicitly — and `forceLDRO` again on the way back.

## What has been measured (21 Aug 2026)

* **Join and uplink**: `Uplink received f_type=JoinRequest` →
  `DevAddr 00E68B81`, after that uplinks with LinkADRReq/DevStatusReq coming
  back as downlinks. Gateway `a84041ffff27e318`, DR3.
* **A downlink switches the mode**: `cs_pico_mode.py lora 3` → on the next
  uplink `downlink FPort 10, 3 B: 00 00 03` → `mode: raw channel`, return
  noted.
* **An over-the-air command switches the mode**: from the dell
  `./lora_cmd.py MODE LORAWAN 5` → answer `A>0E22>MODE LORAWAN, return in
  5 min` (RSSI −81, SNR 7.8) → switch, session resumed from flash, no new join.
* **AT over USB**: `AT` → `OK`; `AT+CFG` returns the full dump;
  `AT+SEND=0,1,5,hallo` on the raw channel arrives at the gateway as
  `868.125 MHz SF11BW500 RSSI −84 … 5B "hallo"`, while the LoRaWAN uplink of
  the same node runs as `867.900 MHz SF9BW125 … 21B`.
* **Flash**: the sequence numbers count up across all switches, and after a
  restart mode and session are there again (`session resumed`).

### Repeater (28 Aug 2026)

* **The transmit path is on the air**: `mode repeat` → `repeater: 868.1 MHz SF9
  BW125 sync 0x34 -> 867.1 MHz, 2000 ms delay`, then
  `rpttx 40112233440000010a0102030405deadbeef` → `18 B queued, out in 2000 ms`
  → `-> forward 18 B on 867.1 MHz`. Two seconds later ChirpStack on the dell:
  `Uplink received f_type=UnconfirmedDataUp` … `No device-session exists for
  dev_addr dev_addr=44332211` — exactly the injected frame, heard by gateway
  `a84041ffff27e318`. The complaint about the unknown DevAddr is the proof: the
  frame went out unaltered, and the repeater has no identity of its own.
* **The radio comes back to the listening channel** after the forward: the
  next `rptstat` shows `forwarded 1`, no TX error, and the 30 s pulse reports
  `alive: repeater 0 received, 1 forwarded, 0 dropped, 0 queued`.
* **Empfang ueber die Luft, gemessen am selben Tag um 06:31**: Der Sender war
  der dell selbst — [`../../../dell/pseudo-lorawan.py`](../../../dell/pseudo-lorawan.py)
  baut einen echten LoRaWAN-Uplink in Software und laesst ihn vom DLOS8N auf
  868.1 SF9 funken (MQTT `command/down`, `polarizationInversion: false`).
  Der Repeater hat ihn gehoert und weitergegeben:

  ```
  RPT #1 RSSI -99 dBm SNR 4.8 dB 32 B: 40 00 11 de 01 00 01 00 01 78 36 ...
    -> forward in 2000 ms on 867.1 MHz
    -> forward 32 B on 867.1 MHz
  ```

  Die Bytes sind Zeichen fuer Zeichen der PHYPayload, den `pseudo-lorawan.py`
  ausgegeben hat. Zwei Sekunden spaeter kam die Kopie beim Gateway an und
  ChirpStack quittierte sie mit `UPLINK_F_CNT_RETRANSMISSION` — genau das,
  was ein Repeater ausloesen soll: derselbe Rahmen ein zweites Mal, vom
  Netzwerkserver als Wiederholung erkannt und verworfen. Der Nutzen liegt in
  dem Fall, in dem die *erste* Kopie fehlt.
* **Nebenbefund**: der DLOS8N hoert seine eigene Sendung. Der Rahmen kam auch
  direkt auf 868.1 an, mit RSSI −16 dBm — Nahfeldkopplung auf die zweite
  Funkkette des SX1302. Fuer den Repeater aendert das nichts (er sendet auf
  einer anderen Frequenz als er hoert), fuer Sendeversuche ueber das Gateway
  heisst es: die Selbsttaubheit, mit der man rechnet, gibt es hier nicht.

### Repeater with identity (28 Aug 2026)

`mode repeatid`, then three uplinks from the dell over the gateway
([`pseudo-lorawan.py`](../../../dell/pseudo-lorawan.py), DevAddr `01DE1100`).
Three forwards, then the report:

```
RPT #3 RSSI -100 dBm SNR 4.5 dB 27 B: 40 00 11 de 01 00 04 00 01 1f 74 ...
  -> forward in 2000 ms on 867.1 MHz
  -> forward 27 B on 867.1 MHz
  -> report FCnt 0, 3 records, 31 B payload
  -> forward 44 B on 867.1 MHz
```

And in ChirpStack, as device `pico-0e22-repeater` on FPort 20:

```json
{"version": 1, "weitergegeben": 3, "anzahl": 3, "weitergaben": [
  {"dev_addr": "01de1100", "f_cnt": 2, "rssi": -102, "snr": 2.75, "m_type": 2},
  {"dev_addr": "01de1100", "f_cnt": 3, "rssi": -100, "snr": 4.75, "m_type": 2},
  {"dev_addr": "01de1100", "f_cnt": 4, "rssi": -100, "snr": 4.5,  "m_type": 2}]}
```

Three DevAddr/FCnt pairs that match the three frames the dell sent, each with
the level at which the repeater heard it — and the forwarded frames themselves
went out byte for byte unchanged.

## Contents

```
platformio.ini              PlatformIO project (board=pico, framework=arduino)
src/loraparms.h             parameters and pins of the raw channel
src/lorawanparms.h          LoRaWAN parameters, DevEUI, start mode
src/lorawan_secret.h        AppKey -- not in git (template: *.template)
src/atparms.h               AT interface: UART pins/baud, version, reporting
src/storage.h/.cpp          flash ring buffer for mode and session
src/main.cpp                the firmware
embed_source.py             embeds src/ into the firmware before every build
pico_c_pingpong.py          test script: the E22 sends "A n", counts PONGs
```

Counterparts on the dell:
[`cs_pico.py`](../../../dell/cs_pico.py) (create it in ChirpStack),
[`cs_pico_mode.py`](../../../dell/cs_pico_mode.py) (downlink control command),
[`test_cs_pico_mode.py`](../../../dell/test_cs_pico_mode.py) (unit test),
[`lora_cmd.py`](../../../dell/lora_cmd.py) (radio command on the raw channel).
