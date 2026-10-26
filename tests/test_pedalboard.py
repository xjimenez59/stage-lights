import os
import socket
import tempfile
import threading
import time
import unittest

from stage_control.controller import Controller, EventBus
from stage_control.pedalboard import PedalboardLink, SerialTransport, format_leds
from stage_control.scene import FixtureState, Scene
from stage_control.sequence import Sequence, Step
from stage_control.store import PedalAction, Settings, Store

REPO_PROFILES = os.path.join(os.path.dirname(__file__), "..", "profiles")
PROFILE_KEY = "eurolite-party-spot-silent-rgbww"


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class FakeDevice(threading.Thread):
    """Joue le rôle du pédalier : serveur TCP sur lequel le Pi se connecte."""

    def __init__(self, hello=True, answer_ping=True):
        super().__init__(daemon=True)
        self.hello, self.answer_ping = hello, answer_ping
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.srv.settimeout(0.1)
        self.port = self.srv.getsockname()[1]
        self.lines = []  # tout ce que le Pi a envoyé
        self.connections = 0
        self.conn = None
        self._halt = threading.Event()
        self.start()

    def run(self):
        while not self._halt.is_set():
            try:
                conn, _ = self.srv.accept()
            except (socket.timeout, OSError):
                continue
            self.connections += 1
            self.conn = conn
            conn.settimeout(0.1)
            buf = b""
            while not self._halt.is_set() and self.conn is conn:
                try:
                    data = conn.recv(256)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode().strip()
                    self.lines.append(text)
                    if text == "WHO" and self.hello:
                        self.send("HELLO 1.0 7")
                    elif text == "PING" and self.answer_ping:
                        self.send("PONG")
            try:
                conn.close()
            except OSError:
                pass

    def send(self, line):
        try:
            self.conn.sendall((line + "\n").encode())
        except (OSError, AttributeError):
            pass

    def drop(self):
        conn, self.conn = self.conn, None
        if conn:
            conn.close()

    def leds(self):
        return [x for x in self.lines if x.startswith("LED ")]

    def stop(self):
        self._halt.set()
        self.drop()
        self.srv.close()


class PedalboardCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(os.path.join(tmp.name, "data"), REPO_PROFILES)
        store.save_plan([{"id": f"p{i}", "name": f"Spot {i}", "profile": PROFILE_KEY, "mode": "6ch",
                          "address": 1 + 6 * (i - 1)} for i in (1, 2)])
        red = FixtureState(rgb=(1, 0, 0), intensity=1.0)
        store.save_scenes({
            "rouge": Scene("rouge", "Rouge", 0.0, {"p1": red, "p2": red}),
            "bleu": Scene("bleu", "Bleu", 0.0, {"p1": FixtureState(rgb=(0, 0, 1), intensity=1.0)}),
            "strobe": Scene("strobe", "Strobe", 0.0, {"p1": FixtureState(rgb=(1, 1, 1), intensity=1.0, strobe=1.0)}),
        })
        store.save_sequences({"duo": Sequence("duo", "Duo", [Step("rouge"), Step("bleu")])})
        store.save_settings(Settings(default_fade=0.0, blackout_fade=0.0, flash_fade=0.0, pedals=[
            PedalAction("scene", "rouge"), PedalAction("scene", "bleu"), PedalAction("sequence", "duo"),
            PedalAction("flash", "strobe"), PedalAction("next"), PedalAction("prev")]))
        self.engine, settings = store.build_engine()
        self.controller = Controller(self.engine, store, settings, EventBus(), save_delay=0.0)
        self.device = FakeDevice()
        self.addCleanup(self.device.stop)
        self.link = None

    def start_link(self, **kw):
        opts = dict(ping_s=0.1, dead_s=0.6, hello_s=0.5, retry_s=0.05)
        opts.update(kw)
        self.link = PedalboardLink(self.controller, f"tcp:127.0.0.1:{self.device.port}", **opts)
        self.link.start()
        self.addCleanup(self._stop_link)
        return self.link

    def _stop_link(self):
        self.link.stop()
        self.link.join(3)

    def connected(self):
        return wait_for(lambda: self.controller.pedalboard["connected"])


