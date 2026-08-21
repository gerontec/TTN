#!/usr/bin/env python3
"""Switches the Pico node over by LoRaWAN downlink (FPort 10).

The way back to the raw channel: on LoRaWAN the node only listens in the two
receive windows after an uplink of its own (class A), so the command waits in
the ChirpStack queue until the next uplink arrives.

    ./cs_pico_mode.py lora [minutes]   back to the raw channel; with minutes
                                       the node returns to LoRaWAN on its own
                                       (the return ticket)
    ./cs_pico_mode.py lorawan          stay on LoRaWAN, clear a pending return
    ./cs_pico_mode.py relay on|off     switch the relay of the raw channel

The other direction (raw channel -> LoRaWAN) does not go through here but over
the air: ./lora_cmd.py MODE LORAWAN [minutes]
"""
import os
import sys

DEV_EUI = "5049434f00000e22"
FPORT = 10


def payload(argv):
    """Builds the downlink payload. Pure function, covered by test_cs_pico_mode.py."""
    what = (argv[0] if argv else "").lower()
    if what == "lora":
        minutes = int(argv[1]) if len(argv) > 1 else 0
        if not 0 <= minutes <= 0xFFFF:
            raise ValueError("minutes must fit into two bytes")
        return bytes([0x00, (minutes >> 8) & 0xFF, minutes & 0xFF])
    if what == "lorawan":
        return bytes([0x01])
    if what == "relay" and len(argv) > 1:
        return bytes([0x02, 1 if argv[1].lower() in ("on", "1", "true") else 0])
    raise ValueError(__doc__)


def token():
    with open(os.path.expanduser("~/.config/chirpstack/api.key")) as f:
        for line in f:
            if line.startswith("CHIRPSTACK_TOKEN="):
                return line.strip().split("=", 1)[1]
    sys.exit("no ChirpStack token found")


def main():
    try:
        data = payload(sys.argv[1:])
    except ValueError as e:
        sys.exit(str(e))

    import grpc
    from chirpstack_api import api

    chan = grpc.insecure_channel("127.0.0.1:8090")
    auth = [("authorization", "Bearer " + token())]
    req = api.EnqueueDeviceQueueItemRequest()
    req.queue_item.dev_eui = DEV_EUI
    req.queue_item.f_port = FPORT
    req.queue_item.data = data
    req.queue_item.confirmed = False
    ident = api.DeviceServiceStub(chan).Enqueue(req, metadata=auth).id
    print("enqueued:", data.hex(), "FPort", FPORT, "id", ident)
    print("will be delivered on the node's next uplink")


if __name__ == "__main__":
    main()
