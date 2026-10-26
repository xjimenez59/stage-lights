import socket
import time
import unittest

from spi_dmx import artnet
from spi_dmx.daemon import ArtnetReceiver, DmxState
from stage_control.engine import Engine
from stage_control.output import ArtnetSender, OutputLoop
from stage_control.plan import Fixture, Plan
from stage_control.profile import profile_from_dict
from stage_control.scene import FixtureState, Scene

RGB = profile_from_dict({
    "name": "rgb3", "modes": {"3ch": {"channels": [
        {"role": "red"}, {"role": "green"}, {"role": "blue"}]}}})


def make_engine():
    plan = Plan([Fixture("a", "A", RGB, "3ch", 1), Fixture("b", "B", RGB, "3ch", 4)])
    scenes = {"red": Scene("red", "Rouge", 0.0, {"a": FixtureState(rgb=(1, 0, 0), intensity=1.0),
                                                 "b": FixtureState(rgb=(0, 0, 1), intensity=1.0)})}
    return Engine(plan, scenes, default_fade=0.0, blackout_fade=0.0, initial_scene="red")


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx.bind(("127.0.0.1", 0))
        self.rx.settimeout(2.0)
        self.port = self.rx.getsockname()[1]

    def tearDown(self):
        self.rx.close()

    def test_packet_is_valid_artdmx_with_sequence(self):
        s = ArtnetSender("127.0.0.1", self.port, universe=3)
        for _ in range(2):
            s.send(bytes([1, 2, 3, 4]))
        first = artnet.parse_artdmx(self.rx.recvfrom(1024)[0])
        second_raw = self.rx.recvfrom(1024)[0]
        s.close()
        self.assertEqual(first, (3, 1, bytes([1, 2, 3, 4])))
        self.assertEqual(second_raw[12], 2)

    def test_sequence_wraps_without_zero(self):
        s = ArtnetSender("127.0.0.1", self.port)
        s._seq = 255
        s.send(bytes(2))
        s.close()
        self.assertEqual(self.rx.recvfrom(1024)[0][12], 1)


class LoopTests(unittest.TestCase):
    def test_channels_default_to_last_used(self):
        loop = OutputLoop(make_engine(), ArtnetSender(), rate_hz=40)
        self.assertEqual(loop.channels, 6)

    def test_bad_rate(self):
        with self.assertRaises(ValueError):
            OutputLoop(make_engine(), ArtnetSender(), rate_hz=0)

    def test_tick_sends_trimmed_frame(self):
        e = make_engine()
        e.set_blackout(False)
        sent = []

        class Fake:
            def send(self, data):
                sent.append(data)

        loop = OutputLoop(e, Fake(), channels=6)
        loop.tick()
        self.assertEqual(sent, [bytes([255, 0, 0, 0, 0, 255])])

    def test_send_error_is_counted_not_raised(self):
        class Broken:
            def send(self, data):
                raise OSError("réseau coupé")

        loop = OutputLoop(make_engine(), Broken())
        loop.tick()
        self.assertEqual((loop.sent, loop.errors), (0, 1))

    def test_end_to_end_into_spi_dmx_receiver(self):
        """Moteur -> boucle -> UDP -> ArtnetReceiver de spi_dmx -> tampon DMX."""
        state = DmxState(6)
        receiver = ArtnetReceiver(state, universe=0, bind="127.0.0.1", port=0)
        receiver.start()
        e = make_engine()
        e.set_blackout(False)
        sender = ArtnetSender("127.0.0.1", receiver.port)
        loop = OutputLoop(e, sender, rate_hz=100)
        loop.start()
        try:
            deadline = time.monotonic() + 3.0
            while state.snapshot() != bytes([255, 0, 0, 0, 0, 255]) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(state.snapshot(), bytes([255, 0, 0, 0, 0, 255]))
            e.toggle_blackout()  # blackout : le DMX doit passer à zéro
            deadline = time.monotonic() + 3.0
            while state.snapshot() != bytes(6) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(state.snapshot(), bytes(6))
        finally:
            loop.stop()
            loop.join(2)
            receiver.stop()
            sender.close()
        self.assertGreater(loop.sent, 2)


if __name__ == "__main__":
    unittest.main()
