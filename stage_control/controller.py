"""Contrôleur : façade unique des commandes (interface web, pédalier, plus tard XR18).

Toutes les sources de commande passent par ici ; le moteur reste seul à produire le DMX.
Le contrôleur publie aussi les changements d'état (événements pour le SSE) et enregistre,
avec un délai, la dernière scène active.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
import unicodedata
from typing import Dict, List, Optional

from .engine import Engine
from .scene import FixtureState, Scene
from .sequence import Sequence, Step
from .store import PEDAL_SLOTS, PedalAction, Settings, Store

log = logging.getLogger("stage_control.controller")

BLACKOUT_PEDAL = PEDAL_SLOTS + 1  # 7ᵉ bouton, figé en blackout
_STATE_FIELDS = ("rgb", "white", "amber", "intensity", "strobe")


class Conflict(Exception):
    """Opération refusée car l'élément est utilisé ailleurs (HTTP 409)."""


class EventBus:
    """Diffusion d'événements vers les clients SSE (une file par client)."""

    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()

    def subscribe(self) -> "queue.Queue":
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            self._subs.discard(q)

    def publish(self, event: str, data) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((event, data))
            except queue.Full:  # client bloqué : on le lâche, il se reconnectera
                self.unsubscribe(q)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "sans-nom"


