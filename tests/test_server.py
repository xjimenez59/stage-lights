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


class ProfileManagementTests(ServerCase):
    def raw(self):
        with open(os.path.join(REPO_PROFILES, PROFILE_KEY + ".json"), encoding="utf-8") as f:
            return json.load(f)

    def download(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            conn.close()

    def check(self, key, profile):
        return self.req("POST", f"/api/profiles/{key}/check", {"profile": profile})

    def test_download_one_model_is_the_file_itself(self):
        status, headers, body = self.download(f"/api/profiles/{PROFILE_KEY}/download")
        self.assertEqual(status, 200)
        self.assertIn(f'filename="{PROFILE_KEY}.json"', headers["Content-Disposition"])
        with open(os.path.join(REPO_PROFILES, PROFILE_KEY + ".json"), "rb") as f:
            self.assertEqual(body, f.read())

    def test_download_all_is_a_zip_with_one_json_per_model(self):
        import io
        import zipfile
        status, headers, body = self.download("/api/profiles/download-all")
        self.assertEqual((status, headers["Content-Type"]), (200, "application/zip"))
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            self.assertEqual(z.namelist(), [PROFILE_KEY + ".json"])
            self.assertEqual(json.loads(z.read(PROFILE_KEY + ".json"))["name"], self.raw()["name"])

    def test_download_unknown_or_dangerous_keys(self):
        for path in ("/api/profiles/inconnu/download", "/api/profiles/..%2Fsecret/download",
                     "/api/profiles/%2e%2e/download", "/api/profiles/A.B/download"):
            self.assertNotEqual(self.download(path)[0], 200, path)

    def test_raw_text_and_origin(self):
        status, out = self.req("GET", f"/api/profiles/{PROFILE_KEY}/raw")
        self.assertEqual((status, out["origin"]), (200, "bundled"))
        self.assertEqual(json.loads(out["text"])["name"], self.raw()["name"])
        _, st = self.req("GET", "/api/state")
        self.assertEqual(st["profiles"][PROFILE_KEY]["origin"], "bundled")

    def test_check_new_valid_model_changes_nothing(self):
        prof = {"name": "Barre LED", "manufacturer": "Test",
                "modes": {"3ch": {"channels": [{"role": "red"}, {"role": "green"}, {"role": "blue"}]}}}
        status, rep = self.check("barre-led", prof)
        self.assertEqual((status, rep["ok"], rep["exists"]), (200, True, False))
        self.assertEqual(rep["profile"]["modes"]["3ch"]["size"], 3)
        self.assertEqual(rep["impacted"], [])
        self.assertNotIn("barre-led", self.req("GET", "/api/state")[1]["profiles"])
        self.assertFalse(os.path.exists(os.path.join(self.store.data_dir, "profiles", "barre-led.json")))

    def test_check_reports_errors_without_failing_the_request(self):
        for bad in ({"name": "X", "modes": {"m": {"channels": [{"role": "bogus"}]}}},
                    {"name": "X", "modes": {}}, {"modes": {"m": {"channels": [{"role": "red"}]}}},
                    {"name": "X", "modes": {"m": {"channels": [{"role": "red", "default": 999}]}}},
                    "pas un objet", None, [1]):
            status, rep = self.check("essai", bad)
            self.assertEqual((status, rep["ok"]), (200, False), str(bad))
            self.assertTrue(rep["errors"])
        self.assertEqual(self.check("Pas%20Valide", {"name": "X"})[0], 400)
        self.assertEqual(self.check("MAJUSCULES", {"name": "X"})[0], 400)
        self.assertEqual(self.check("a" * 61, {"name": "X"})[0], 400)

    def test_check_update_lists_changes(self):
        prof = self.raw()
        del prof["modes"]["8ch"]
        prof["modes"]["5ch"] = {"channels": [{"role": "red"}] * 1 + [{"role": "green"}, {"role": "blue"},
                                                                    {"role": "white"}, {"role": "intensity"}]}
        _, rep = self.check(PROFILE_KEY, prof)
        self.assertTrue(rep["ok"], rep)
        self.assertTrue(rep["exists"])
        self.assertIn("mode 8ch supprimé", rep["changes"])
        self.assertIn("mode 5ch ajouté (5 canaux)", rep["changes"])
        self.assertEqual(sorted(rep["impacted"]), ["Spot 1", "Spot 2"])

    def test_check_blocks_a_removed_mode_in_use(self):
        prof = self.raw()
        del prof["modes"]["6ch"]  # p1 et p2 sont en 6ch
        _, rep = self.check(PROFILE_KEY, prof)
        self.assertFalse(rep["ok"])
        self.assertIn("absent du nouveau modèle", rep["errors"][0])

    def test_check_blocks_a_resize_that_breaks_the_plan(self):
        prof = self.raw()
        prof["modes"]["6ch"]["channels"].append({"role": "other"})  # 7 canaux : p1 chevaucherait p2
        _, rep = self.check(PROFILE_KEY, prof)
        self.assertFalse(rep["ok"])
        self.assertIn("plan de feu", rep["errors"][0])

    def test_identical_model_warns(self):
        _, rep = self.check(PROFILE_KEY, self.raw())
        self.assertTrue(rep["ok"])
        self.assertTrue(any("identique" in w for w in rep["warnings"]))

    def test_save_new_model_then_use_it(self):
        prof = {"name": "Barre LED", "modes": {"3ch": {"channels": [
            {"role": "red"}, {"role": "green"}, {"role": "blue"}]}}}
        status, rep = self.req("PUT", "/api/profiles/barre-led", {"profile": prof})
        self.assertEqual((status, rep["ok"]), (200, True))
        self.assertEqual(Store(self.store.data_dir, REPO_PROFILES).load_profiles()["barre-led"].name, "Barre LED")
        _, st = self.req("GET", "/api/state")
        self.assertEqual(st["profiles"]["barre-led"]["origin"], "custom")
        status, f = self.req("POST", "/api/fixtures", {"name": "Barre", "profile": "barre-led", "mode": "3ch"})
        self.assertEqual((status, f["address"]), (201, 13))

    def test_save_update_replaces_the_bundled_model_and_applies_to_the_plan(self):
        self.req("POST", "/api/blackout", {"on": False})
        self.req("POST", "/api/scenes/rouge/recall")
        before = self.engine.frame()
        prof = self.raw()
        prof["name"] = "PARty Spot (corrigé)"
        status, rep = self.req("PUT", f"/api/profiles/{PROFILE_KEY}", {"profile": prof})
        self.assertEqual((status, rep["ok"]), (200, True))
        self.assertEqual(self.engine.plan.get("p1").profile.name, "PARty Spot (corrigé)")
        self.assertEqual(self.engine.frame(), before)  # l'éclairage ne bouge pas
        self.assertEqual(self.req("GET", "/api/state")[1]["fixtures"][0]["profile"], "PARty Spot (corrigé)")
        self.assertEqual(self.req("GET", f"/api/profiles/{PROFILE_KEY}/raw")[1]["origin"], "custom")
        # le fichier du dépôt n'a pas été touché ; une 2e mise à jour garde une copie de la 1re
        self.assertEqual(self.raw()["name"], "LED PARty Spot Silent RGB/WW")
        prof["name"] = "PARty Spot v3"
        self.req("PUT", f"/api/profiles/{PROFILE_KEY}", {"profile": prof})
        custom = os.path.join(self.store.data_dir, "profiles", PROFILE_KEY + ".json")
        with open(custom + ".bak", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["name"], "PARty Spot (corrigé)")

    def make_custom(self, key="barre-led"):
        prof = {"name": "Barre LED", "modes": {"3ch": {"channels": [
            {"role": "red"}, {"role": "green"}, {"role": "blue"}]}}}
        self.assertEqual(self.req("PUT", f"/api/profiles/{key}", {"profile": prof})[0], 200)
        return prof

    def test_delete_unused_custom_model(self):
        self.make_custom()
        path = os.path.join(self.store.data_dir, "profiles", "barre-led.json")
        status, out = self.req("DELETE", "/api/profiles/barre-led")
        self.assertEqual((status, out), (200, {"key": "barre-led", "reverted": False}))
        self.assertNotIn("barre-led", self.req("GET", "/api/state")[1]["profiles"])
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(path + ".bak"))  # on garde une copie du fichier supprimé
        self.assertNotIn("barre-led", Store(self.store.data_dir, REPO_PROFILES).load_profiles())

    def test_delete_refused_while_a_fixture_uses_the_model(self):
        self.make_custom()
        self.req("POST", "/api/fixtures", {"name": "Barre", "profile": "barre-led", "mode": "3ch"})
        status, out = self.req("DELETE", "/api/profiles/barre-led")
        self.assertEqual(status, 409)
        self.assertIn("Barre", out["error"])
        self.assertIn("barre-led", self.req("GET", "/api/state")[1]["profiles"])
        self.req("DELETE", "/api/fixtures/barre")  # une fois le projecteur retiré, la suppression passe
        self.assertEqual(self.req("DELETE", "/api/profiles/barre-led")[0], 200)

    def test_delete_an_override_goes_back_to_the_bundled_model(self):
        prof = self.raw()
        prof["name"] = "PARty Spot (corrigé)"
        self.req("PUT", f"/api/profiles/{PROFILE_KEY}", {"profile": prof})
        st = self.req("GET", "/api/state")[1]
        self.assertTrue(st["profiles"][PROFILE_KEY]["has_bundled"])
        self.req("POST", "/api/blackout", {"on": False})
        self.req("POST", "/api/scenes/rouge/recall")
        before = self.engine.frame()
        status, out = self.req("DELETE", f"/api/profiles/{PROFILE_KEY}")
        self.assertEqual((status, out["reverted"]), (200, True))
        st = self.req("GET", "/api/state")[1]
        self.assertEqual((st["profiles"][PROFILE_KEY]["origin"], st["profiles"][PROFILE_KEY]["name"]),
                         ("bundled", "LED PARty Spot Silent RGB/WW"))
        self.assertEqual(self.engine.plan.get("p1").profile.name, "LED PARty Spot Silent RGB/WW")
        self.assertEqual(self.engine.frame(), before)

    def test_revert_refused_if_the_bundled_model_no_longer_fits_the_plan(self):
        prof = self.raw()
        prof["modes"]["5ch"] = {"channels": [{"role": "red"}, {"role": "green"}, {"role": "blue"},
                                            {"role": "white"}, {"role": "intensity"}]}
        self.req("PUT", f"/api/profiles/{PROFILE_KEY}", {"profile": prof})
        self.assertEqual(self.req("PUT", "/api/fixtures/p1", {"mode": "5ch"})[0], 200)
        status, out = self.req("DELETE", f"/api/profiles/{PROFILE_KEY}")
        self.assertEqual(status, 409)
        self.assertIn("absent du nouveau modèle", out["error"])
        self.assertEqual(self.req("GET", "/api/state")[1]["profiles"][PROFILE_KEY]["origin"], "custom")

    def test_delete_refuses_bundled_and_unknown_models(self):
        self.assertEqual(self.req("DELETE", f"/api/profiles/{PROFILE_KEY}")[0], 409)  # fourni, non personnalisé
        self.assertEqual(self.req("DELETE", "/api/profiles/inconnu")[0], 404)
        self.assertEqual(self.req("DELETE", "/api/profiles/%2e%2e")[0], 404)
        self.assertTrue(os.path.exists(os.path.join(REPO_PROFILES, PROFILE_KEY + ".json")))

    def test_save_refused_when_check_fails(self):
        prof = self.raw()
        del prof["modes"]["6ch"]
        status, out = self.req("PUT", f"/api/profiles/{PROFILE_KEY}", {"profile": prof})
        self.assertEqual(status, 400)
        self.assertIn("absent du nouveau modèle", out["error"])
        self.assertFalse(os.path.exists(os.path.join(self.store.data_dir, "profiles", PROFILE_KEY + ".json")))
        self.assertEqual(self.req("PUT", "/api/profiles/Mauvais", {"profile": self.raw()})[0], 400)
        self.assertEqual(self.req("PUT", "/api/profiles/ok", {"profile": "texte"})[0], 400)


