import unittest

from stage_control.engine import Engine
from stage_control.plan import Fixture, Plan
from stage_control.profile import profile_from_dict
from stage_control.scene import FixtureState, Scene

RGB = profile_from_dict({
    "name": "rgb3", "modes": {"3ch": {"channels": [
        {"role": "red"}, {"role": "green"}, {"role": "blue"}]}}})


STROBE_PROFILE = profile_from_dict({
    "name": "strobe-test", "modes": {"m": {"channels": [
        {"role": "red"}, {"role": "green"}, {"role": "blue"}, {"role": "intensity"},
        {"role": "strobe", "default": 0, "min": 11, "max": 255}]}}})


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def full(r=1.0, g=1.0, b=1.0, i=1.0):
    return FixtureState(rgb=(r, g, b), intensity=i)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.plan = Plan([Fixture("a", "A", RGB, "3ch", 1), Fixture("b", "B", RGB, "3ch", 4)])
        self.scenes = {
            "red": Scene("red", "Rouge", None, {"a": full(1, 0, 0), "b": full(1, 0, 0)}),
            "blue_a": Scene("blue_a", "Bleu sur A", None, {"a": full(0, 0, 1)}),
            "off_a": Scene("off_a", "A éteint", None, {"a": full(0, 0, 0, 0.0)}),
            "instant": Scene("instant", "Sec", 0.0, {"a": full(0, 1, 0), "b": full(0, 1, 0)}),
            "slow": Scene("slow", "Lent", 4.0, {"a": full(0, 1, 0)}),
        }

    def engine(self, **kw):
        kw.setdefault("clock", self.clock)
        return Engine(self.plan, self.scenes, **kw)

    def advance(self, s):
        self.clock.t += s

    # -- démarrage et blackout --------------------------------------------

    def test_starts_in_blackout(self):
        e = self.engine(initial_scene="red")
        self.assertTrue(e.blackout)
        self.assertEqual(e.active, "red")
        self.assertEqual(e.frame(), bytes(512))

    def test_blackout_release_restores_initial_scene_with_fade(self):
        e = self.engine(initial_scene="red", blackout_fade=2.0)
        e.toggle_blackout()
        self.assertEqual(e.frame()[0:3], bytes([0, 0, 0]))
        self.advance(1.0)  # moitié du fondu : courbe en S à 0,5 = 0,5
        self.assertEqual(e.frame()[0], 128)
        self.advance(1.0)
        self.assertEqual(e.frame()[0:3], bytes([255, 0, 0]))
        self.assertFalse(e.blackout)

    def test_release_without_memorized_scene_uses_first(self):
        e = self.engine(blackout_fade=0.0, default_fade=0.0)
        e.toggle_blackout()
        self.assertEqual(e.active, "red")
        self.assertEqual(e.frame()[0], 255)

    def test_blackout_toggle_roundtrip_keeps_active_scene(self):
        e = self.engine(initial_scene="red", blackout_fade=1.0)
        e.set_blackout(False)
        self.advance(2)
        e.toggle_blackout()
        self.assertEqual(e.active, "red")
        self.advance(2)
        self.assertEqual(e.frame(), bytes(512))
        e.toggle_blackout()
        self.advance(2)
        self.assertEqual(e.frame()[0:3], bytes([255, 0, 0]))

    def test_recall_during_blackout_keeps_blackout(self):
        e = self.engine(initial_scene="red", blackout_fade=0.0, default_fade=0.0)
        e.set_blackout(False)
        e.toggle_blackout()
        e.recall("instant")
        self.assertEqual(e.active, "instant")
        self.assertTrue(e.blackout)
        self.assertEqual(e.frame(), bytes(512))
        e.toggle_blackout()
        self.assertEqual(e.frame()[0:3], bytes([0, 255, 0]))

    # -- scènes et fondus --------------------------------------------------

    def test_smoothstep_quarter(self):
        e = self.engine(blackout_fade=0.0, default_fade=4.0)
        e.set_blackout(False)  # rappelle "red" (première scène), fondu de 4 s
        self.advance(1.0)  # t = 0,25 -> 0,15625
        self.assertEqual(e.frame()[0], round(0.15625 * 255))

    def test_linear_curve(self):
        e = self.engine(blackout_fade=0.0, default_fade=4.0, curve="linear")
        e.set_blackout(False)
        self.advance(1.0)
        self.assertEqual(e.frame()[0], round(0.25 * 255))

    def test_unknown_curve(self):
        with self.assertRaises(ValueError):
            self.engine(curve="bogus")

    def test_scene_fade_overrides_default(self):
        e = self.engine(blackout_fade=0.0, default_fade=10.0)
        e.set_blackout(False)
        e.recall("instant")  # fade_s = 0 : immédiat malgré le défaut
        self.assertEqual(e.frame()[0:3], bytes([0, 255, 0]))

    def test_unlisted_fixtures_stay_as_is(self):
        e = self.engine(blackout_fade=0.0, default_fade=0.0)
        e.set_blackout(False)  # rouge sur A et B
        e.recall("blue_a")
        f = e.frame()
        self.assertEqual(f[0:3], bytes([0, 0, 255]))  # A change
        self.assertEqual(f[3:6], bytes([255, 0, 0]))  # B reste rouge

    def test_explicit_zero_intensity_turns_fixture_off(self):
        e = self.engine(blackout_fade=0.0, default_fade=0.0)
        e.set_blackout(False)
        e.recall("off_a")
        f = e.frame()
        self.assertEqual(f[0:3], bytes([0, 0, 0]))
        self.assertEqual(f[3:6], bytes([255, 0, 0]))

    def test_recall_mid_fade_starts_from_current_value(self):
        e = self.engine(blackout_fade=0.0, default_fade=2.0)
        e.set_blackout(False)  # rouge, fondu de 2 s depuis le noir
        self.advance(1.0)  # moitié : rouge à 128
        before = e.frame()[0]
        e.recall("slow")  # A vers vert en 4 s
        self.assertEqual(e.frame()[0], before)  # pas de saut

    def test_fade_out_keeps_color(self):
        e = self.engine(blackout_fade=0.0, default_fade=0.0)
        e.set_blackout(False)  # rouge à pleine intensité
        e.scenes["dim"] = Scene("dim", "Éteint", 2.0, {"a": full(0, 0, 0, 0.0)})
        e.recall("dim")
        self.advance(1.0)  # moitié : toujours rouge, intensité 0,5
        self.assertEqual(e.frame()[0:3], bytes([128, 0, 0]))

    # -- flash -------------------------------------------------------------

    def test_flash_overlays_and_releases(self):
        e = self.engine(blackout_fade=0.0, default_fade=0.0, flash_fade=0.0)
        e.set_blackout(False)  # rouge
        e.flash_on("instant")
        self.assertEqual(e.frame()[0:3], bytes([0, 255, 0]))
        self.assertEqual(e.status()["flash"], "instant")
        e.flash_off()
        self.assertEqual(e.frame()[0:3], bytes([255, 0, 0]))
        self.assertIsNone(e.status()["flash"])

    def test_flash_does_not_change_active_scene(self):
        e = self.engine(blackout_fade=0.0, default_fade=0.0, flash_fade=0.0)
        e.set_blackout(False)
        e.flash_on("blue_a")
        self.assertEqual(e.active, "red")

    def test_blackout_masks_flash(self):
        e = self.engine(initial_scene="red", flash_fade=0.0)
        e.flash_on("instant")
        self.assertEqual(e.frame(), bytes(512))

    def test_strobe_flash_scene_and_blackout_cuts_strobe(self):
        plan = Plan([Fixture("p", "P", STROBE_PROFILE, "m", 1)])
        scenes = {
            "base": Scene("base", "Base", 0.0, {"p": FixtureState(rgb=(1, 1, 1), intensity=1.0)}),
            "strobe": Scene("strobe", "Strobe", 0.0, {"p": FixtureState(rgb=(1, 1, 1), intensity=1.0,
                                                                         strobe=1.0)}),
        }
        e = Engine(plan, scenes, clock=self.clock, default_fade=0.0, blackout_fade=0.0,
                   flash_fade=0.0, initial_scene="base")
        e.set_blackout(False)
        self.assertEqual(e.frame()[4], 0)
        e.flash_on("strobe")
        self.assertEqual(e.frame()[4], 255)
        e.flash_off()
        self.assertEqual(e.frame()[4], 0)
        e.flash_on("strobe")
        e.toggle_blackout()  # le blackout masque le flash, stroboscope compris
        self.assertEqual(e.frame()[4], 0)

    # -- réglages directs --------------------------------------------------

    def test_set_state_is_immediate_and_leaves_others(self):
        e = self.engine(blackout_fade=0.0, default_fade=0.0)
        e.set_blackout(False)
        e.set_state("a", full(0, 0, 1))
        f = e.frame()
        self.assertEqual(f[0:3], bytes([0, 0, 255]))
        self.assertEqual(f[3:6], bytes([255, 0, 0]))

    def test_set_state_unknown_fixture(self):
        with self.assertRaises(KeyError):
            self.engine().set_state("zzz", full())

    def test_master(self):
        e = self.engine(blackout_fade=0.0, default_fade=0.0)
        e.set_blackout(False)
        e.set_master(0.5)
        self.assertEqual(e.frame()[0], 128)
        with self.assertRaises(ValueError):
            e.set_master(2)


if __name__ == "__main__":
    unittest.main()
