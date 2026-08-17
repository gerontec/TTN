#!/usr/bin/env python3
"""Unit-Tests fuer lora_raw.py -- ohne Funk, ohne Gateway, ohne Geraete.

Die Funktests dieser Strecke sind reihenweise am Zustand der Hardware
gescheitert, nicht an der Logik: der E22 stand im Konfigmodus und empfing
nichts, der Pico war abgesteckt, der logread-Ringpuffer lief um. Was hier
geprueft wird, laesst sich dagegen jederzeit beantworten.

Die Pruefsteine sind **echte Rahmen**, die am 17.08.2026 ueber die Luft
mitgeschnitten wurden -- kein selbst ausgedachtes Format. Wenn die Ebyte-
Rahmenbildung hier gruen ist, stimmt sie mit dem ueberein, was ein E22
tatsaechlich sendet.

    python3 -m unittest test_lora_raw -v
"""
import importlib.util
import unittest
from argparse import Namespace
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "lora_raw", Path(__file__).resolve().parent / "lora_raw.py")
lr = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(lr)
except SystemExit:          # argparse laeuft beim Import nicht an
    pass


# --- echte Mitschnitte, Gateway chan 8, 868.125 MHz SF11BW500 --------------
# vom E22 (Adresse FFFF), Nutzlast nach XOR 0x12 rechts danebengeschrieben
E22_E90X0 = bytes.fromhex("2c12a90800ffff06572b224a3f22")      # "E90X-0"
E22_E90X1 = bytes.fromhex("2c12a80900ffff06572b224a3f23")      # "E90X-1"
E22_PROD3 = bytes.fromhex("2c1287260 0ffff07 4240 5d56 3f2221".replace(" ", ""))  # "PROD-03"


class TestEbyteRahmen(unittest.TestCase):
    """Gegen echte Mitschnitte -- das ist der eigentliche Wert dieser Datei."""

    def test_absender_aus_echtem_rahmen(self):
        self.assertEqual(lr.ebyte_absender(E22_E90X0), "FFFF")
        self.assertEqual(lr.ebyte_absender(E22_PROD3), "FFFF")

    def test_nutzlast_aus_echtem_rahmen(self):
        self.assertEqual(lr.ebyte_nutzlast(E22_E90X0), b"E90X-0")
        self.assertEqual(lr.ebyte_nutzlast(E22_E90X1), b"E90X-1")
        self.assertEqual(lr.ebyte_nutzlast(E22_PROD3), b"PROD-03")

    def test_eigene_rahmung_trifft_das_echte_format(self):
        """Selbst gebaut muss byteweise dem entsprechen, was der E22 sendet.

        Das ist der schaerfste Test hier: Pruefbyte, dessen Komplement, NETID,
        Laenge und Weissung muessen alle stimmen, sonst weicht ein Byte ab.
        """
        nach = lr.ebyte_rahmen(b"E90X-0", "FFFF")
        self.assertEqual(nach, E22_E90X0)
        self.assertEqual(lr.ebyte_rahmen(b"PROD-03", "FFFF"), E22_PROD3)

    def test_pruefbyte_ist_summe_kein_zaehler(self):
        """Gleiche Nutzlast ergibt denselben Rahmen -- keine laufende Nummer."""
        self.assertEqual(lr.ebyte_rahmen(b"gleich", "E09C"),
                         lr.ebyte_rahmen(b"gleich", "E09C"))

    def test_pruefbyte_komplement(self):
        f = lr.ebyte_rahmen(b"irgendwas", "E09C")
        self.assertEqual(f[3], f[2] ^ 0xA1)

    def test_eigene_adresse_landet_im_rahmen(self):
        f = lr.ebyte_rahmen(b"x", "E09C")
        self.assertEqual(lr.ebyte_absender(f), "E09C")
        self.assertEqual(f[5:7], b"\xe0\x9c")

    def test_hin_und_zurueck(self):
        for text in (b"", b"a", b"GW2E22", b"x" * 200):
            f = lr.ebyte_rahmen(text, "E09C")
            self.assertEqual(lr.ebyte_nutzlast(f), text, text[:12])

    def test_kein_falsch_positiv(self):
        """Text darf nicht versehentlich als Ebyte-Rahmen gelten."""
        for roh in (b"E09C>hallo", b"C>STATUS", b",xxxxxxxTEXT",
                    b"\x2c\x12\x00", b""):
            self.assertIsNone(lr.ebyte_absender(roh), roh)


