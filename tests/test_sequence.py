import unittest

from stage_control.engine import Engine
from stage_control.plan import Fixture, Plan
from stage_control.profile import profile_from_dict
from stage_control.scene import FixtureState, Scene
from stage_control.sequence import Sequence, Step

RGB = profile_from_dict({
    "name": "rgb3", "modes": {"3ch": {"channels": [
        {"role": "red"}, {"role": "green"}, {"role": "blue"}]}}})


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def col(r, g, b):
    return Scene("", "", 0.0, {"a": FixtureState(rgb=(r, g, b), intensity=1.0)})


class SequenceModelTests(unittest.TestCase):
    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            Sequence("s", "S", [])

    def test_negative_times_rejected(self):
        with self.assertRaises(ValueError):
            Step("x", fade_s=-1)
        with self.assertRaises(ValueError):
            Step("x", hold_s=-1)

    def test_zero_length_loop_rejected(self):
        with self.assertRaises(ValueError):
            Sequence("s", "S", [Step("x", 0.0, 0.0)], loop=True)
        Sequence("s", "S", [Step("x", 0.0, None)], loop=True)  # un pas manuel : accepté

    def test_roundtrip(self):
        s = Sequence("s", "S", [Step("x", 1.0, 2.0), Step("y")], loop=True)
        s2 = Sequence.from_dict(s.to_dict())
        self.assertEqual(s2.steps, s.steps)
        self.assertTrue(s2.loop)


class SequenceEngineTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.plan = Plan([Fixture("a", "A", RGB, "3ch", 1)])
        scenes = {}
        for sid, c in (("r", (1, 0, 0)), ("g", (0, 1, 0)), ("b", (0, 0, 1))):
            sc = col(*c)
            sc.id = sid
            scenes[sid] = sc
        self.scenes = scenes
        self.seqs = {
            "timed": Sequence("timed", "Auto", [Step("r", 0.0, 2.0), Step("g", 0.0, 2.0),
                                                Step("b", 0.0, 2.0)]),
            "loop": Sequence("loop", "Boucle", [Step("r", 0.0, 1.0), Step("g", 0.0, 1.0)], loop=True),
            "manual": Sequence("manual", "Manuel", [Step("r"), Step("g"), Step("b")]),
            "mixed": Sequence("mixed", "Mixte", [Step("r", 0.0, 1.0), Step("g")]),
            "fade": Sequence("fade", "Fondu", [Step("r", 0.0, 0.0), Step("g", 2.0, 1.0)]),
        }
        self.e = Engine(self.plan, self.scenes, clock=self.clock, sequences=self.seqs,
                        default_fade=0.0, blackout_fade=0.0)
        self.e.set_blackout(False)

    def advance(self, s):
        self.clock.t += s

    def px(self):
        return self.e.frame()[0:3]

    def test_timed_sequence_plays_then_stops_on_last_scene(self):
        self.e.start_sequence("timed")
        self.assertEqual(self.px(), bytes([255, 0, 0]))
        self.advance(2.0)
        self.assertEqual(self.px(), bytes([0, 255, 0]))
        self.advance(2.0)
        self.assertEqual(self.px(), bytes([0, 0, 255]))
        self.assertEqual(self.e.status()["sequence"], "timed")
        self.advance(2.0)  # fin : s'arrête, la dernière scène reste
        self.assertEqual(self.px(), bytes([0, 0, 255]))
        self.assertIsNone(self.e.status()["sequence"])
        self.assertEqual(self.e.active, "b")

    def test_loop_wraps(self):
        self.e.start_sequence("loop")
        self.advance(1.0)
        self.assertEqual(self.px(), bytes([0, 255, 0]))
        self.advance(1.0)
        self.assertEqual(self.px(), bytes([255, 0, 0]))
        self.advance(100.0)  # rattrape sans planter : 100 s = 100 passages, retour au rouge
        self.assertEqual(self.px(), bytes([255, 0, 0]))
        self.assertEqual(self.e.status()["sequence"], "loop")

    def test_catch_up_applies_missed_steps_in_order(self):
        self.e.start_sequence("timed")
        self.advance(5.0)  # 2 passages échus d'un coup (à t+2 et t+4)
        self.assertEqual(self.px(), bytes([0, 0, 255]))
        self.assertEqual(self.e.status()["step"], 2)

    def test_manual_steps_wait_for_next(self):
        self.e.start_sequence("manual")
        self.advance(1000.0)
        self.assertEqual(self.px(), bytes([255, 0, 0]))  # jamais de passage automatique
        self.e.next_step()
        self.assertEqual(self.px(), bytes([0, 255, 0]))
        self.e.next_step()
        self.assertEqual(self.px(), bytes([0, 0, 255]))
        self.e.next_step()  # dernière étape, non bouclée : la séquence se termine
        self.assertIsNone(self.e.status()["sequence"])
        self.assertEqual(self.px(), bytes([0, 0, 255]))

    def test_next_restarts_timer_and_mixed_steps(self):
        self.e.start_sequence("mixed")
        self.advance(0.5)
        self.e.next_step()  # saute le délai
        self.assertEqual(self.px(), bytes([0, 255, 0]))
        self.advance(1000.0)  # étape manuelle : reste
        self.assertEqual(self.e.status()["step"], 1)

    def test_prev_step(self):
        self.e.start_sequence("manual")
        self.e.next_step()
        self.e.next_step()
        self.e.prev_step()
        self.assertEqual(self.px(), bytes([0, 255, 0]))
        self.e.prev_step()
        self.e.prev_step()  # au début, non bouclée : reste sur la première
        self.assertEqual(self.px(), bytes([255, 0, 0]))
        self.assertEqual(self.e.status()["step"], 0)

    def test_next_prev_without_sequence_do_nothing(self):
        self.e.recall("g")
        self.e.next_step()
        self.e.prev_step()
        self.assertEqual(self.px(), bytes([0, 255, 0]))

    def test_toggle_starts_then_stops(self):
        self.assertTrue(self.e.toggle_sequence("loop"))
        self.advance(1.0)
        self.assertFalse(self.e.toggle_sequence("loop"))
        self.advance(10.0)  # arrêtée : plus de progression
        self.assertEqual(self.px(), bytes([0, 255, 0]))
        self.assertIsNone(self.e.status()["sequence"])

    def test_starting_another_sequence_replaces_the_first(self):
        self.e.start_sequence("loop")
        self.e.start_sequence("manual")
        self.assertEqual(self.e.status()["sequence"], "manual")

    def test_manual_recall_stops_sequence(self):
        self.e.start_sequence("loop")
        self.e.recall("b")
        self.advance(10.0)
        self.assertEqual(self.px(), bytes([0, 0, 255]))
        self.assertIsNone(self.e.status()["sequence"])

    def test_hold_counts_from_end_of_fade(self):
        self.e.start_sequence("fade")  # étape 1 immédiate, sans délai : passe tout de suite à l'étape 2
        self.assertEqual(self.e.status()["step"], 1)
        self.advance(2.9)  # fondu de 2 s + délai de 1 s : fin à 3 s
        self.assertEqual(self.e.status()["sequence"], "fade")
        self.advance(0.2)
        self.assertIsNone(self.e.status()["sequence"])
        self.assertEqual(self.px(), bytes([0, 255, 0]))

    def test_sequence_continues_during_blackout(self):
        self.e.start_sequence("timed")
        self.e.set_blackout(True)
        self.advance(2.0)
        self.assertEqual(self.e.active, "g")
        self.assertEqual(self.e.frame(), bytes(512))

    def test_unknown_scene_in_sequence(self):
        self.e.sequences["bad"] = Sequence("bad", "Mauvaise", [Step("zzz", 0.0, 1.0)])
        with self.assertRaises(KeyError):
            self.e.start_sequence("bad")
        self.assertIsNone(self.e.status()["sequence"])


if __name__ == "__main__":
    unittest.main()
