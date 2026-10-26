"""Séquences : enchaînements de scènes (voir docs/specification-controleur.md §4.6).

Chaque étape donne une scène, un temps de fondu optionnel (sinon celui de la scène,
sinon le défaut global) et une condition de passage à l'étape suivante :
- ``hold_s`` = nombre : délai en secondes, **compté à partir de la fin du fondu** ;
- ``hold_s`` = ``None`` : manuel, l'étape dure jusqu'à une action « étape suivante ».
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Step:
    scene: str
    fade_s: Optional[float] = None
    hold_s: Optional[float] = None  # None : passage manuel

    def __post_init__(self):
        if self.fade_s is not None and self.fade_s < 0:
            raise ValueError("fade_s négatif")
        if self.hold_s is not None and self.hold_s < 0:
            raise ValueError("hold_s négatif")


@dataclass
class Sequence:
    id: str
    name: str
    steps: List[Step] = field(default_factory=list)
    loop: bool = False  # False : s'arrête sur la dernière scène

    def __post_init__(self):
        if not self.steps:
            raise ValueError(f"séquence {self.id!r} : aucune étape")
        if self.loop and all(s.hold_s is not None and s.hold_s + (s.fade_s or 0.0) <= 0
                             for s in self.steps):
            # Garde-fou : une boucle sans aucune durée tournerait à vide.
            raise ValueError(f"séquence {self.id!r} : boucle de durée nulle")

    @classmethod
    def from_dict(cls, d: dict) -> "Sequence":
        return cls(d["id"], d.get("name", d["id"]),
                   [Step(s["scene"], s.get("fade_s"), s.get("hold_s")) for s in d.get("steps", [])],
                   bool(d.get("loop", False)))

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "loop": self.loop,
                "steps": [{"scene": s.scene, "fade_s": s.fade_s, "hold_s": s.hold_s}
                          for s in self.steps]}
