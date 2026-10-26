import unittest

from stage_control.plan import Fixture, Plan
from stage_control.profile import profile_from_dict
from stage_control.render import render, render_fixture
from stage_control.scene import FixtureState, Scene

# Profils génériques de test : ce ne sont PAS les canaux des PARty Spot.
RGB = profile_from_dict({
    "name": "rgb3", "modes": {"3ch": {"channels": [
        {"role": "red"}, {"role": "green"}, {"role": "blue"}]}}})

RGBW_DIM = profile_from_dict({
    "name": "rgbw-dim", "modes": {"6ch": {"channels": [
        {"role": "intensity"}, {"role": "red"}, {"role": "green"}, {"role": "blue"},
        {"role": "white"}, {"role": "strobe", "default": 7}]}}})

RGBA = profile_from_dict({
    "name": "rgba", "modes": {"4ch": {"channels": [
        {"role": "red"}, {"role": "green"}, {"role": "blue"}, {"role": "amber"}]}}})


class ProfileTests(unittest.TestCase):
    def test_unknown_role(self):
        with self.assertRaises(ValueError):
            profile_from_dict({"name": "x", "modes": {"m": {"channels": [{"role": "bogus"}]}}})

    def test_repeated_color_role(self):
        with self.assertRaises(ValueError):
            profile_from_dict({"name": "x", "modes": {"m": {"channels": [
                {"role": "red"}, {"role": "red"}]}}})

    def test_default_out_of_range(self):
        with self.assertRaises(ValueError):
            profile_from_dict({"name": "x", "modes": {"m": {"channels": [
                {"role": "strobe", "default": 300}]}}})

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            RGB.mode("9ch")

    def test_no_modes(self):
        with self.assertRaises(ValueError):
            profile_from_dict({"name": "x", "modes": {}})


class PlanTests(unittest.TestCase):
    def test_overlap_rejected(self):
        with self.assertRaises(ValueError):
            Plan([Fixture("a", "A", RGB, "3ch", 1), Fixture("b", "B", RGB, "3ch", 3)])

    def test_adjacent_ok_and_count(self):
        p = Plan([Fixture("a", "A", RGB, "3ch", 1), Fixture("b", "B", RGBW_DIM, "6ch", 4)])
        self.assertEqual(p.channel_count(), 9)

    def test_out_of_universe(self):
        with self.assertRaises(ValueError):
            Plan([Fixture("a", "A", RGB, "3ch", 511)])
        with self.assertRaises(ValueError):
            Plan([Fixture("a", "A", RGB, "3ch", 0)])

    def test_duplicate_id(self):
        with self.assertRaises(ValueError):
            Plan([Fixture("a", "A", RGB, "3ch", 1), Fixture("a", "B", RGB, "3ch", 10)])


class PlanAddressTests(unittest.TestCase):
    def plan(self, *spec):
        return Plan([Fixture(f"f{a}", f"F{a}", RGB, "3ch", a) for a in spec])

    def test_free_address_empty_plan(self):
        self.assertEqual(self.plan().free_address(6), 1)

    def test_free_address_after_last_fixture(self):
        self.assertEqual(self.plan(1, 4).free_address(3), 7)

    def test_free_address_uses_the_first_gap_that_fits(self):
        p = self.plan(1, 10)  # occupe 1-3 et 10-12 : un trou de 4 à 9
        self.assertEqual(p.free_address(3), 4)
        self.assertEqual(p.free_address(6), 4)
        self.assertEqual(p.free_address(7), 13)  # trop grand pour le trou

    def test_free_address_ignores_the_fixture_being_edited(self):
        self.assertEqual(self.plan(1).free_address(3, ignore="f1"), 1)

    def test_free_address_when_full(self):
        p = self.plan(1, 4, 7)
        self.assertEqual(p.free_address(510), None)  # 510 canaux ne tiennent pas après 9
        self.assertEqual(p.free_address(503), 10)  # 10..512 : exactement jusqu'au bout

    def test_to_spec_keeps_profile_key(self):
        p = Plan([Fixture("a", "A", RGB, "3ch", 5, "ma-cle")])
        self.assertEqual(p.to_spec(), [{"id": "a", "name": "A", "profile": "ma-cle", "mode": "3ch", "address": 5}])


