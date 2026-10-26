import http.client
import json
import os
import tempfile
import threading
import unittest

from stage_control.controller import Controller, EventBus
from stage_control.scene import FixtureState, Scene
from stage_control.sequence import Sequence, Step
from stage_control.server import make_server
from stage_control.store import PedalAction, Settings, Store

REPO_PROFILES = os.path.join(os.path.dirname(__file__), "..", "profiles")
PROFILE_KEY = "eurolite-party-spot-silent-rgbww"


def red(i=1.0):
    return FixtureState(rgb=(1, 0, 0), intensity=i)


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.static = os.path.join(self.tmp.name, "web")
        os.makedirs(self.static)
        with open(os.path.join(self.static, "index.html"), "w", encoding="utf-8") as f:
            f.write("<h1>ok</h1>")
        with open(os.path.join(self.tmp.name, "secret.txt"), "w", encoding="utf-8") as f:
            f.write("secret")

        data = os.path.join(self.tmp.name, "data")
        self.store = Store(data, REPO_PROFILES)
        self.store.save_plan([{"id": f"p{i}", "name": f"Spot {i}", "profile": PROFILE_KEY,
                               "mode": "6ch", "address": 1 + 6 * (i - 1)} for i in (1, 2)])
        self.store.save_scenes({
            "rouge": Scene("rouge", "Rouge", 0.0, {"p1": red(), "p2": red()}),
            "bleu": Scene("bleu", "Bleu", 0.0, {"p1": FixtureState(rgb=(0, 0, 1), intensity=1.0)}),
            "strobe": Scene("strobe", "Strobe", 0.0, {"p1": FixtureState(rgb=(1, 1, 1), intensity=1.0,
                                                                         strobe=1.0)}),
        })
        self.store.save_sequences({"duo": Sequence("duo", "Duo", [Step("rouge"), Step("bleu")])})
        self.store.save_settings(Settings(default_fade=0.0, blackout_fade=0.0, flash_fade=0.0,
                                          pedals=[PedalAction("scene", "rouge"), PedalAction("scene", "bleu"),
                                                  PedalAction("sequence", "duo"), PedalAction("flash", "strobe"),
                                                  PedalAction("next"), PedalAction("prev")]))
        self.engine, self.settings = self.store.build_engine()
        self.controller = Controller(self.engine, self.store, self.settings, EventBus(), save_delay=0.0)
        self.server = make_server(self.controller, "127.0.0.1", 0, self.static)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()

    def req(self, method, path, body=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            payload = raw if raw is not None else (None if body is None else json.dumps(body))
            conn.request(method, path, payload, {"Content-Type": "application/json"})
            r = conn.getresponse()
            data = r.read()
            try:
                return r.status, json.loads(data)
            except ValueError:
                return r.status, data
        finally:
            conn.close()


class ApiTests(ServerCase):
    def test_state_dump(self):
        status, st = self.req("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual([f["id"] for f in st["fixtures"]], ["p1", "p2"])
        self.assertIn("strobe", st["fixtures"][0]["roles"])
        self.assertEqual([s["id"] for s in st["scenes"]], ["rouge", "bleu", "strobe"])
        self.assertTrue(st["status"]["blackout"])  # démarrage en blackout
        self.assertEqual(len(st["settings"]["pedals"]), 6)

    def test_recall_and_blackout_drive_dmx(self):
        self.assertEqual(self.engine.frame(), bytes(512))
        status, _ = self.req("POST", "/api/scenes/rouge/recall")
        self.assertEqual(status, 200)
        self.assertEqual(self.engine.frame(), bytes(512))  # toujours en blackout
        status, out = self.req("POST", "/api/blackout", {"on": False})
        self.assertEqual((status, out["blackout"]), (200, False))
        self.assertEqual(self.engine.frame()[0:5], bytes([255, 0, 0, 0, 255]))
        _, out = self.req("POST", "/api/blackout")  # bascule
        self.assertTrue(out["blackout"])
        self.assertEqual(self.engine.frame(), bytes(512))

    def test_unknown_things_are_404(self):
        self.assertEqual(self.req("POST", "/api/scenes/zzz/recall")[0], 404)
        self.assertEqual(self.req("POST", "/api/flash/zzz", {"down": True})[0], 404)
        self.assertEqual(self.req("POST", "/api/fixtures/zzz/state", {"white": 1})[0], 404)
        self.assertEqual(self.req("GET", "/api/nope")[0], 404)
        self.assertEqual(self.req("DELETE", "/api/scenes/zzz")[0], 404)

    def test_bad_requests_are_400(self):
        self.assertEqual(self.req("POST", "/api/blackout", raw="{pas du json")[0], 400)
        self.assertEqual(self.req("POST", "/api/blackout", raw="[1]")[0], 400)
        self.assertEqual(self.req("POST", "/api/blackout", {"on": "oui"})[0], 400)
        self.assertEqual(self.req("POST", "/api/fixtures/p1/state", {"intensity": 3})[0], 400)
        self.assertEqual(self.req("POST", "/api/fixtures/p1/state", {"couleur": 1})[0], 400)
        self.assertEqual(self.req("POST", "/api/pedal/9", {"down": True})[0], 400)

    def test_fixture_state_merges_fields(self):
        self.req("POST", "/api/blackout", {"on": False})
        self.req("POST", "/api/scenes/rouge/recall")
        status, st = self.req("POST", "/api/fixtures/p1/state", {"white": 0.5, "rgb": [0, 1, 0]})
        self.assertEqual(status, 200)
        self.assertEqual(st["intensity"], 1.0)  # champ non fourni : conservé
        self.assertEqual(self.engine.frame()[0:4], bytes([0, 255, 0, 128]))
        self.assertEqual(self.engine.frame()[6:9], bytes([255, 0, 0]))  # l'autre projecteur ne bouge pas

    def test_batch_fixture_state(self):
        self.req("POST", "/api/blackout", {"on": False})
        status, out = self.req("POST", "/api/fixtures/state",
                               {"ids": ["p1", "p2"], "fields": {"rgb": [0, 0, 1], "intensity": 0.5}})
        self.assertEqual(status, 200)
        self.assertEqual(set(out), {"p1", "p2"})
        f = self.engine.frame()
        self.assertEqual(f[0:3], bytes([0, 0, 255]))
        self.assertEqual(f[6:9], bytes([0, 0, 255]))
        self.assertEqual(f[4], 128)  # dimmer à 50 %

    def test_batch_is_all_or_nothing(self):
        self.req("POST", "/api/blackout", {"on": False})
        self.req("POST", "/api/scenes/rouge/recall")
        self.assertEqual(self.req("POST", "/api/fixtures/state",
                                  {"ids": ["p1", "fantome"], "fields": {"rgb": [0, 1, 0]}})[0], 404)
        self.assertEqual(self.engine.frame()[0:3], bytes([255, 0, 0]))  # p1 n'a pas bougé
        self.assertEqual(self.req("POST", "/api/fixtures/state",
                                  {"ids": ["p1"], "fields": {"intensity": 9}})[0], 400)
        self.assertEqual(self.req("POST", "/api/fixtures/state", {"ids": "p1", "fields": {}})[0], 400)

    def test_flash_endpoint(self):
        self.req("POST", "/api/blackout", {"on": False})
        _, st = self.req("POST", "/api/flash/strobe", {"down": True})
        self.assertEqual(st["flash"], "strobe")
        self.assertEqual(self.engine.frame()[5], 255)
        _, st = self.req("POST", "/api/flash/strobe", {"down": False})
        self.assertIsNone(st["flash"])
        self.assertEqual(self.engine.frame()[5], 0)

    def test_sequence_endpoints(self):
        self.req("POST", "/api/blackout", {"on": False})
        _, out = self.req("POST", "/api/sequences/duo/toggle")
        self.assertTrue(out["running"])
        _, st = self.req("POST", "/api/sequence/next")
        self.assertEqual(st["active"], "bleu")
        _, st = self.req("POST", "/api/sequence/stop")
        self.assertIsNone(st["sequence"])
        self.assertEqual(self.req("POST", "/api/sequences/zzz/toggle")[0], 404)


class PedalTests(ServerCase):
    def press(self, n, down=True):
        return self.req("POST", f"/api/pedal/{n}", {"down": down})[1]

    def test_scene_pedals_and_leds(self):
        self.req("POST", "/api/blackout", {"on": False})
        st = self.press(2)
        self.assertEqual(st["active"], "bleu")
        self.assertEqual(st["leds"]["slots"], [False, True, False, False, False, False])
        st = self.press(1)
        self.assertEqual(st["leds"]["slots"][0], True)
        self.assertEqual(st["leds"]["slots"][1], False)

    def test_release_of_scene_pedal_does_nothing(self):
        self.req("POST", "/api/blackout", {"on": False})
        self.press(2)
        self.press(1, down=False)
        self.assertEqual(self.engine.status()["active"], "bleu")

    def test_blackout_pedal_keeps_active_scene_led(self):
        self.req("POST", "/api/blackout", {"on": False})
        self.press(1)
        st = self.press(7)  # blackout
        self.assertTrue(st["leds"]["blackout"])
        self.assertTrue(st["leds"]["slots"][0])  # la LED de la scène active reste allumée
        self.assertEqual(self.engine.frame(), bytes(512))
        st = self.press(7)
        self.assertFalse(st["leds"]["blackout"])
        self.assertEqual(self.engine.frame()[0], 255)

    def test_first_blackout_press_restores_first_scene(self):
        st = self.press(7)  # démarrage en blackout, aucune scène mémorisée
        self.assertFalse(st["blackout"])
        self.assertEqual(st["active"], "rouge")

    def test_flash_pedal_follows_foot(self):
        self.req("POST", "/api/blackout", {"on": False})
        self.press(1)
        st = self.press(4, True)
        self.assertTrue(st["leds"]["slots"][3])
        self.assertEqual(self.engine.frame()[5], 255)
        st = self.press(4, False)
        self.assertFalse(st["leds"]["slots"][3])
        self.assertEqual(self.engine.frame()[5], 0)
        self.assertEqual(st["active"], "rouge")

    def test_sequence_pedals(self):
        self.req("POST", "/api/blackout", {"on": False})
        st = self.press(3)  # lance « duo »
        self.assertTrue(st["leds"]["slots"][2])
        self.assertEqual(st["active"], "rouge")
        # « rouge » est la scène de la pédale 1 et la 1re étape de la séquence : sa LED reste éteinte
        self.assertFalse(st["leds"]["slots"][0])
        st = self.press(5)  # étape suivante
        self.assertEqual(st["active"], "bleu")
        st = self.press(6)  # étape précédente
        self.assertEqual(st["active"], "rouge")
        self.assertFalse(st["leds"]["slots"][1])  # idem pour « bleu » (pédale 2), étape en cours
        st = self.press(3)  # second appui : arrête
        self.assertFalse(st["leds"]["slots"][2])
        self.assertIsNone(st["sequence"])
        self.assertTrue(st["leds"]["slots"][0])  # la dernière scène reste active : sa pédale s'allume


class EditingTests(ServerCase):
    def test_capture_scene_creates_and_persists(self):
        self.req("POST", "/api/blackout", {"on": False})
        self.req("POST", "/api/scenes/rouge/recall")
        self.req("POST", "/api/fixtures/p2/state", {"rgb": [0, 0, 1]})
        status, scene = self.req("POST", "/api/scenes", {"name": "Mélange été", "capture": "all"})
        self.assertEqual(status, 201)
        self.assertEqual(scene["id"], "melange-ete")
        self.assertEqual(scene["states"]["p2"]["rgb"], [0, 0, 1])
        self.assertIn("melange-ete", self.store.load_scenes())
        status, scene2 = self.req("POST", "/api/scenes", {"name": "Mélange été", "capture": ["p1"]})
        self.assertEqual(scene2["id"], "melange-ete-2")
        self.assertEqual(list(scene2["states"]), ["p1"])

    def test_capture_excludes_blackout_and_flash(self):
        self.req("POST", "/api/scenes/rouge/recall")  # en blackout : l'affichage est noir
        _, scene = self.req("POST", "/api/scenes", {"name": "Capture", "capture": "all"})
        self.assertEqual(scene["states"]["p1"]["intensity"], 1.0)

    def test_scene_validation(self):
        self.assertEqual(self.req("POST", "/api/scenes", {"name": "X"})[0], 400)
        self.assertEqual(self.req("POST", "/api/scenes", {"capture": "all"})[0], 400)
        self.assertEqual(self.req("POST", "/api/scenes",
                                  {"name": "X", "states": {"fantome": {"intensity": 1}}})[0], 400)
        self.assertEqual(self.req("PUT", "/api/scenes/zzz", {"name": "X", "capture": "all"})[0], 404)

    def test_put_replaces_and_keeps_fade(self):
        status, scene = self.req("PUT", "/api/scenes/rouge", {"name": "Rouge vif", "fade_s": 2.5,
                                                              "states": {"p1": {"intensity": 1.0,
                                                                                "rgb": [1, 0, 0]}}})
        self.assertEqual((status, scene["name"], scene["fade_s"]), (200, "Rouge vif", 2.5))
        self.assertEqual(list(self.engine.scenes["rouge"].states), ["p1"])

    def test_delete_scene_conflicts(self):
        status, out = self.req("DELETE", "/api/scenes/strobe")  # pédale 4 (flash)
        self.assertEqual(status, 409)
        self.assertIn("pédale", out["error"])
        status, out = self.req("POST", "/api/scenes", {"name": "Neutre", "capture": "all"})
        self.assertEqual(self.req("DELETE", "/api/scenes/neutre")[0], 200)
        self.assertNotIn("neutre", self.store.load_scenes())
        # utilisée par une séquence (et plus par une pédale)
        self.req("PUT", "/api/settings", {"pedals": []})
        status, out = self.req("DELETE", "/api/scenes/bleu")
        self.assertEqual(status, 409)
        self.assertIn("séquences", out["error"])

    def test_sequence_crud(self):
        status, seq = self.req("POST", "/api/sequences", {
            "name": "Refrain", "loop": True,
            "steps": [{"scene": "rouge", "fade_s": 0.5, "hold_s": 2}, {"scene": "bleu", "hold_s": 2}]})
        self.assertEqual((status, seq["id"], seq["loop"]), (201, "refrain", True))
        self.assertIn("refrain", self.store.load_sequences())
        self.assertEqual(self.req("POST", "/api/sequences",
                                  {"name": "Mauvaise", "steps": [{"scene": "zzz"}]})[0], 400)
        self.assertEqual(self.req("POST", "/api/sequences", {"name": "Vide", "steps": []})[0], 400)
        self.assertEqual(self.req("DELETE", "/api/sequences/refrain")[0], 200)
        self.assertEqual(self.req("DELETE", "/api/sequences/duo")[0], 409)  # pédale 3

    def test_settings_update_applies_and_persists(self):
        status, s = self.req("PUT", "/api/settings", {"master": 0.5, "default_fade": 2.0})
        self.assertEqual((status, s["master"]), (200, 0.5))
        self.assertEqual(self.engine.master, 0.5)
        self.assertEqual(self.engine.default_fade, 2.0)
        self.assertEqual(self.store.load_settings().master, 0.5)
        self.assertEqual(self.req("PUT", "/api/settings", {"master": 4})[0], 400)
        self.assertEqual(self.req("PUT", "/api/settings",
                                  {"pedals": [{"type": "scene", "target": "fantome"}]})[0], 400)
        self.assertEqual(self.engine.master, 0.5)  # une mise à jour refusée ne change rien

    def test_last_scene_is_persisted(self):
        self.req("POST", "/api/scenes/bleu/recall")
        self.assertEqual(self.store.load_settings().last_scene, "bleu")  # save_delay = 0 ici


class StaticAndSseTests(ServerCase):
    def test_static_index_and_traversal(self):
        status, body = self.req("GET", "/")
        self.assertEqual((status, body), (200, b"<h1>ok</h1>"))
        self.assertEqual(self.req("GET", "/index.html")[0], 200)
        self.assertEqual(self.req("GET", "/../secret.txt")[0], 404)
        self.assertEqual(self.req("GET", "/%2e%2e/secret.txt")[0], 404)
        self.assertEqual(self.req("GET", "/absent.js")[0], 404)

    def test_sse_sends_initial_status_then_changes(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/events")
        r = conn.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn("text/event-stream", r.getheader("Content-Type"))

        def read_event():
            event, data = None, None
            while True:
                line = r.fp.readline().decode("utf-8").rstrip("\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:])
                elif line == "" and event:
                    return event, data

        try:
            event, data = read_event()
            self.assertEqual(event, "status")
            self.assertTrue(data["blackout"])
            self.req("POST", "/api/blackout", {"on": False})
            event, data = read_event()
            self.assertEqual((event, data["blackout"]), ("status", False))
            self.req("POST", "/api/scenes", {"name": "Nouvelle", "capture": "all"})
            self.assertEqual(read_event()[0], "config")  # l'état ne change pas : seul « config » part
        finally:
            conn.close()


class WebFilesTests(unittest.TestCase):
    """L'interface livrée : la page et les fichiers qu'elle référence existent."""

    WEB = os.path.join(os.path.dirname(__file__), "..", "stage_control", "web")

    def test_index_references_existing_files(self):
        import re
        with open(os.path.join(self.WEB, "index.html"), encoding="utf-8") as f:
            html = f.read()
        refs = re.findall(r'(?:src|href)="([^"#:]+)"', html)
        self.assertIn("app.js", refs)
        self.assertIn("style.css", refs)
        for ref in refs:
            self.assertTrue(os.path.isfile(os.path.join(self.WEB, ref)), ref)

    def test_interface_uses_no_external_resource(self):
        # le boîtier n'a pas d'internet : aucune ressource externe (CDN, polices...)
        for fn in ("index.html", "app.js", "style.css"):
            with open(os.path.join(self.WEB, fn), encoding="utf-8") as f:
                text = f.read()
            self.assertNotRegex(text, r"https?://", fn)


if __name__ == "__main__":
    unittest.main()
