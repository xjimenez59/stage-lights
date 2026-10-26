"""Persistance JSON : plan de feu, scènes, séquences, réglages (voir spécification §8).

Répertoire de données :
    fixtures.json    plan de feu
    scenes.json      bibliothèque de scènes (l'ordre compte : la première sert de repli)
    sequences.json   séquences
    settings.json    intensité générale, fondus, affectation des pédales, dernière scène
    profiles/*.json  profils propres à l'installation (complètent ceux du dépôt)

Écriture atomique (fichier temporaire, ``fsync``, renommage) avec copie ``.bak`` de la
version précédente. À la lecture, un fichier illisible est remplacé par sa copie ``.bak``.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .engine import CURVES, Engine
from .plan import Fixture, Plan
from .profile import Profile, load_profile
from .scene import Scene
from .sequence import Sequence

log = logging.getLogger("stage_control.store")

_PROFILE_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")


def valid_profile_key(key: str) -> bool:
    """Un identifiant de modèle devient un nom de fichier : on n'accepte rien d'autre que ceci."""
    return isinstance(key, str) and bool(_PROFILE_KEY.match(key))


PEDAL_SLOTS = 6
PEDAL_TYPES = ("none", "scene", "sequence", "flash", "next", "prev")
_NEEDS_TARGET = ("scene", "sequence", "flash")


def write_json_atomic(path: str, obj: Any) -> None:
    """Écrit ``obj`` dans ``path`` sans jamais laisser un fichier à moitié écrit."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        shutil.copyfile(path, path + ".bak")
    os.replace(tmp, path)


def read_json(path: str, default: Any) -> Any:
    """Lit un JSON ; absent : ``default`` ; illisible : copie ``.bak`` si possible, sinon erreur."""
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        bak = path + ".bak"
        if os.path.exists(bak):
            log.error("%s illisible (%s) : utilisation de %s", path, exc, bak)
            with open(bak, encoding="utf-8") as f:
                return json.load(f)
        raise ValueError(f"{path} illisible et sans copie .bak : {exc}") from exc


@dataclass(frozen=True)
class PedalAction:
    type: str = "none"
    target: Optional[str] = None  # id de scène ou de séquence

    def __post_init__(self):
        if self.type not in PEDAL_TYPES:
            raise ValueError(f"action de pédale inconnue : {self.type!r} ({', '.join(PEDAL_TYPES)})")
        if self.type in _NEEDS_TARGET and not self.target:
            raise ValueError(f"l'action {self.type!r} demande une cible")


@dataclass
class Settings:
    master: float = 1.0
    default_fade: float = 1.0
    blackout_fade: float = 1.0
    flash_fade: float = 0.1
    curve: str = "smoothstep"
    universe: int = 0
    rate_hz: float = 40.0
    last_scene: Optional[str] = None
    pedals: List[PedalAction] = field(default_factory=lambda: [PedalAction() for _ in range(PEDAL_SLOTS)])

    def __post_init__(self):
        if not 0.0 <= self.master <= 1.0:
            raise ValueError("master hors 0..1")
        for name in ("default_fade", "blackout_fade", "flash_fade"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} négatif")
        if self.curve not in CURVES:
            raise ValueError(f"courbe inconnue : {self.curve!r}")
        if self.rate_hz <= 0:
            raise ValueError("rate_hz doit être > 0")
        if len(self.pedals) > PEDAL_SLOTS:
            raise ValueError(f"{PEDAL_SLOTS} emplacements de pédale au maximum")
        self.pedals = list(self.pedals) + [PedalAction()] * (PEDAL_SLOTS - len(self.pedals))

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        known = {k: d[k] for k in ("master", "default_fade", "blackout_fade", "flash_fade", "curve",
                                   "universe", "rate_hz", "last_scene") if k in d}
        pedals = [PedalAction(p.get("type", "none"), p.get("target")) for p in d.get("pedals", [])]
        return cls(pedals=pedals, **known) if pedals else cls(**known)

    def to_dict(self) -> dict:
        return {"master": self.master, "default_fade": self.default_fade,
                "blackout_fade": self.blackout_fade, "flash_fade": self.flash_fade,
                "curve": self.curve, "universe": self.universe, "rate_hz": self.rate_hz,
                "last_scene": self.last_scene,
                "pedals": [{"type": p.type, "target": p.target} for p in self.pedals]}


