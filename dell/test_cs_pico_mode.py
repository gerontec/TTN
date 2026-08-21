#!/usr/bin/env python3
"""Unit test for the downlink payload of the Pico mode switch.

The encoding is the contract between cs_pico_mode.py and the firmware
(lorawanDownlink() in devices/pico_sx1262/e22pico/src/main.cpp): FPort 10,
byte 0 = command, for "lora" two more bytes of minutes, big endian.

    python3 -m unittest test_cs_pico_mode -v
"""
import unittest

import cs_pico_mode as m


class TestPayload(unittest.TestCase):
    def test_lora_without_minutes(self):
        self.assertEqual(m.payload(["lora"]), b"\x00\x00\x00")

    def test_lora_with_minutes_big_endian(self):
        self.assertEqual(m.payload(["lora", "3"]), b"\x00\x00\x03")
        # 300 minutes must not be truncated to one byte -- 300 & 0xFF is 44.
        self.assertEqual(m.payload(["lora", "300"]), b"\x00\x01\x2c")
        self.assertEqual(m.payload(["lora", "65535"]), b"\x00\xff\xff")

    def test_minutes_out_of_range(self):
        with self.assertRaises(ValueError):
            m.payload(["lora", "65536"])
        with self.assertRaises(ValueError):
            m.payload(["lora", "-1"])

    def test_lorawan(self):
        self.assertEqual(m.payload(["lorawan"]), b"\x01")
        self.assertEqual(m.payload(["LORAWAN"]), b"\x01")

    def test_relay(self):
        self.assertEqual(m.payload(["relay", "on"]), b"\x02\x01")
        self.assertEqual(m.payload(["relay", "off"]), b"\x02\x00")

    def test_unknown(self):
        for argv in ([], ["nonsense"], ["relay"]):
            with self.assertRaises(ValueError):
                m.payload(argv)

    def test_fport_matches_firmware(self):
        # LW_CONTROL_PORT in src/lorawanparms.h
        self.assertEqual(m.FPORT, 10)


if __name__ == "__main__":
    unittest.main()
