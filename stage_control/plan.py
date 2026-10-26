"""Plan de feu : projecteurs, adresses DMX, validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from .profile import Mode, Profile

UNIVERSE_SIZE = 512


@dataclass(frozen=True)
class Fixture:
    id: str
    name: str
    profile: Profile
    mode_name: str
    address: int  # 1..512, premier canal

    @property
    def mode(self) -> Mode:
        return self.profile.mode(self.mode_name)

    @property
    def end(self) -> int:
        """Dernier canal occupé (inclus)."""
        return self.address + self.mode.size - 1


class Plan:
    def __init__(self, fixtures: Iterable[Fixture]):
        self.fixtures: List[Fixture] = list(fixtures)
        self.validate()

    def validate(self) -> None:
        seen: Dict[str, Fixture] = {}
        for f in self.fixtures:
            if f.id in seen:
                raise ValueError(f"identifiant en double : {f.id!r}")
            seen[f.id] = f
            f.mode  # lève ValueError si le mode n'existe pas
            if f.address < 1 or f.end > UNIVERSE_SIZE:
                raise ValueError(
                    f"{f.id!r} : canaux {f.address}..{f.end} hors de l'univers (1..{UNIVERSE_SIZE})"
                )
        ordered = sorted(self.fixtures, key=lambda f: f.address)
        for a, b in zip(ordered, ordered[1:]):
            if b.address <= a.end:
                raise ValueError(
                    f"chevauchement : {a.id!r} ({a.address}..{a.end}) et {b.id!r} ({b.address}..{b.end})"
                )

    def get(self, fixture_id: str) -> Fixture:
        for f in self.fixtures:
            if f.id == fixture_id:
                return f
        raise KeyError(fixture_id)

    def channel_count(self) -> int:
        """Nombre de canaux à émettre (dernier canal utilisé)."""
        return max((f.end for f in self.fixtures), default=0)