class SceneOrderAndStatesTests(ServerCase):
    def test_reorder_scenes_persists_and_drives_fallback(self):
        status, out = self.req("PUT", "/api/scene-order", {"ids": ["strobe", "bleu", "rouge"]})
        self.assertEqual((status, out["ids"]), (200, ["strobe", "bleu", "rouge"]))
        self.assertEqual(list(self.store.load_scenes()), ["strobe", "bleu", "rouge"])
        self.assertEqual([s["id"] for s in self.req("GET", "/api/state")[1]["scenes"]], ["strobe", "bleu", "rouge"])
        # la première scène sert de repli au premier appui sur le blackout
        _, st = self.req("POST", "/api/blackout", {"on": False})
        self.assertEqual(self.engine.status()["active"], "strobe")

    def test_reorder_validation(self):
        for bad in (["rouge", "bleu"], ["rouge", "bleu", "strobe", "x"], ["rouge", "rouge", "bleu"], "rouge"):
            self.assertEqual(self.req("PUT", "/api/scene-order", {"ids": bad})[0], 400, str(bad))
        self.assertEqual(list(self.engine.scenes), ["rouge", "bleu", "strobe"])  # inchangé

    def test_apply_states_sets_each_fixture(self):
        self.req("POST", "/api/blackout", {"on": False})
        status, out = self.req("POST", "/api/states", {"states": {
            "p1": {"rgb": [0, 0, 1], "intensity": 1.0}, "p2": {"rgb": [0, 1, 0], "intensity": 0.5}}})
        self.assertEqual(status, 200)
        self.assertEqual(out["p2"]["intensity"], 0.5)
        f = self.engine.frame()
        self.assertEqual(f[0:3], bytes([0, 0, 255]))
        self.assertEqual(f[6:9], bytes([0, 255, 0]))
        self.assertEqual(f[10], 128)

    def test_apply_states_is_all_or_nothing(self):
        self.req("POST", "/api/blackout", {"on": False})
        self.req("POST", "/api/scenes/rouge/recall")
        self.assertEqual(self.req("POST", "/api/states", {"states": {
            "p1": {"rgb": [0, 0, 1], "intensity": 1.0}, "fantome": {"intensity": 1.0}}})[0], 404)
        self.assertEqual(self.req("POST", "/api/states", {"states": {
            "p1": {"rgb": [0, 0, 1], "intensity": 9}}})[0], 400)
        self.assertEqual(self.req("POST", "/api/states", {"states": [1]})[0], 400)
        self.assertEqual(self.engine.frame()[0:3], bytes([255, 0, 0]))  # rien n'a bougé