class Store:
    def __init__(self, data_dir: str, profiles_dir: Optional[str] = None):
        self.data_dir = data_dir
        self.bundled_dir = profiles_dir  # modèles fournis avec le dépôt (jamais modifiés)
        # Profils du dépôt (par défaut ./profiles), complétés par ceux du répertoire de données.
        self.profiles_dirs = [d for d in (profiles_dir, os.path.join(data_dir, "profiles")) if d]

    def _path(self, name: str) -> str:
        return os.path.join(self.data_dir, name)

    # -- profils et plan ---------------------------------------------------

    def load_profiles(self) -> Dict[str, Profile]:
        """Profils par nom de fichier (sans extension) ; le répertoire de données l'emporte."""
        out: Dict[str, Profile] = {}
        for d in self.profiles_dirs:
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".json"):
                    out[fn[:-5]] = load_profile(os.path.join(d, fn))
        return out

    def profile_path(self, key: str) -> Optional[str]:
        """Fichier d'un modèle (celui du répertoire de données l'emporte sur celui du dépôt)."""
        if not valid_profile_key(key):
            return None
        found = None
        for d in self.profiles_dirs:
            path = os.path.join(d, key + ".json")
            if os.path.isfile(path):
                found = path
        return found

    def profile_origin(self, key: str) -> str:
        """``custom`` : fichier du répertoire de données ; ``bundled`` : fichier fourni avec le dépôt."""
        path = self.profile_path(key)
        custom_dir = os.path.abspath(os.path.join(self.data_dir, "profiles"))
        return "custom" if path and os.path.abspath(os.path.dirname(path)) == custom_dir else "bundled"

    def read_profile_raw(self, key: str) -> bytes:
        path = self.profile_path(key)
        if path is None:
            raise KeyError(key)
        with open(path, "rb") as f:
            return f.read()

    def save_profile(self, key: str, data: dict) -> None:
        """Enregistre un modèle dans le répertoire de données (il remplace celui du dépôt)."""
        if not valid_profile_key(key):
            raise ValueError("identifiant de modèle invalide (lettres minuscules, chiffres, - et _)")
        write_json_atomic(os.path.join(self.data_dir, "profiles", key + ".json"), data)

    def bundled_profile_path(self, key: str) -> Optional[str]:
        """Version fournie avec le dépôt d'un modèle (qu'il soit ou non masqué par une version personnalisée)."""
        if not self.bundled_dir or not valid_profile_key(key):
            return None
        path = os.path.join(self.bundled_dir, key + ".json")
        return path if os.path.isfile(path) else None

    def delete_custom_profile(self, key: str) -> None:
        """Supprime la version personnalisée d'un modèle ; une copie ``.bak`` du fichier supprimé est gardée."""
        if self.profile_origin(key) != "custom":
            raise ValueError(f"le modèle {key!r} n'est pas personnalisé")
        path = self.profile_path(key)
        os.replace(path, path + ".bak")

    def export_profiles_zip(self) -> bytes:
        """Tous les modèles disponibles, un fichier JSON par modèle, dans une archive."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for key in sorted(self.load_profiles()):
                z.writestr(key + ".json", self.read_profile_raw(key))
        return buf.getvalue()

    def load_plan(self) -> Plan:
        profiles = self.load_profiles()
        fixtures = []
        for raw in read_json(self._path("fixtures.json"), {"fixtures": []}).get("fixtures", []):
            key = raw["profile"]
            if key not in profiles:
                raise ValueError(f"projecteur {raw.get('id')!r} : profil inconnu {key!r}")
            fixtures.append(Fixture(raw["id"], raw.get("name", raw["id"]), profiles[key],
                                    raw["mode"], int(raw["address"]), key))
        return Plan(fixtures)

    def save_plan(self, plan_spec: List[dict]) -> None:
        """``plan_spec`` : liste de {id, name, profile, mode, address} (validée avant écriture)."""
        write_json_atomic(self._path("fixtures.json"), {"fixtures": plan_spec})

    # -- scènes, séquences, réglages --------------------------------------

    def load_scenes(self) -> Dict[str, Scene]:
        raw = read_json(self._path("scenes.json"), {"scenes": []}).get("scenes", [])
        scenes = [Scene.from_dict(s) for s in raw]
        return {s.id: s for s in scenes}

    def save_scenes(self, scenes: Dict[str, Scene]) -> None:
        write_json_atomic(self._path("scenes.json"), {"scenes": [s.to_dict() for s in scenes.values()]})

    def load_sequences(self) -> Dict[str, Sequence]:
        raw = read_json(self._path("sequences.json"), {"sequences": []}).get("sequences", [])
        seqs = [Sequence.from_dict(s) for s in raw]
        return {s.id: s for s in seqs}

    def save_sequences(self, sequences: Dict[str, Sequence]) -> None:
        write_json_atomic(self._path("sequences.json"),
                          {"sequences": [s.to_dict() for s in sequences.values()]})

    def load_settings(self) -> Settings:
        return Settings.from_dict(read_json(self._path("settings.json"), {}))

    def save_settings(self, settings: Settings) -> None:
        write_json_atomic(self._path("settings.json"), settings.to_dict())

    # -- assemblage --------------------------------------------------------

    def build_engine(self, **engine_kwargs) -> "tuple[Engine, Settings]":
        """Construit le moteur à partir des fichiers (démarre en blackout sur la dernière scène)."""
        settings = self.load_settings()
        scenes = self.load_scenes()
        sequences = self.load_sequences()
        for seq in sequences.values():
            for step in seq.steps:
                if step.scene not in scenes:
                    log.warning("séquence %r : scène inconnue %r", seq.id, step.scene)
        engine = Engine(self.load_plan(), scenes, sequences=sequences,
                        default_fade=settings.default_fade, blackout_fade=settings.blackout_fade,
                        flash_fade=settings.flash_fade, curve=settings.curve,
                        initial_scene=settings.last_scene, master=settings.master, **engine_kwargs)
        return engine, settings
