import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spi_dmx import frame  # noqa: E402


class FrameTests(unittest.TestCase):
    def test_roundtrip_full_universe(self):
        data = bytes(range(256)) + bytes(range(256))
        out = frame.build_frame(data)
        dec = frame.decode_frame(out)
        self.assertEqual(dec["channels"], data)
        self.assertEqual(dec["start_code"], 0)
        self.assertEqual(dec["break_bits"], frame.DEFAULT_BREAK_BITS)
        self.assertEqual(dec["mab_bits"], frame.DEFAULT_MAB_BITS)

    def test_roundtrip_short(self):
        for n in (1, 2, 7, 8, 9, 32, 100):
            data = bytes((i * 37 + 5) & 0xFF for i in range(n))
            dec = frame.decode_frame(frame.build_frame(data))
            self.assertEqual(dec["channels"], data, n)

    def test_timing_matches_dmx_spec(self):
        # break >= 92 µs, MAB >= 12 µs à 4 µs/bit
        self.assertGreaterEqual(frame.DEFAULT_BREAK_BITS * frame.BIT_US, 92)
        self.assertGreaterEqual(frame.DEFAULT_MAB_BITS * frame.BIT_US, 12)

    def test_length_512(self):
        out = frame.build_frame(bytes(512))
        bits = 25 + 4 + 11 * 513
        self.assertEqual(len(out), (bits + 7) // 8)
        # ~ 22,8 ms
        self.assertAlmostEqual(frame.frame_duration_us(512) / 1000, 22.8, delta=0.3)

    def test_first_slot_bit_order(self):
        # valeur 0x01 : LSB d'abord -> 0 (start) 1 0 0 0 0 0 0 0 1 1
        out = frame.build_frame(b"\x01", break_bits=8, mab_bits=8)
        bits = "".join(f"{b:08b}" for b in out)
        # 8 zéros de break, 8 uns de MAB, puis le start code 0x00 : 0 00000000 11
        self.assertEqual(bits[:8], "0" * 8)
        self.assertEqual(bits[8:16], "1" * 8)
        self.assertEqual(bits[16:27], "0" + "00000000" + "11")
        self.assertEqual(bits[27:38], "0" + "10000000" + "11")

    def test_ends_idle_high(self):
        out = frame.build_frame(b"\x00\x00\x00")
        self.assertEqual(out[-1] & 1, 1)  # dernier bit à 1 : repos haut
        out = frame.build_frame(b"\x00", idle_bytes=3)
        self.assertEqual(out[-3:], b"\xff\xff\xff")

    def test_start_code(self):
        dec = frame.decode_frame(frame.build_frame(b"\x10", start_code=0xCC))
        self.assertEqual(dec["start_code"], 0xCC)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            frame.build_frame(bytes(513))
        with self.assertRaises(ValueError):
            frame.build_frame(b"\x00", break_bits=0)
        with self.assertRaises(frame.FrameDecodeError):
            frame.decode_frame(b"\xff\xff")


if __name__ == "__main__":
    unittest.main()
