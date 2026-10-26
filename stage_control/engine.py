"""Moteur de scènes : fondus, blackout, flash (voir docs/specification-controleur.md §5).

Trois couches, de la plus basse à la plus haute :
1. la **base** : scène active, avec fondu entre l'état affiché au moment du rappel et la cible.
   Un projecteur absent de la scène rappelée reste tel quel ;
2. le **flash** : une scène superposée tant qu'on la maintient, avec un court fondu ;
3. le **blackout** : multiplie l'intensité de tous les projecteurs par un facteur
   1 → 0 (fondu). Il masque aussi le flash.

Le temps vient d'une horloge injectable (``clock``) pour pouvoir tester sans attendre.
Toutes les méthodes publiques sont protégées par un verrou : le moteur est appelé
par l'interface web, le pédalier et la boucle d'émission.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Optional

from .plan import Plan
from .render import render
from .scene import FixtureState, Scene
from .sequence import Sequence

ZERO = FixtureState()


def smoothstep(t: float) -> float:
    """Courbe en S : départ et arrivée doux."""
    return t * t * (3.0 - 2.0 * t)


def linear(t: float) -> float:
    return t


CURVES = {"smoothstep": smoothstep, "linear": linear}


def lerp_state(a: FixtureState, b: FixtureState, p: float) -> FixtureState:
    def mix(x: float, y: float) -> float:
        return min(1.0, max(0.0, x + (y - x) * p))

    intensity = mix(a.intensity, b.intensity)
    # Un projecteur éteint d'un côté du fondu ne « traverse » pas des couleurs
    # sombres : on garde la couleur de l'autre côté et seule l'intensité évolue
    # (sinon, en mode sans canal d'intensité, couleur et intensité se multiplient
    # et le fondu devient quadratique).
    if a.intensity <= 0.0:
        a = b
    elif b.intensity <= 0.0:
        b = a
    return FixtureState(
        rgb=(mix(a.rgb[0], b.rgb[0]), mix(a.rgb[1], b.rgb[1]), mix(a.rgb[2], b.rgb[2])),
        white=mix(a.white, b.white),
        amber=mix(a.amber, b.amber),
        intensity=intensity,
        strobe=mix(a.strobe, b.strobe),
    )


class _Ramp:
    """Valeur 0..1 qui évolue de ``start`` vers ``target`` en ``dur`` secondes."""

    def __init__(self, value: float, curve: Callable[[float], float]):
        self._curve = curve
        self.start = self.target = value
        self.t0 = 0.0
        self.dur = 0.0

    def progress(self, now: float) -> float:
        if self.dur <= 0:
            return 1.0
        return min(1.0, max(0.0, (now - self.t0) / self.dur))

    def value(self, now: float) -> float:
        p = self._curve(self.progress(now))
        return self.start + (self.target - self.start) * p

    def done(self, now: float) -> bool:
        return self.progress(now) >= 1.0

    def go(self, target: float, now: float, dur: float) -> None:
        self.start = self.value(now)  # repart de la valeur courante : pas de saut
        self.target = target
        self.t0 = now
        self.dur = dur


class Engine:
    def __init__(self, plan: Plan, scenes: Dict[str, Scene], *,
                 clock: Callable[[], float] = time.monotonic,
                 default_fade: float = 1.0, blackout_fade: float = 1.0,
                 flash_fade: float = 0.1, curve: str = "smoothstep",
                 initial_scene: Optional[str] = None, master: float = 1.0,
                 sequences: Optional[Dict[str, Sequence]] = None):
        if curve not in CURVES:
            raise ValueError(f"courbe inconnue : {curve!r} ({', '.join(CURVES)})")
        self.plan = plan
        self.scenes = scenes
        self.sequences: Dict[str, Sequence] = sequences if sequences is not None else {}
        self._seq: Optional[Sequence] = None  # séquence en cours
        self._idx = 0
        self._due: Optional[float] = None  # instant du passage automatique à l'étape suivante
        self._clock = clock
        self._curve = CURVES[curve]
        self.default_fade = default_fade
        self.blackout_fade = blackout_fade
        self.flash_fade = flash_fade
        self.master = master
        self._lock = threading.RLock()

        # Base : interpolation entre _start et _target depuis _t0 sur _dur.
        self._start: Dict[str, FixtureState] = {}
        self._target: Dict[str, FixtureState] = {}
        self._t0 = 0.0
        self._dur = 0.0
        self._active: Optional[str] = None

        # Démarrage en blackout (spec §5) : la scène initiale est posée sans fondu mais masquée.
        self._blackout = True
        self._bo = _Ramp(0.0, self._curve)
        self._flash = _Ramp(0.0, self._curve)
        self._flash_scene: Optional[Scene] = None
        if initial_scene is not None and initial_scene in scenes:
            self._active = initial_scene
            self._target = dict(scenes[initial_scene].states)
            self._start = dict(self._target)

    # -- états -------------------------------------------------------------

    @property
    def active(self) -> Optional[str]:
        """Scène active (à jour des passages automatiques d'une séquence)."""
        with self._lock:
            self._advance(self._clock())
            return self._active

    @property
    def blackout(self) -> bool:
        return self._blackout

    def _base_state(self, fid: str, now: float) -> FixtureState:
        a = self._start.get(fid, ZERO)
        b = self._target.get(fid, a)
        if self._dur <= 0:
            return b
        p = min(1.0, max(0.0, (now - self._t0) / self._dur))
        return lerp_state(a, b, self._curve(p))

    def states(self, now: Optional[float] = None) -> Dict[str, FixtureState]:
        """États affichés (base, flash, blackout) de chaque projecteur du plan."""
        with self._lock:
            now = self._clock() if now is None else now
            self._advance(now)
            bo = self._bo.value(now)
            fl = self._flash.value(now)
            if self._flash_scene is not None and self._flash.target == 0.0 and self._flash.done(now):
                self._flash_scene = None
            out: Dict[str, FixtureState] = {}
            for f in self.plan.fixtures:
                st = self._base_state(f.id, now)
                if self._flash_scene is not None and f.id in self._flash_scene.states and fl > 0.0:
                    st = lerp_state(st, self._flash_scene.states[f.id], fl)
                if bo < 1.0:
                    st = FixtureState(st.rgb, st.white, st.amber, st.intensity * bo,
                                      st.strobe if bo > 0.0 else 0.0)
                out[f.id] = st
            return out

    def frame(self, now: Optional[float] = None) -> bytes:
        """Univers DMX complet (512 octets) à l'instant ``now``."""
        with self._lock:
            return render(self.plan, self.states(now), self.master)

    def status(self) -> dict:
        with self._lock:
            self._advance(self._clock())
            return {"active": self.active, "blackout": self._blackout,
                    "flash": self._flash_scene.id if self._flash_scene and self._flash.target > 0 else None,
                    "sequence": self._seq.id if self._seq else None,
                    "step": self._idx if self._seq else None}

    # -- commandes ---------------------------------------------------------

    def _fade_of(self, scene: Scene) -> float:
        return self.default_fade if scene.fade_s is None else scene.fade_s

    def _apply(self, scene: Scene, now: float, fade: float) -> None:
        current = {f.id: self._base_state(f.id, now) for f in self.plan.fixtures}
        self._start = current
        self._target = dict(current)
        self._target.update(scene.states)
        self._t0 = now
        self._dur = fade
        self._active = scene.id

    def recall(self, scene_id: str) -> None:
        """Rappelle une scène avec fondu (et arrête la séquence en cours). Les projecteurs
        hors scène restent tels quels. Pendant un blackout, la scène devient active mais
        le blackout reste en place."""
        with self._lock:
            scene = self.scenes[scene_id]
            self.stop_sequence()
            self._apply(scene, self._clock(), self._fade_of(scene))

    # -- séquences ---------------------------------------------------------

    def _enter_step(self, idx: int, now: float) -> None:
        step = self._seq.steps[idx]
        scene = self.scenes[step.scene]
        fade = self._fade_of(scene) if step.fade_s is None else step.fade_s
        self._apply(scene, now, fade)
        self._idx = idx
        self._due = None if step.hold_s is None else now + fade + step.hold_s

    def _advance(self, now: float) -> None:
        """Applique les passages automatiques échus (à leur instant, pas à ``now``)."""
        guard = 0
        while self._seq is not None and self._due is not None and self._due <= now:
            guard += 1
            due = self._due
            if guard > 10_000:  # retard énorme : on repart de maintenant
                due = now
            if self._idx + 1 < len(self._seq.steps):
                self._enter_step(self._idx + 1, due)
            elif self._seq.loop:
                self._enter_step(0, due)
            else:
                self.stop_sequence()  # fin : la dernière scène reste active

    def start_sequence(self, sequence_id: str) -> None:
        """Lance une séquence (remplace celle en cours)."""
        with self._lock:
            seq = self.sequences[sequence_id]
            for step in seq.steps:
                if step.scene not in self.scenes:
                    raise KeyError(step.scene)
            self._seq = seq
            self._enter_step(0, self._clock())

    def stop_sequence(self) -> None:
        with self._lock:
            self._seq = None
            self._due = None

    def toggle_sequence(self, sequence_id: str) -> bool:
        """Pédale de séquence : lance, ou arrête si c'est elle qui tourne. Renvoie « en cours »."""
        with self._lock:
            self._advance(self._clock())
            if self._seq is not None and self._seq.id == sequence_id:
                self.stop_sequence()
                return False
            self.start_sequence(sequence_id)
            return True

    def next_step(self) -> None:
        with self._lock:
            now = self._clock()
            self._advance(now)
            if self._seq is None:
                return
            if self._idx + 1 < len(self._seq.steps):
                self._enter_step(self._idx + 1, now)
            elif self._seq.loop:
                self._enter_step(0, now)
            else:
                self.stop_sequence()

    def prev_step(self) -> None:
        with self._lock:
            now = self._clock()
            self._advance(now)
            if self._seq is None:
                return
            if self._idx > 0:
                self._enter_step(self._idx - 1, now)
            elif self._seq.loop:
                self._enter_step(len(self._seq.steps) - 1, now)
            else:
                self._enter_step(0, now)  # retour au début de la séquence

    def set_blackout(self, on: bool) -> None:
        with self._lock:
            if on == self._blackout:
                return
            now = self._clock()
            if not on and self._active is None and self.scenes:
                self.recall(next(iter(self.scenes)))  # aucune scène mémorisée : la première
            self._blackout = on
            self._bo.go(0.0 if on else 1.0, now, self.blackout_fade)

    def toggle_blackout(self) -> bool:
        with self._lock:
            self.set_blackout(not self._blackout)
            return self._blackout

    def flash_on(self, scene_id: str) -> None:
        with self._lock:
            now = self._clock()
            self._flash_scene = self.scenes[scene_id]
            self._flash.go(1.0, now, self.flash_fade)

    def flash_off(self) -> None:
        with self._lock:
            if self._flash_scene is not None:
                self._flash.go(0.0, self._clock(), self.flash_fade)

    def set_state(self, fixture_id: str, state: FixtureState) -> None:
        """Modification immédiate d'un projecteur (roue de couleur, sliders)."""
        with self._lock:
            self.plan.get(fixture_id)  # KeyError si inconnu
            # Seul ce projecteur est figé sur la valeur voulue ; un fondu en cours
            # continue pour les autres.
            self._start[fixture_id] = state
            self._target[fixture_id] = state

    def set_master(self, master: float) -> None:
        if not 0.0 <= master <= 1.0:
            raise ValueError(f"intensité générale hors 0..1 : {master}")
        with self._lock:
            self.master = master