class TestTextRahmen(unittest.TestCase):

    def test_frischer_absender(self):
        self.assertEqual(lr.zerlege(b"E09C>PING"), (0, "E09C", b"PING"))

    def test_absender_ueberlebt_den_sprungpraefix(self):
        """Entscheidend fuer den Selbstfilter: das Echo kommt mit R1 zurueck."""
        self.assertEqual(lr.zerlege(b"R1E09C>PING"), (1, "E09C", b"PING"))
        self.assertEqual(lr.zerlege(b"R3E09C>PING")[0], 3)

    def test_befehl_hat_keinen_absender(self):
        self.assertIsNone(lr.zerlege(b"C>STATUS")[1])

    def test_ohne_kennung(self):
        sprung, absender, nutz = lr.zerlege(b"nur text")
        self.assertEqual((sprung, absender), (0, None))
        self.assertEqual(nutz, b"nur text")


def _args(**kw):
    grund = dict(freq=868.125, all=False, self_filter=True, id="E09C",
                 ebyte=True)
    grund.update(kw)
    return Namespace(**grund)


class _FakeMq:
    def __init__(self):
        self.gesendet = []

    def publish(self, topic, payload, qos=0):
        import json
        self.gesendet.append(json.loads(payload))


def _rxpk(roh, freq=868.125):
    import base64
    return {"freq": freq, "chan": 8, "datr": "SF11BW500", "rssi": -80,
            "lsnr": 8.0, "stat": 1, "size": len(roh),
            "data": base64.b64encode(roh).decode()}


class TestMqttAusgabe(unittest.TestCase):
    """Auf MQTT muss der Absender immer erkennbar sein."""

    def _einmal(self, roh, **kw):
        mq = _FakeMq()
        lr.handle_rxpk(_rxpk(roh), _args(**kw), mq)
        return mq.gesendet

    def test_ebyte_absender_ist_gesetzt(self):
        raus = self._einmal(E22_E90X0)
        self.assertEqual(len(raus), 1)
        self.assertEqual(raus[0]["absender"], "FFFF")

    def test_ebyte_text_ist_lesbar(self):
        raus = self._einmal(E22_E90X0)
        self.assertEqual(raus[0]["text"], "E90X-0")

    def test_ebyte_format_ist_markiert(self):
        self.assertEqual(self._einmal(E22_E90X0)[0]["format"], "ebyte")

    def test_text_absender_ist_gesetzt(self):
        raus = self._einmal(b"0C2B>FREMD")
        self.assertEqual(raus[0]["absender"], "0C2B")
        self.assertEqual(raus[0]["format"], "text")

    def test_niemals_absender_null_bei_bekanntem_format(self):
        """Der Punkt, um den es geht."""
        for roh in (E22_E90X0, E22_PROD3, b"0C2B>x", b"R1AB12>y"):
            raus = self._einmal(roh)
            self.assertIsNotNone(raus[0]["absender"], roh)


class TestSelbstfilter(unittest.TestCase):

    def _einmal(self, roh, **kw):
        mq = _FakeMq()
        lr.handle_rxpk(_rxpk(roh), _args(**kw), mq)
        return mq.gesendet

    def test_eigenes_echo_wird_verworfen(self):
        eigen = lr.ebyte_rahmen(b"meins", "E09C")
        self.assertEqual(self._einmal(eigen), [])

    def test_eigenes_echo_mit_sprungpraefix_wird_verworfen(self):
        self.assertEqual(self._einmal(b"R1E09C>meins"), [])

    def test_fremdes_geht_durch(self):
        fremd = lr.ebyte_rahmen(b"fremd", "0C2B")
        self.assertEqual(len(self._einmal(fremd)), 1)

    def test_abschaltbar(self):
        eigen = lr.ebyte_rahmen(b"meins", "E09C")
        self.assertEqual(len(self._einmal(eigen, self_filter=False)), 1)

    def test_gross_klein_egal(self):
        self.assertEqual(self._einmal(b"R1e09c>meins"), [])


class TestKanalfilter(unittest.TestCase):

    def _einmal(self, roh, freq, **kw):
        mq = _FakeMq()
        lr.handle_rxpk(_rxpk(roh, freq), _args(**kw), mq)
        return mq.gesendet

    def test_fremder_kanal_wird_verworfen(self):
        self.assertEqual(self._einmal(E22_E90X0, 868.500), [])

    def test_fremder_kanal_mit_all(self):
        self.assertEqual(len(self._einmal(E22_E90X0, 868.500, all=True)), 1)

    def test_quarzversatz_bleibt_drin(self):
        """Der E22 liegt gemessen rund 27 kHz daneben, das muss durchgehen."""
        self.assertEqual(len(self._einmal(E22_E90X0, 868.125 - 0.015)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
