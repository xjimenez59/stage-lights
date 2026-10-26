"""Scènes : état abstrait (couleur, blanc, ambre, intensité) par projecteur."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


def _unit(value: float, what: str) -> float:
    v = float(value)
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"{what} hors 0..1 : {value}")
    return v


@dataclass(frozen=True)
class FixtureState:
    """Valeurs de 0.0 à 1.0, indépendantes des canaux du projecteur."""

    rgb: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    white: float = 0.0
    amber: float = 0.0
    intensity: float = 0.0
    strobe: float = 0.0  # 0 = pas de stroboscope, puis vitesse croissante jusqu'à 1

    def __post_init__(self):
        if len(self.rgb) != 3:
            raise ValueError("rgb doit avoir 3 composantes")
        for c in self.rgb:
            _unit(c, "composante rgb")
        _unit(self.white, "blanc")
        _unit(self.amber, "ambre")
        _unit(self.intensity, "intensité")
        _unit(self.strobe, "stroboscope")

    @classmethod
    def from_dict(cls, d: dict) -> "FixtureState":
        return cls(tuple(d.get("rgb", (0, 0, 0))), d.get("white", 0.0),
                   d.get("amber", 0.0), d.get("intensity", 0.0), d.get("strobe", 0.0))

    def to_dict(self) -> dict:
        return {"rgb": list(self.rgb), "white": self.white,
                "amber": self.amber, "intensity": self.intensity, "strobe": self.strobe}


@dataclass
class Scene:
    id: str
    name: str
    fade_s: float | None = None  # None : temps de fondu par défaut global
    states: Dict[str, FixtureState] = field(default_factory=dict)  # par id de projecteur

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        fade = d.get("fade_s")
        if fade is not None and float(fade) < 0:
            raise ValueError("fade_s négatif")
        return cls(d["id"], d.get("name", d["id"]), None if fade is None else float(fade),
                   {fid: FixtureState.from_dict(s) for fid, s in d.get("states", {}).items()})

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "fade_s": self.fade_s,
                "states": {fid: s.to_dict() for fid, s in self.states.items()}}