class RenderTests(unittest.TestCase):
    def test_scale_mode_without_intensity_channel(self):
        f = Fixture("a", "A", RGB, "3ch", 1)
        out = render_fixture(f, FixtureState(rgb=(1.0, 0.5, 0.0), intensity=0.5))
        self.assertEqual(out, bytes([128, 64, 0]))  # 255*0.5 = 127.5 -> 128 ; 255*0.25 = 63.75 -> 64

    def test_intensity_channel_mode(self):
        f = Fixture("a", "A", RGBW_DIM, "6ch", 1)
        out = render_fixture(f, FixtureState(rgb=(1.0, 0.0, 0.0), white=1.0, intensity=0.5))
        # intensité sur son canal, couleurs et blanc non atténués, strobe = défaut du profil
        self.assertEqual(out, bytes([128, 255, 0, 0, 255, 7]))

    def test_missing_roles_are_ignored(self):
        f = Fixture("a", "A", RGB, "3ch", 1)
        out = render_fixture(f, FixtureState(rgb=(0, 0, 0), white=1.0, amber=1.0, intensity=1.0))
        self.assertEqual(out, bytes([0, 0, 0]))  # pas de blanc/ambre simulé

    def test_amber(self):
        f = Fixture("a", "A", RGBA, "4ch", 1)
        out = render_fixture(f, FixtureState(amber=0.5, intensity=1.0))
        self.assertEqual(out, bytes([0, 0, 0, 128]))

    def test_master(self):
        f = Fixture("a", "A", RGBW_DIM, "6ch", 1)
        out = render_fixture(f, FixtureState(rgb=(1, 1, 1), intensity=1.0), master=0.5)
        self.assertEqual(out[0], 128)
        self.assertEqual(out[1], 255)

    def test_master_out_of_range(self):
        plan = Plan([Fixture("a", "A", RGB, "3ch", 1)])
        with self.assertRaises(ValueError):
            render(plan, {}, master=1.5)

    def test_universe_layout_and_defaults(self):
        plan = Plan([Fixture("a", "A", RGB, "3ch", 1), Fixture("b", "B", RGBW_DIM, "6ch", 10)])
        u = render(plan, {"a": FixtureState(rgb=(1, 0, 0), intensity=1.0)})
        self.assertEqual(len(u), 512)
        self.assertEqual(u[0:3], bytes([255, 0, 0]))
        self.assertEqual(u[3:9], bytes(6))
        # projecteur sans état : couleurs à zéro, strobe à sa valeur par défaut
        self.assertEqual(u[9:15], bytes([0, 0, 0, 0, 0, 7]))

    def test_rounding_clamps(self):
        f = Fixture("a", "A", RGB, "3ch", 1)
        out = render_fixture(f, FixtureState(rgb=(1.0, 1.0, 1.0), intensity=1.0))
        self.assertEqual(out, bytes([255, 255, 255]))


