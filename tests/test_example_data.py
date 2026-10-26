"""Garde-fou : les données d'exemple installées sur le Pi doivent rester valides."""

import os
import unittest

from stage_control.store import Store

ROOT = os.path.join(os.path.dirname(__file__), "..")


class ExampleDataTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(os.path.join(ROOT, "config", "data-example"), os.path.join(ROOT, "profiles"))

    def test_builds_an_engine_with_four_spots(self):
        engine, settings = self.store.build_engine()
        self.assertEqual([f.address for f in engine.plan.fixtures], [1, 7, 13, 19])
        self.assertEqual(engine.plan.channel_count(), 24)  # = --channels de spi-dmx.service
        self.assertEqual(len(engine.scenes), 6)

    def test_service_channel_count_matches_the_plan(self):
        with open(os.path.join(ROOT, "scripts", "spi-dmx.service"), encoding="utf-8") as f:
            self.assertIn("--channels 24", f.read())

    def test_pedals_point_to_existing_scenes(self):
        engine, settings = self.store.build_engine()
        for p in settings.pedals:
            self.assertIn(p.target, engine.scenes)

    def test_first_scene_renders_warm_white_on_all_spots(self):
        engine, _ = self.store.build_engine(clock=lambda: 0.0)
        engine.default_fade = engine.blackout_fade = 0.0
        engine.set_blackout(False)
        frame = engine.frame()
        for base in (0, 6, 12, 18):
            self.assertEqual(frame[base:base + 6], bytes([0, 0, 0, 255, 255, 0]))  # blanc chaud, dimmer, pas de strobe

    def test_strobe_scene_uses_the_strobe_channel(self):
        engine, _ = self.store.build_engine(clock=lambda: 0.0)
        engine.flash_fade = engine.blackout_fade = 0.0
        engine.set_blackout(False)
        engine.flash_on("stroboscope")
        self.assertGreater(engine.frame()[5], 11)


if __name__ == "__main__":
    unittest.main()