class Controller:
    def __init__(self, engine: Engine, store: Store, settings: Settings,
                 bus: Optional[EventBus] = None, save_delay: float = 5.0,
                 clock=time.monotonic):
        self.engine = engine
        self.store = store
        self.settings = settings
        self.bus = bus or EventBus()
        self.save_delay = save_delay
        self._clock = clock
        self._lock = threading.RLock()
        self._last_status: Optional[dict] = None
        self._dirty_since: Optional[float] = None

    # -- état --------------------------------------------------------------

    def leds(self, status: Optional[dict] = None) -> dict:
        """État des LED du pédalier : 6 emplacements + blackout (spec §4.5 et §7)."""
        st = status or self.engine.status()
        slots: List[bool] = []
        for action in self.settings.pedals:
            if action.type == "scene":
                # Pendant une séquence, seule la pédale de la séquence est allumée : sinon la
                # LED d'une scène qui apparaît dans la séquence prêterait à confusion.
                lit = st["sequence"] is None and st["active"] == action.target
            elif action.type == "sequence":
                lit = st["sequence"] == action.target
            elif action.type == "flash":
                lit = st["flash"] == action.target
            else:
                lit = False
            slots.append(lit)
        return {"slots": slots, "blackout": st["blackout"]}

    def status(self) -> dict:
        st = self.engine.status()
        st["leds"] = self.leds(st)
        return st

    def poll(self) -> dict:
        """Compare l'état au précédent, publie s'il a changé, enregistre la scène active (différé)."""
        with self._lock:
            st = self.status()
            if st != self._last_status:
                self._last_status = st
                self.bus.publish("status", st)
            now = self._clock()
            if st["active"] != self.settings.last_scene and st["active"] is not None:
                self.settings.last_scene = st["active"]
                self._dirty_since = self._dirty_since if self._dirty_since is not None else now
            if self._dirty_since is not None and now - self._dirty_since >= self.save_delay:
                self.flush()
            return st

    def flush(self) -> None:
        with self._lock:
            if self._dirty_since is not None:
                self.store.save_settings(self.settings)
                self._dirty_since = None

    def dump(self) -> dict:
        """Tout ce dont l'interface a besoin pour s'afficher."""
        with self._lock, self.engine.lock:
            fixtures = []
            for f in self.engine.plan.fixtures:
                roles = [c.role for c in f.mode.channels]
                fixtures.append({"id": f.id, "name": f.name, "profile": f.profile.name,
                                 "mode": f.mode_name, "address": f.address, "roles": roles})
            base = self.engine.base_states()
            return {
                "fixtures": fixtures,
                "scenes": [s.to_dict() for s in self.engine.scenes.values()],
                "sequences": [s.to_dict() for s in self.engine.sequences.values()],
                "settings": self.settings.to_dict(),
                "status": self.status(),
                "current": {fid: st.to_dict() for fid, st in base.items()},
            }

    def _changed(self) -> None:
        self.bus.publish("config", {"t": time.time()})
        self.poll()

    # -- commandes de jeu --------------------------------------------------

    def recall(self, scene_id: str) -> None:
        self.engine.recall(scene_id)
        self.poll()

    def set_blackout(self, on: Optional[bool] = None) -> bool:
        if on is None:
            self.engine.toggle_blackout()
        else:
            self.engine.set_blackout(on)
        self.poll()
        return self.engine.blackout

    def flash(self, scene_id: str, down: bool) -> None:
        if down:
            self.engine.flash_on(scene_id)
        else:
            self.engine.flash_off()
        self.poll()

    def toggle_sequence(self, sequence_id: str) -> bool:
        running = self.engine.toggle_sequence(sequence_id)
        self.poll()
        return running

    def stop_sequence(self) -> None:
        self.engine.stop_sequence()
        self.poll()

    def next_step(self) -> None:
        self.engine.next_step()
        self.poll()

    def prev_step(self) -> None:
        self.engine.prev_step()
        self.poll()

    def set_fixtures(self, fixture_ids: List[str], fields: dict) -> Dict[str, FixtureState]:
        """Réglage direct (roue de couleur, sliders) de plusieurs projecteurs à la fois.

        Seuls les champs fournis changent. Tout est validé avant d'appliquer quoi que ce soit.
        """
        unknown = set(fields) - set(_STATE_FIELDS)
        if unknown:
            raise ValueError(f"champs inconnus : {', '.join(sorted(unknown))}")
        with self.engine.lock:
            for fid in fixture_ids:
                self.engine.plan.get(fid)  # KeyError si inconnu
            base = self.engine.base_states()
            new = {}
            for fid in fixture_ids:
                merged = base[fid].to_dict()
                merged.update(fields)
                new[fid] = FixtureState.from_dict(merged)
            for fid, state in new.items():
                self.engine.set_state(fid, state)
        self.poll()
        return new

    def set_fixture(self, fixture_id: str, fields: dict) -> FixtureState:
        return self.set_fixtures([fixture_id], fields)[fixture_id]

    def pedal(self, n: int, down: bool) -> None:
        """Événement de pédale : ``n`` de 1 à 7 (7 = blackout), ``down`` = appui / relâchement."""
        if not 1 <= n <= BLACKOUT_PEDAL:
            raise ValueError(f"pédale {n} inexistante (1 à {BLACKOUT_PEDAL})")
        if n == BLACKOUT_PEDAL:
            if down:
                self.engine.toggle_blackout()
        else:
            action = self.settings.pedals[n - 1]
            if action.type == "flash":
                (self.engine.flash_on(action.target) if down else self.engine.flash_off())
            elif down:
                if action.type == "scene":
                    self.engine.recall(action.target)
                elif action.type == "sequence":
                    self.engine.toggle_sequence(action.target)
                elif action.type == "next":
                    self.engine.next_step()
                elif action.type == "prev":
                    self.engine.prev_step()
        self.poll()

    # -- édition -----------------------------------------------------------

    def save_scene(self, scene_id: Optional[str], data: dict) -> Scene:
        """Crée (``scene_id`` vide) ou remplace une scène.

        ``data`` : ``name``, ``fade_s`` (optionnel) et soit ``states`` (id de projecteur vers état),
        soit ``capture`` (liste d'ids de projecteurs, ou ``"all"``) pour enregistrer l'état courant.
        """
        with self.engine.lock:
            plan_ids = {f.id for f in self.engine.plan.fixtures}
            if "states" in data:
                states = {fid: FixtureState.from_dict(s) for fid, s in data["states"].items()}
            elif "capture" in data:
                wanted = plan_ids if data["capture"] == "all" else set(data["capture"])
                base = self.engine.base_states()
                states = {fid: st for fid, st in base.items() if fid in wanted}
            else:
                raise ValueError("« states » ou « capture » requis")
            unknown = set(states) - plan_ids
            if unknown:
                raise ValueError(f"projecteurs inconnus : {', '.join(sorted(unknown))}")
            existing = self.engine.scenes.get(scene_id) if scene_id else None
            if scene_id and existing is None:
                raise KeyError(scene_id)
            name = data.get("name") or (existing.name if existing else None)
            if not name:
                raise ValueError("nom requis")
            if scene_id is None:
                base_id, scene_id, i = slugify(name), None, 1
                scene_id = base_id
                while scene_id in self.engine.scenes:
                    i += 1
                    scene_id = f"{base_id}-{i}"
            fade = data.get("fade_s", existing.fade_s if existing else None)
            scene = Scene.from_dict({"id": scene_id, "name": name, "fade_s": fade,
                                     "states": {k: v.to_dict() for k, v in states.items()}})
            self.engine.scenes[scene_id] = scene
            self.store.save_scenes(self.engine.scenes)
        self._changed()
        return scene

    def delete_scene(self, scene_id: str) -> None:
        with self.engine.lock:
            if scene_id not in self.engine.scenes:
                raise KeyError(scene_id)
            users = [s.name for s in self.engine.sequences.values()
                     if any(st.scene == scene_id for st in s.steps)]
            if users:
                raise Conflict(f"scène utilisée par les séquences : {', '.join(users)}")
            if any(p.target == scene_id for p in self.settings.pedals):
                raise Conflict("scène affectée à une pédale")
            del self.engine.scenes[scene_id]
            self.store.save_scenes(self.engine.scenes)
        self._changed()

    def save_sequence(self, sequence_id: Optional[str], data: dict) -> Sequence:
        with self.engine.lock:
            existing = self.engine.sequences.get(sequence_id) if sequence_id else None
            if sequence_id and existing is None:
                raise KeyError(sequence_id)
            name = data.get("name") or (existing.name if existing else None)
            if not name:
                raise ValueError("nom requis")
            if sequence_id is None:
                base_id, i = slugify(name), 1
                sequence_id = base_id
                while sequence_id in self.engine.sequences:
                    i += 1
                    sequence_id = f"{base_id}-{i}"
            steps = [Step(s["scene"], s.get("fade_s"), s.get("hold_s")) for s in data.get("steps", [])]
            for st in steps:
                if st.scene not in self.engine.scenes:
                    raise ValueError(f"scène inconnue : {st.scene!r}")
            seq = Sequence(sequence_id, name, steps, bool(data.get("loop", existing.loop if existing else False)))
            self.engine.sequences[sequence_id] = seq
            self.store.save_sequences(self.engine.sequences)
        self._changed()
        return seq

    def delete_sequence(self, sequence_id: str) -> None:
        with self.engine.lock:
            if sequence_id not in self.engine.sequences:
                raise KeyError(sequence_id)
            if any(p.target == sequence_id for p in self.settings.pedals):
                raise Conflict("séquence affectée à une pédale")
            if self.engine.status()["sequence"] == sequence_id:
                self.engine.stop_sequence()
            del self.engine.sequences[sequence_id]
            self.store.save_sequences(self.engine.sequences)
        self._changed()

    def update_settings(self, data: dict) -> Settings:
        """Met à jour intensité générale, fondus et pédales (courbe : au redémarrage seulement)."""
        with self._lock, self.engine.lock:
            merged = self.settings.to_dict()
            for key in ("master", "default_fade", "blackout_fade", "flash_fade", "pedals"):
                if key in data:
                    merged[key] = data[key]
            new = Settings.from_dict(merged)
            for p in new.pedals:
                if p.type in ("scene", "flash") and p.target not in self.engine.scenes:
                    raise ValueError(f"scène inconnue : {p.target!r}")
                if p.type == "sequence" and p.target not in self.engine.sequences:
                    raise ValueError(f"séquence inconnue : {p.target!r}")
            new.last_scene = self.settings.last_scene
            self.engine.set_master(new.master)
            self.engine.default_fade = new.default_fade
            self.engine.blackout_fade = new.blackout_fade
            self.engine.flash_fade = new.flash_fade
            self.settings = new
            self.store.save_settings(new)
            self._dirty_since = None
        self._changed()
        return new


class Ticker(threading.Thread):
    """Fait avancer les événements d'état (passages de séquence, fondus) sans requête."""

    def __init__(self, controller: Controller, period: float = 0.2):
        super().__init__(daemon=True, name="controller-ticker")
        self.controller = controller
        self.period = period
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.wait(self.period):
            try:
                self.controller.poll()
            except Exception:  # un défaut d'affichage ne doit jamais arrêter le contrôle
                log.exception("erreur dans le suivi d'état")

    def stop(self) -> None:
        self._halt.set()
        self.controller.flush()