class FixtureEditingTests(ServerCase):
    def test_state_lists_models_and_next_free_address(self):
        _, st = self.req("GET", "/api/state")
        model = st["profiles"][PROFILE_KEY]
        self.assertEqual(set(model["modes"]), {"4ch", "6ch", "8ch"})
        self.assertEqual(model["modes"]["6ch"]["size"], 6)
        self.assertEqual(model["modes"]["6ch"]["next_address"], 13)  # p1 = 1-6, p2 = 7-12
        roles = [c["role"] for c in model["modes"]["6ch"]["channels"]]
        self.assertEqual(roles, ["red", "green", "blue", "white", "intensity", "strobe"])
        strobe = model["modes"]["6ch"]["channels"][5]
        self.assertEqual((strobe["min"], strobe["max"]), (11, 255))
        self.assertEqual(st["dmx"], {"channels": 12, "size": 512})
        f = st["fixtures"][0]
        self.assertEqual((f["profile_key"], f["end"], f["channels"]), (PROFILE_KEY, 6, 6))

    def test_add_fixture_takes_the_next_free_address_and_persists(self):
        status, f = self.req("POST", "/api/fixtures", {"name": "Contre", "profile": PROFILE_KEY, "mode": "6ch"})
        self.assertEqual((status, f["id"], f["address"], f["end"]), (201, "contre", 13, 18))
        self.assertEqual([x.address for x in self.store.load_plan().fixtures], [1, 7, 13])
        self.assertEqual(self.engine.plan.channel_count(), 18)
        self.assertEqual(self.req("GET", "/api/state")[1]["dmx"]["channels"], 18)

    def test_new_fixture_is_dark_until_a_scene_lights_it(self):
        self.req("POST", "/api/blackout", {"on": False})
        self.req("POST", "/api/scenes/rouge/recall")
        self.req("POST", "/api/fixtures", {"name": "Contre", "profile": PROFILE_KEY, "mode": "6ch"})
        f = self.engine.frame()
        self.assertEqual(f[0:3], bytes([255, 0, 0]))  # les projecteurs existants continuent
        self.assertEqual(f[12:18], bytes(6))  # le nouveau reste à zéro
        self.req("POST", "/api/fixtures/contre/state", {"rgb": [0, 0, 1], "intensity": 1.0})
        self.assertEqual(self.engine.frame()[12:15], bytes([0, 0, 255]))

    def test_explicit_address_and_overlap_is_refused(self):
        status, f = self.req("POST", "/api/fixtures", {"name": "Fond", "profile": PROFILE_KEY, "mode": "4ch",
                                                       "address": 100})
        self.assertEqual((status, f["address"], f["end"]), (201, 100, 103))
        status, out = self.req("POST", "/api/fixtures", {"name": "Gêneur", "profile": PROFILE_KEY, "mode": "6ch",
                                                         "address": 5})
        self.assertEqual(status, 400)
        self.assertIn("chevauchement", out["error"])
        self.assertEqual(len(self.store.load_plan().fixtures), 3)  # rien n'a été enregistré en trop
        self.assertEqual(self.req("POST", "/api/fixtures", {"name": "Hors", "profile": PROFILE_KEY, "mode": "6ch",
                                                            "address": 510})[0], 400)

    def test_validation(self):
        post = lambda body: self.req("POST", "/api/fixtures", body)[0]  # noqa: E731
        self.assertEqual(post({"profile": PROFILE_KEY, "mode": "6ch"}), 400)  # nom manquant
        self.assertEqual(post({"name": "X", "profile": "inconnu", "mode": "6ch"}), 400)
        self.assertEqual(post({"name": "X", "profile": PROFILE_KEY, "mode": "12ch"}), 400)
        self.assertEqual(post({"name": "X", "profile": PROFILE_KEY, "mode": "6ch", "address": "abc"}), 400)
        self.assertEqual(self.req("PUT", "/api/fixtures/fantome", {"name": "X"})[0], 404)
        self.assertEqual(self.req("DELETE", "/api/fixtures/fantome")[0], 404)

    def test_same_name_gets_a_distinct_id_and_state_is_reserved(self):
        _, a = self.req("POST", "/api/fixtures", {"name": "Spot", "profile": PROFILE_KEY, "mode": "4ch"})
        _, b = self.req("POST", "/api/fixtures", {"name": "Spot", "profile": PROFILE_KEY, "mode": "4ch"})
        _, c = self.req("POST", "/api/fixtures", {"name": "State", "profile": PROFILE_KEY, "mode": "4ch"})
        self.assertEqual((a["id"], b["id"], c["id"]), ("spot", "spot-2", "state-2"))

    def test_move_and_change_mode(self):
        status, f = self.req("PUT", "/api/fixtures/p2", {"address": 20, "mode": "4ch", "name": "Jardin"})
        self.assertEqual((status, f["address"], f["end"], f["name"]), (200, 20, 23, "Jardin"))
        self.assertEqual(self.engine.plan.get("p2").mode_name, "4ch")
        self.assertEqual(self.store.load_plan().get("p2").address, 20)
        # un projecteur peut se déplacer sur ses propres canaux sans « chevaucher » avec lui-même
        self.assertEqual(self.req("PUT", "/api/fixtures/p1", {"address": 3})[0], 200)
        # mais pas sur ceux d'un autre
        self.assertEqual(self.req("PUT", "/api/fixtures/p1", {"address": 18})[0], 400)

    def test_delete_keeps_scenes_and_others_running(self):
        self.req("POST", "/api/blackout", {"on": False})
        self.req("POST", "/api/scenes/rouge/recall")
        self.assertEqual(self.req("DELETE", "/api/fixtures/p1")[0], 200)
        self.assertEqual([f.id for f in self.engine.plan.fixtures], ["p2"])
        self.assertEqual(self.engine.frame()[6:9], bytes([255, 0, 0]))  # p2 ne bouge pas
        self.assertEqual(self.engine.frame()[0:6], bytes(6))
        self.assertIn("p1", self.store.load_scenes()["rouge"].states)  # la scène garde son état
        # le projecteur revient : il repart éteint, indépendamment de l'ancien état de la scène
        status, back = self.req("POST", "/api/fixtures",
                                {"name": "p1", "profile": PROFILE_KEY, "mode": "6ch", "address": 1})
        self.assertEqual(back["id"], "p1")  # même identifiant : les scènes le retrouvent
        self.assertEqual(self.engine.frame()[0:6], bytes(6))
        self.req("POST", "/api/scenes/rouge/recall")
        self.assertEqual(self.engine.frame()[0:3], bytes([255, 0, 0]))

    def test_output_loop_follows_the_plan(self):
        from stage_control.output import OutputLoop

        class Sink:
            def __init__(self):
                self.last = b""

            def send(self, data):
                self.last = data

        sink = Sink()
        loop = OutputLoop(self.engine, sink)
        loop.tick()
        self.assertEqual(len(sink.last), 12)
        self.req("POST", "/api/fixtures", {"name": "Contre", "profile": PROFILE_KEY, "mode": "6ch"})
        loop.tick()
        self.assertEqual(len(sink.last), 18)
        self.req("DELETE", "/api/fixtures/p1")
        self.req("DELETE", "/api/fixtures/p2")
        self.req("DELETE", "/api/fixtures/contre")
        loop.tick()
        self.assertEqual(len(sink.last), 2)  # plan vide : minimum Art-Net


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
