"""Contrôleur : façade unique des commandes (interface web, pédalier, plus tard XR18).

Toutes les sources de commande passent par ici ; le moteur reste seul à produire le DMX.
Le contrôleur publie aussi les changements d'état (événements pour le SSE) et enregistre,
avec un délai, la dernière scène active.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
import unicodedata
from typing import Dict, List, Optional

from .engine import Engine
from .plan import UNIVERSE_SIZE, Fixture, Plan
from .profile import profile_from_dict
from .scene import FixtureState, Scene
from .sequence import Sequence, Step
from .store import PEDAL_SLOTS, PedalAction, Settings, Store, valid_profile_key

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


def fixture_json(f: Fixture) -> dict:
    return {"id": f.id, "name": f.name, "profile": f.profile.name, "profile_key": f.profile_key,
            "mode": f.mode_name, "address": f.address, "end": f.end, "channels": f.mode.size,
            "roles": [c.role for c in f.mode.channels]}


class Controller:
    def __init__(self, engine: Engine, store: Store, settings: Settings,
                 bus: Optional[EventBus] = None, save_delay: float = 5.0,
                 clock=time.monotonic):
        self.engine = engine
        self.store = store
        self.settings = settings
        self.profiles = store.load_profiles()  # modèles de projecteurs disponibles (par nom de fichier)
        self.bus = bus or EventBus()
        # État de la liaison avec le pédalier (renseigné par PedalboardLink ; ``enabled`` : une liaison est configurée)
        self.pedalboard = {"enabled": False, "connected": False, "port": None, "version": None}
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
            plan = self.engine.plan
            base = self.engine.base_states()
            return {
                "fixtures": [fixture_json(f) for f in plan.fixtures],
                "profiles": self._profiles_json(plan),
                "dmx": {"channels": plan.channel_count(), "size": UNIVERSE_SIZE},
                "pedalboard": dict(self.pedalboard),
                "scenes": [s.to_dict() for s in self.engine.scenes.values()],
                "sequences": [s.to_dict() for s in self.engine.sequences.values()],
                "settings": self.settings.to_dict(),
                "status": self.status(),
                "current": {fid: st.to_dict() for fid, st in base.items()},
            }

    def _profiles_json(self, plan: Plan) -> dict:
        """Modèles disponibles : modes, rôle de chaque canal, et première adresse libre."""
        out = {}
        for key, p in self.profiles.items():
            modes = {}
            for name, m in p.modes.items():
                modes[name] = {"size": m.size, "next_address": plan.free_address(m.size),
                               "channels": [{"role": c.role, "default": c.default, "min": c.min,
                                             "max": c.max} for c in m.channels]}
            out[key] = {"name": p.name, "manufacturer": p.manufacturer, "modes": modes,
                        "origin": self.store.profile_origin(key),
                        "has_bundled": self.store.bundled_profile_path(key) is not None}
        return out

    # -- modèles de projecteurs : contrôle et intégration --------------------

    @staticmethod
    def _layout(profile) -> Dict[str, list]:
        return {name: [(c.role, c.default, c.min, c.max) for c in m.channels]
                for name, m in profile.modes.items()}

    def check_profile(self, key: str, data) -> dict:
        """Contrôle un modèle avant intégration, sans rien modifier.

        Renvoie ``ok`` (aucune erreur bloquante), les ``errors`` bloquantes, les ``warnings``, la liste
        des ``changes`` par rapport au modèle de même identifiant, les projecteurs ``impacted`` et un
        aperçu ``profile`` (modes et canaux).
        """
        if not valid_profile_key(key):
            raise ValueError("identifiant de modèle invalide (lettres minuscules, chiffres, - et _, 60 caractères au plus)")
        report = {"key": key, "exists": key in self.profiles, "ok": False, "errors": [], "warnings": [],
                  "changes": [], "impacted": [], "profile": None}
        try:
            new = profile_from_dict(data)
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            report["errors"].append(f"modèle invalide : {exc}")
            return report
        with self._lock, self.engine.lock:
            plan = self.engine.plan
            report["profile"] = {"name": new.name, "manufacturer": new.manufacturer, "modes": {
                name: {"size": m.size, "channels": [{"role": c.role, "default": c.default, "min": c.min,
                                                     "max": c.max} for c in m.channels]}
                for name, m in new.modes.items()}}
            old = self.profiles.get(key)
            if old is not None:
                if old.name != new.name:
                    report["changes"].append(f"nom : « {old.name} » devient « {new.name} »")
                old_l, new_l = self._layout(old), self._layout(new)
                for mode in old_l.keys() - new_l.keys():
                    report["changes"].append(f"mode {mode} supprimé")
                for mode in new_l.keys() - old_l.keys():
                    report["changes"].append(f"mode {mode} ajouté ({len(new_l[mode])} canaux)")
                for mode in old_l.keys() & new_l.keys():
                    if old_l[mode] != new_l[mode]:
                        a, b = len(old_l[mode]), len(new_l[mode])
                        report["changes"].append(f"mode {mode} : " + (f"{a} → {b} canaux" if a != b
                                                                      else "fonctions des canaux modifiées"))
                if not report["changes"]:
                    report["warnings"].append("identique au modèle actuel : rien à changer")
            for other_key, other in self.profiles.items():
                if other_key != key and other.name == new.name:
                    report["warnings"].append(f"même nom que le modèle « {other_key} »")
            users = [f for f in plan.fixtures if f.profile_key == key]
            report["impacted"] = [f.name for f in users]
            for f in users:
                if f.mode_name not in new.modes:
                    report["errors"].append(f"« {f.name} » utilise le mode {f.mode_name}, absent du nouveau modèle")
            if users and not report["errors"]:
                trial = [Fixture(f.id, f.name, new if f.profile_key == key else f.profile, f.mode_name,
                                 f.address, f.profile_key) for f in plan.fixtures]
                try:
                    Plan(trial)
                except ValueError as exc:
                    report["errors"].append(f"le plan de feu ne tiendrait plus : {exc}")
        report["ok"] = not report["errors"]
        return report

    def delete_profile(self, key: str) -> dict:
        """Supprime la version personnalisée d'un modèle.

        Si le dépôt fournit ce modèle, on **revient à la version fournie** (après avoir vérifié qu'elle
        convient au plan de feu). Sinon le modèle disparaît, à condition qu'aucun projecteur ne l'utilise.
        """
        if not valid_profile_key(key) or key not in self.profiles:
            raise KeyError(key)
        if self.store.profile_origin(key) != "custom":
            raise Conflict("modèle fourni avec le dépôt : il ne peut pas être supprimé")
        with self._lock, self.engine.lock:
            plan = self.engine.plan
            users = [f for f in plan.fixtures if f.profile_key == key]
            bundled_path = self.store.bundled_profile_path(key)
            if bundled_path is None:
                if users:
                    raise Conflict("modèle utilisé par : " + ", ".join(f.name for f in users))
            else:
                with open(bundled_path, encoding="utf-8") as f:
                    rep = self.check_profile(key, json.load(f))
                if not rep["ok"]:
                    raise Conflict("la version fournie ne convient pas au plan de feu : " + " ; ".join(rep["errors"]))
            self.store.delete_custom_profile(key)
            self.profiles = self.store.load_profiles()
            if users and bundled_path is not None:
                back = self.profiles[key]
                self.engine.set_plan(Plan([Fixture(f.id, f.name, back if f.profile_key == key else f.profile,
                                                   f.mode_name, f.address, f.profile_key)
                                           for f in plan.fixtures]))
        self._changed()
        return {"key": key, "reverted": bundled_path is not None}

    def save_profile(self, key: str, data) -> dict:
        """Intègre un modèle contrôlé : fichier du répertoire de données, plan de feu mis à jour à chaud."""
        report = self.check_profile(key, data)
        if not report["ok"]:
            raise ValueError(" ; ".join(report["errors"]))
        with self._lock, self.engine.lock:
            self.store.save_profile(key, data)
            self.profiles = self.store.load_profiles()
            new = self.profiles[key]
            plan = self.engine.plan
            if any(f.profile_key == key for f in plan.fixtures):
                self.engine.set_plan(Plan([Fixture(f.id, f.name, new if f.profile_key == key else f.profile,
                                                   f.mode_name, f.address, f.profile_key)
                                           for f in plan.fixtures]))
        self._changed()
        return report

    def set_pedalboard(self, **info) -> None:
        """Met à jour l'état de la liaison avec le pédalier et le diffuse à l'interface."""
        with self._lock:
            if all(self.pedalboard.get(k) == v for k, v in info.items()):
                return
            self.pedalboard.update(info)
            self.bus.publish("pedalboard", dict(self.pedalboard))

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

    def apply_states(self, states: dict) -> Dict[str, FixtureState]:
        """Applique des états complets, un par projecteur (aperçu d'une scène en édition, retour à
        l'état d'avant). Tout est validé avant d'appliquer quoi que ce soit."""
        with self.engine.lock:
            parsed = {}
            for fid, raw in states.items():
                self.engine.plan.get(fid)  # KeyError si inconnu
                parsed[fid] = FixtureState.from_dict(raw)
            for fid, st in parsed.items():
                self.engine.set_state(fid, st)
        self.poll()
        return parsed

    def reorder_scenes(self, ids: List[str]) -> None:
        """Change l'ordre de présentation des scènes (``ids`` : toutes les scènes, dans le nouvel ordre)."""
        with self.engine.lock:
            if len(set(ids)) != len(ids) or set(ids) != set(self.engine.scenes):
                raise ValueError("la liste doit contenir chaque scène existante exactement une fois")
            ordered = [self.engine.scenes[i] for i in ids]
            self.engine.scenes.clear()
            self.engine.scenes.update((s.id, s) for s in ordered)
            self.store.save_scenes(self.engine.scenes)
        self._changed()

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

    def save_fixture(self, fixture_id: Optional[str], data: dict) -> Fixture:
        """Ajoute (``fixture_id`` vide) ou modifie un projecteur du plan de feu.

        ``data`` : ``name``, ``profile`` (clé du modèle), ``mode``, ``address`` (optionnelle : à la
        création, première adresse libre). Le plan est validé en entier avant d'être appliqué.
        """
        with self._lock, self.engine.lock:
            plan = self.engine.plan
            existing = next((f for f in plan.fixtures if f.id == fixture_id), None) if fixture_id else None
            if fixture_id and existing is None:
                raise KeyError(fixture_id)
            name = str(data.get("name", existing.name if existing else "")).strip()
            if not name:
                raise ValueError("nom requis")
            key = data.get("profile", existing.profile_key if existing else None)
            if key not in self.profiles:
                raise ValueError(f"modèle inconnu : {key!r}")
            profile = self.profiles[key]
            mode_name = data.get("mode", existing.mode_name if existing else None)
            size = profile.mode(mode_name).size  # ValueError si le mode n'existe pas
            address = data.get("address")
            if address is None:
                address = existing.address if existing else plan.free_address(size)
            if address is None:
                raise ValueError("plus de place dans l'univers DMX (512 canaux)")
            try:
                address = int(address)
            except (TypeError, ValueError):
                raise ValueError("adresse DMX invalide") from None
            if fixture_id is None:
                base_id, i = slugify(name), 1
                taken = {f.id for f in plan.fixtures} | {"state"}  # « state » est une route de l'API
                fixture_id = base_id
                while fixture_id in taken:
                    i += 1
                    fixture_id = f"{base_id}-{i}"
            new = Fixture(fixture_id, name, profile, mode_name, address, key)
            fixtures = [new if f.id == fixture_id else f for f in plan.fixtures]
            if existing is None:
                fixtures.append(new)
            new_plan = Plan(fixtures)  # ValueError : chevauchement, hors univers
            self.store.save_plan(new_plan.to_spec())
            self.engine.set_plan(new_plan)
        self._changed()
        return new

    def delete_fixture(self, fixture_id: str) -> None:
        """Retire un projecteur du plan. Les scènes gardent son état, ignoré tant qu'il est absent."""
        with self._lock, self.engine.lock:
            plan = self.engine.plan
            if not any(f.id == fixture_id for f in plan.fixtures):
                raise KeyError(fixture_id)
            new_plan = Plan([f for f in plan.fixtures if f.id != fixture_id])
            self.store.save_plan(new_plan.to_spec())
            self.engine.set_plan(new_plan)
        self._changed()

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
