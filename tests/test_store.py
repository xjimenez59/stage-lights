import json
import os
import tempfile
import unittest

from stage_control.scene import FixtureState, Scene
from stage_control.sequence import Sequence, Step
from stage_control.store import (PEDAL_SLOTS, PedalAction, Settings, Store,
                                 read_json, write_json_atomic)

REPO_PROFILES = os.path.join(os.path.dirname(__file__), "..", "profiles")
PROFILE_KEY = "eurolite-party-spot-silent-rgbww"


class AtomicIoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "sub", "a.json")

    def test_creates_directories_and_no_temp_left(self):
        write_json_atomic(self.path, {"x": 1})
        self.assertEqual(read_json(self.path, None), {"x": 1})
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_second_write_keeps_previous_as_bak(self):
        write_json_atomic(self.path, {"v": 1})
        write_json_atomic(self.path, {"v": 2})
        self.assertEqual(read_json(self.path, None), {"v": 2})
        with open(self.path + ".bak", encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"v": 1})

    def test_missing_returns_default(self):
        self.assertEqual(read_json(self.path, {"d": 0}), {"d": 0})

    def test_corrupt_file_falls_back_to_bak(self):
        write_json_atomic(self.path, {"v": 1})
        write_json_atomic(self.path, {"v": 2})
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ pas du json")
        self.assertEqual(read_json(self.path, None), {"v": 1})

    def test_corrupt_without_bak_raises(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{")
        with self.assertRaises(ValueError):
            read_json(self.path, None)

    def test_unicode_preserved(self):
        write_json_atomic(self.path, {"nom": "Éclairage général"})
        self.assertEqual(read_json(self.path, None)["nom"], "Éclairage général")


class SettingsTests(unittest.TestCase):
    def test_defaults_have_six_empty_pedals(self):
        s = Settings()
        self.assertEqual(len(s.pedals), PEDAL_SLOTS)
        self.assertTrue(all(p.type == "none" for p in s.pedals))

    def test_roundtrip(self):
        s = Settings(master=0.8, last_scene="c", pedals=[PedalAction("scene", "c"), PedalAction("next")])
        s2 = Settings.from_dict(s.to_dict())
        self.assertEqual(s2.master, 0.8)
        self.assertEqual(s2.pedals[0], PedalAction("scene", "c"))
        self.assertEqual(s2.pedals[1].type, "next")
        self.assertEqual(len(s2.pedals), PEDAL_SLOTS)

    def test_validation(self):
        for bad in ({"master": 2}, {"default_fade": -1}, {"curve": "zigzag"}, {"rate_hz": 0}):
            with self.assertRaises(ValueError, msg=str(bad)):
                Settings.from_dict(bad)
        with self.assertRaises(ValueError):
            PedalAction("scene")  # cible manquante
        with self.assertRaises(ValueError):
            PedalAction("teleport")
        with self.assertRaises(ValueError):
            Settings(pedals=[PedalAction()] * 7)

    def test_unknown_keys_are_ignored(self):
        self.assertEqual(Settings.from_dict({"futur": 1}).master, 1.0)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name, REPO_PROFILES)

    def write_plan(self, n=4, mode="6ch", step=6):
        self.store.save_plan([{"id": f"p{i+1}", "name": f"Spot {i+1}", "profile": PROFILE_KEY,
                               "mode": mode, "address": 1 + step * i} for i in range(n)])

    def test_empty_data_dir_gives_empty_defaults(self):
        engine, settings = self.store.build_engine()
        self.assertEqual(engine.plan.fixtures, [])
        self.assertEqual(engine.scenes, {})
        self.assertEqual(settings.master, 1.0)

    def test_repo_profile_is_found(self):
        self.assertIn(PROFILE_KEY, self.store.load_profiles())

    def test_data_dir_profile_overrides_repo_profile(self):
        os.makedirs(os.path.join(self.tmp.name, "profiles"))
        custom = {"name": "Perso", "modes": {"x": {"channels": [{"role": "red"}]}}}
        with open(os.path.join(self.tmp.name, "profiles", PROFILE_KEY + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump(custom, f)
        self.assertEqual(self.store.load_profiles()[PROFILE_KEY].name, "Perso")

    def test_plan_roundtrip_and_validation(self):
        self.write_plan()
        plan = self.store.load_plan()
        self.assertEqual([f.address for f in plan.fixtures], [1, 7, 13, 19])
        self.assertEqual(plan.channel_count(), 24)

    def test_plan_with_overlap_is_rejected_on_load(self):
        self.write_plan(mode="6ch", step=4)
        with self.assertRaises(ValueError):
            self.store.load_plan()

    def test_plan_with_unknown_profile(self):
        self.store.save_plan([{"id": "a", "profile": "inexistant", "mode": "6ch", "address": 1}])
        with self.assertRaises(ValueError):
            self.store.load_plan()

    def test_scenes_and_sequences_roundtrip_keep_order(self):
        scenes = {sid: Scene(sid, sid.upper(), None, {"p1": FixtureState(rgb=(1, 0, 0), intensity=1.0)})
                  for sid in ("zz", "aa", "mm")}
        self.store.save_scenes(scenes)
        self.assertEqual(list(self.store.load_scenes()), ["zz", "aa", "mm"])
        seqs = {"s": Sequence("s", "S", [Step("zz", 1.0, 2.0), Step("aa")], loop=True)}
        self.store.save_sequences(seqs)
        self.assertEqual(self.store.load_sequences()["s"].steps, seqs["s"].steps)

    def test_build_engine_from_files(self):
        self.write_plan()
        scenes = {"rouge": Scene("rouge", "Rouge", 0.0, {
            f"p{i}": FixtureState(rgb=(1, 0, 0), intensity=1.0) for i in range(1, 5)})}
        self.store.save_scenes(scenes)
        self.store.save_settings(Settings(master=0.5, last_scene="rouge", default_fade=0.0,
                                          blackout_fade=0.0))
        engine, settings = self.store.build_engine()
        self.assertTrue(engine.blackout)  # démarrage en blackout
        self.assertEqual(engine.active, "rouge")
        self.assertEqual(engine.frame(), bytes(512))
        engine.toggle_blackout()
        frame = engine.frame()
        self.assertEqual(frame[0], 255)  # rouge sur le canal 1 (mode 6 canaux), non atténué
        self.assertEqual(frame[4], 128)  # dimmer (canal 5) = intensité × intensité générale (0,5)
        self.assertEqual(settings.master, 0.5)

    def test_unknown_last_scene_is_ignored(self):
        self.write_plan(1)
        self.store.save_settings(Settings(last_scene="disparue"))
        engine, _ = self.store.build_engine()
        self.assertIsNone(engine.active)


if __name__ == "__main__":
    unittest.main()
