"""Profils de projecteurs : modes et rôle de chaque canal DMX.

Un profil décrit un modèle ; il ne contient aucune adresse. Les valeurs des
canaux propres à un modèle (stroboscope, macros...) viennent de sa notice et
sont saisies dans le fichier JSON du profil, jamais déduites.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List

# Rôles pilotés par une scène.
COLOR_ROLES = ("red", "green", "blue", "white", "amber")
# Rôles reconnus mais non pilotés en v1 : ils gardent leur valeur par défaut.
FIXED_ROLES = ("uv", "strobe", "macro", "speed", "other")
# Réservés pour les projecteurs à mouvement (hors v1).
MOTION_ROLES = ("pan", "tilt")
ROLES = ("intensity",) + COLOR_ROLES + FIXED_ROLES + MOTION_ROLES


@dataclass(frozen=True)
class Channel:
    role: str
    default: int = 0  # valeur DMX 0..255 quand le canal n'est pas piloté
    # Plage DMX « active » d'un canal à intensité variable (stroboscope : la
    # notice ne l'active qu'à partir d'une certaine valeur). Sans plage : 1..255.
    min: int = 1
    max: int = 255


@dataclass(frozen=True)
class Mode:
    name: str
    channels: List[Channel] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.channels)

    def has(self, role: str) -> bool:
        return any(c.role == role for c in self.channels)


@dataclass(frozen=True)
class Profile:
    name: str
    manufacturer: str
    modes: Dict[str, Mode]

    def mode(self, name: str) -> Mode:
        try:
            return self.modes[name]
        except KeyError:
            raise ValueError(
                f"profil {self.name!r} : mode inconnu {name!r} (modes : {', '.join(self.modes)})"
            ) from None


def profile_from_dict(data: dict) -> Profile:
    name = data.get("name")
    if not name:
        raise ValueError("profil sans nom")
    modes: Dict[str, Mode] = {}
    for mode_name, raw in (data.get("modes") or {}).items():
        channels: List[Channel] = []
        for i, ch in enumerate(raw.get("channels", []), start=1):
            role = ch.get("role")
            if role not in ROLES:
                raise ValueError(f"profil {name!r}, mode {mode_name!r}, canal {i} : rôle inconnu {role!r}")
            default = int(ch.get("default", 0))
            if not 0 <= default <= 255:
                raise ValueError(f"profil {name!r}, mode {mode_name!r}, canal {i} : défaut hors 0..255")
            lo, hi = int(ch.get("min", 1)), int(ch.get("max", 255))
            if not 0 <= lo <= hi <= 255:
                raise ValueError(f"profil {name!r}, mode {mode_name!r}, canal {i} : plage min/max invalide")
            channels.append(Channel(role, default, lo, hi))
        if not channels:
            raise ValueError(f"profil {name!r}, mode {mode_name!r} : aucun canal")
        roles = [c.role for c in channels if c.role in ("intensity",) + COLOR_ROLES]
        if len(roles) != len(set(roles)):
            raise ValueError(f"profil {name!r}, mode {mode_name!r} : rôle répété")
        modes[mode_name] = Mode(mode_name, channels)
    if not modes:
        raise ValueError(f"profil {name!r} : aucun mode")
    return Profile(name, data.get("manufacturer", ""), modes)


def load_profile(path: str) -> Profile:
    with open(path, encoding="utf-8") as f:
        return profile_from_dict(json.load(f))