class LinkTests(PedalboardCase):
    def test_connects_and_sends_the_initial_led_state(self):
        self.start_link()
        self.assertTrue(self.connected())
        self.assertEqual(self.controller.pedalboard["version"], "1.0")
        self.assertTrue(self.controller.pedalboard["port"].startswith("tcp:"))
        self.assertEqual(self.device.lines[0], "WHO")
        self.assertTrue(wait_for(lambda: self.device.leds()))
        self.assertEqual(self.device.leds()[0], "LED 000000 1")  # démarrage en blackout, aucune scène

    def test_buttons_drive_the_controller_and_leds_follow(self):
        self.start_link()
        self.assertTrue(self.connected())
        self.engine.set_blackout(False)
        self.device.send("BTN 2 1")
        self.device.send("BTN 2 0")
        self.assertTrue(wait_for(lambda: self.engine.status()["active"] == "bleu"))
        self.assertTrue(wait_for(lambda: "LED 010000 0" in self.device.leds()))
        self.device.send("BTN 7 1")  # blackout
        self.device.send("BTN 7 0")
        self.assertTrue(wait_for(lambda: self.engine.blackout))
        self.assertTrue(wait_for(lambda: self.device.leds()[-1] == "LED 010000 1"))  # LED de scène + blackout

    def test_flash_follows_the_foot(self):
        self.start_link()
        self.assertTrue(self.connected())
        self.engine.set_blackout(False)
        self.device.send("BTN 4 1")
        self.assertTrue(wait_for(lambda: self.engine.status()["flash"] == "strobe"))
        # sortir du blackout sans scène mémorisée rappelle la première (« rouge », pédale 1) ; le flash allume la pédale 4
        self.assertTrue(wait_for(lambda: "LED 100100 0" in self.device.leds()))
        self.device.send("BTN 4 0")
        self.assertTrue(wait_for(lambda: self.engine.status()["flash"] is None))

    def test_pedals_are_released_when_the_link_drops(self):
        self.start_link()
        self.assertTrue(self.connected())
        self.engine.set_blackout(False)
        self.device.send("BTN 4 1")
        self.assertTrue(wait_for(lambda: self.engine.status()["flash"] == "strobe"))
        self.device.drop()  # câble arraché pendant que le flash est maintenu
        self.assertTrue(wait_for(lambda: self.engine.status()["flash"] is None))
        self.assertTrue(wait_for(lambda: not self.controller.pedalboard["connected"] or self.device.connections > 1))

    def test_reconnects_and_resends_the_state(self):
        self.start_link()
        self.assertTrue(self.connected())
        self.engine.set_blackout(False)
        self.engine.recall("bleu")
        self.device.drop()
        self.assertTrue(wait_for(lambda: self.device.connections == 2))
        self.assertTrue(wait_for(lambda: self.controller.pedalboard["connected"]))
        before = len(self.device.leds())
        self.assertTrue(wait_for(lambda: self.device.leds()[-1] == "LED 010000 0" and len(self.device.leds()) >= 1))
        self.assertGreaterEqual(self.device.lines.count("WHO"), 2)
        self.assertGreaterEqual(len(self.device.leds()), before)

    def test_silent_device_is_declared_dead_and_the_link_restarts(self):
        self.device.answer_ping = False
        self.start_link(dead_s=0.4)
        self.assertTrue(self.connected())
        self.assertTrue(wait_for(lambda: self.device.connections >= 2, timeout=4.0))

    def test_device_without_hello_is_not_a_pedalboard(self):
        self.device.hello = False
        self.start_link(hello_s=0.3)
        self.assertTrue(wait_for(lambda: self.device.connections >= 2, timeout=3.0))  # il réessaie
        self.assertFalse(self.controller.pedalboard["connected"])
        self.assertEqual([x for x in self.device.lines if x.startswith("LED")], [])  # n'envoie rien d'autre que WHO

    def test_garbage_and_repeats_are_ignored(self):
        link = self.start_link()
        self.assertTrue(self.connected())
        self.engine.set_blackout(False)
        for line in ("BTN 9 1", "BTN x 1", "BTN 2", "FOO bar", "", "BTN 2 1", "BTN 2 1", "BTN 2 0", "BTN 2 0"):
            self.device.send(line)
        self.assertTrue(wait_for(lambda: self.engine.status()["active"] == "bleu"))
        self.assertTrue(wait_for(lambda: link.ignored >= 4))
        self.assertTrue(wait_for(lambda: link.down == set()))  # le relâchement a bien été traité (les répétitions n'ont rien changé)
        self.assertTrue(self.controller.pedalboard["connected"])

    def test_missing_scene_does_not_kill_the_link(self):
        link = self.start_link()
        self.assertTrue(self.connected())
        del self.engine.scenes["rouge"]  # la pédale 1 pointe maintenant vers une scène supprimée
        self.device.send("BTN 1 1")
        self.device.send("BTN 1 0")
        self.device.send("BTN 2 1")
        self.assertTrue(wait_for(lambda: self.engine.status()["active"] == "bleu"))
        self.assertTrue(link.is_alive())

    def test_state_dump_exposes_the_pedalboard(self):
        self.assertFalse(self.controller.dump()["pedalboard"]["enabled"])
        self.start_link()
        self.assertTrue(self.connected())
        info = self.controller.dump()["pedalboard"]
        self.assertEqual((info["enabled"], info["connected"], info["version"]), (True, True, "1.0"))

    def test_status_change_event_is_published(self):
        q = self.controller.bus.subscribe()
        self.start_link()
        self.assertTrue(self.connected())
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        self.assertIn(("pedalboard", {"enabled": True, "connected": True, "port": f"tcp:127.0.0.1:{self.device.port}",
                                       "version": "1.0"}), events)


class HelpersTests(unittest.TestCase):
    def test_format_leds(self):
        self.assertEqual(format_leds({"slots": [True, False, False, True, False, False], "blackout": False}),
                         "LED 100100 0")
        self.assertEqual(format_leds({"slots": [False] * 6, "blackout": True}), "LED 000000 1")

    @unittest.skipUnless(hasattr(os, "openpty"), "pty indisponible (hors Linux)")
    def test_serial_transport_on_a_pty(self):
        master, slave = os.openpty()
        try:
            t = SerialTransport(os.ttyname(slave))
            os.write(master, b"BTN 1 1\n")
            got = b""
            end = time.monotonic() + 2
            while b"\n" not in got and time.monotonic() < end:
                got += t.read(0.1)
            self.assertEqual(got, b"BTN 1 1\n")  # mode brut : pas de modification des octets
            self.assertEqual(t.read(0.05), b"")  # délai dépassé : rien
            t.write(b"LED 100000 0\n")
            self.assertEqual(os.read(master, 64), b"LED 100000 0\n")
            t.close()
        finally:
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    unittest.main()