class PartySpotProfileTests(unittest.TestCase):
    """Profil réel (notice Eurolite p. 12) : modes 4 et 6 canaux."""

    @classmethod
    def setUpClass(cls):
        import os
        from stage_control.profile import load_profile
        path = os.path.join(os.path.dirname(__file__), "..", "profiles",
                            "eurolite-party-spot-silent-rgbww.json")
        cls.profile = load_profile(path)

    def test_4ch_has_no_master_so_intensity_scales_colors(self):
        f = Fixture("p", "P", self.profile, "4ch", 1)
        out = render_fixture(f, FixtureState(rgb=(1, 0.5, 0), white=1.0, intensity=0.5))
        self.assertEqual(out, bytes([128, 64, 0, 128]))

    def test_6ch_master_dimmer_and_strobe_off(self):
        f = Fixture("p", "P", self.profile, "6ch", 1)
        out = render_fixture(f, FixtureState(rgb=(1, 0, 0), white=0.5, intensity=0.5))
        self.assertEqual(out, bytes([255, 0, 0, 128, 128, 0]))  # strobe 0 = « aucune fonction »

    def test_strobe_off_is_zero_and_on_uses_active_range(self):
        f = Fixture("p", "P", self.profile, "6ch", 1)
        off = render_fixture(f, FixtureState(intensity=1.0))
        self.assertEqual(off[5], 0)  # « aucune fonction »
        slow = render_fixture(f, FixtureState(intensity=1.0, strobe=0.001))
        self.assertEqual(slow[5], 11)  # début de la plage stroboscope (1..5 = musique : jamais utilisé)
        fast = render_fixture(f, FixtureState(intensity=1.0, strobe=1.0))
        self.assertEqual(fast[5], 255)
        mid = render_fixture(f, FixtureState(intensity=1.0, strobe=0.5))
        self.assertEqual(mid[5], 11 + round(244 * 0.5))

    def test_strobe_range_8ch_starts_at_10(self):
        f = Fixture("p", "P", self.profile, "8ch", 1)
        self.assertEqual(render_fixture(f, FixtureState(intensity=1.0, strobe=0.001))[5], 10)

    def test_strobe_is_not_scaled_by_intensity_or_master(self):
        f = Fixture("p", "P", self.profile, "6ch", 1)
        out = render_fixture(f, FixtureState(intensity=0.5, strobe=1.0), master=0.5)
        self.assertEqual(out[5], 255)

    def test_strobe_ignored_when_profile_has_no_channel(self):
        f = Fixture("p", "P", self.profile, "4ch", 1)
        out = render_fixture(f, FixtureState(rgb=(1, 0, 0), intensity=1.0, strobe=1.0))
        self.assertEqual(out, bytes([255, 0, 0, 0]))

    def test_strobe_range_validation(self):
        with self.assertRaises(ValueError):
            profile_from_dict({"name": "x", "modes": {"m": {"channels": [
                {"role": "strobe", "min": 200, "max": 100}]}}})
        with self.assertRaises(ValueError):
            profile_from_dict({"name": "x", "modes": {"m": {"channels": [
                {"role": "strobe", "max": 300}]}}})

    def test_strobe_roundtrip_in_scene(self):
        s = Scene("s", "S", None, {"a": FixtureState(strobe=0.4)})
        self.assertEqual(Scene.from_dict(s.to_dict()).states["a"].strobe, 0.4)
        with self.assertRaises(ValueError):
            FixtureState(strobe=1.5)

    def test_8ch_auto_programs_and_speed_stay_off(self):
        f = Fixture("p", "P", self.profile, "8ch", 1)
        out = render_fixture(f, FixtureState(rgb=(0, 1, 0), white=0.0, intensity=1.0))
        # canal 6 strobe 0, canal 7 programmes auto 0 (000-020 = aucune fonction), canal 8 vitesse 0
        self.assertEqual(out, bytes([0, 255, 0, 0, 255, 0, 0, 0]))

    def test_four_fixtures_in_8ch_mode_addresses(self):
        plan = Plan([Fixture(f"p{i}", f"P{i}", self.profile, "8ch", 1 + 8 * i) for i in range(4)])
        self.assertEqual([f.address for f in plan.fixtures], [1, 9, 17, 25])
        self.assertEqual(plan.channel_count(), 32)

    def test_four_fixtures_in_6ch_mode_fit_with_adjacent_addresses(self):
        plan = Plan([Fixture(f"p{i}", f"P{i}", self.profile, "6ch", 1 + 6 * i) for i in range(4)])
        self.assertEqual(plan.channel_count(), 24)


class SceneTests(unittest.TestCase):
    def test_state_validation(self):
        with self.assertRaises(ValueError):
            FixtureState(intensity=1.2)
        with self.assertRaises(ValueError):
            FixtureState(rgb=(0, 0, -0.1))

    def test_roundtrip(self):
        s = Scene("s1", "Refrain", 2.0, {"a": FixtureState(rgb=(1, 0.5, 0), white=0.25, intensity=0.8)})
        s2 = Scene.from_dict(s.to_dict())
        self.assertEqual(s2.states["a"], s.states["a"])
        self.assertEqual((s2.id, s2.name, s2.fade_s), ("s1", "Refrain", 2.0))

    def test_default_fade_is_none(self):
        self.assertIsNone(Scene.from_dict({"id": "x"}).fade_s)

    def test_negative_fade(self):
        with self.assertRaises(ValueError):
            Scene.from_dict({"id": "x", "fade_s": -1})


if __name__ == "__main__":
    unittest.main()
