import os
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spi_dmx import artnet, daemon, frame  # noqa: E402


class ArtnetTests(unittest.TestCase):
    def test_roundtrip(self):
        pkt = artnet.build_artdmx(0x0102, bytes([1, 2, 3, 4]), sequence=7)
        uni, seq, data = artnet.parse_artdmx(pkt)
        self.assertEqual((uni, seq, data), (0x0102, 7, bytes([1, 2, 3, 4])))

    def test_odd_length_padded(self):
        pkt = artnet.build_artdmx(0, b"\x01\x02\x03")
        _, _, data = artnet.parse_artdmx(pkt)
        self.assertEqual(data, b"\x01\x02\x03\x00")

    def test_rejects_garbage(self):
        self.assertIsNone(artnet.parse_artdmx(b""))
        self.assertIsNone(artnet.parse_artdmx(b"x" * 40))
        pkt = bytearray(artnet.build_artdmx(0, b"\x01\x02"))
        pkt[8:10] = b"\x00\x20"  # autre opcode
        self.assertIsNone(artnet.parse_artdmx(bytes(pkt)))
        self.assertIsNone(artnet.parse_artdmx(artnet.build_artdmx(0, b"\x01\x02")[:-1]))


class ListSink:
    def __init__(self):
        self.frames = []

    def write(self, data):
        self.frames.append(data)

    def close(self):
        pass


class DaemonTests(unittest.TestCase):
    def test_state_truncates_and_updates(self):
        st = daemon.DmxState(4)
        st.update(bytes([9, 8, 7, 6, 5, 4]))
        self.assertEqual(st.snapshot(), bytes([9, 8, 7, 6]))
        st.update(bytes([1]))
        self.assertEqual(st.snapshot(), bytes([1, 8, 7, 6]))
        st.blackout()
        self.assertEqual(st.snapshot(), bytes(4))

    def test_udp_to_frame(self):
        st = daemon.DmxState(8)
        rx = daemon.ArtnetReceiver(st, universe=3, bind="127.0.0.1", port=0)
        rx.start()
        try:
            tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            tx.sendto(artnet.build_artdmx(2, bytes([99] * 8)), ("127.0.0.1", rx.port))  # autre univers
            tx.sendto(artnet.build_artdmx(3, bytes([10, 20, 30, 40, 50, 60, 70, 80])),
                      ("127.0.0.1", rx.port))
            deadline = time.monotonic() + 2
            while rx.packets == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(st.snapshot(), bytes([10, 20, 30, 40, 50, 60, 70, 80]))
        finally:
            rx.stop()

    def test_output_loop_rate_and_content(self):
        st = daemon.DmxState(4)
        st.update(bytes([1, 2, 3, 4]))
        sink = ListSink()
        stop = threading.Event()
        threading.Timer(0.5, stop.set).start()
        n = daemon.run_output_loop(st, sink, 40.0, stop)
        self.assertTrue(15 <= n <= 25, n)
        self.assertEqual(frame.decode_frame(sink.frames[0])["channels"], bytes([1, 2, 3, 4]))

    def test_timeout_blackout(self):
        st = daemon.DmxState(2)
        st.update(bytes([200, 200]))
        sink = ListSink()
        stop = threading.Event()
        threading.Timer(0.6, stop.set).start()
        daemon.run_output_loop(st, sink, 50.0, stop, timeout_s=0.2)
        self.assertEqual(frame.decode_frame(sink.frames[0])["channels"], bytes([200, 200]))
        self.assertEqual(frame.decode_frame(sink.frames[-1])["channels"], bytes([0, 0]))

    def test_main_dry_run(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "frames.bin")
            threading.Timer(0.4, lambda: os.kill(os.getpid(), 2)).start()
            rc = daemon.main(["--dry-run", out, "--channels", "8", "--rate", "50",
                              "--test-pattern"])
            self.assertEqual(rc, 0)
            blob = open(out, "rb").read()
            self.assertGreater(len(blob), 0)


if __name__ == "__main__":
    unittest.main()
