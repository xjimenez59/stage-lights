"""Traduction d'états abstraits en canaux DMX.

Règles (voir docs/specification-controleur.md §4.4) :
- un canal absent du profil est ignoré (aucune simulation de blanc/ambre) ;
- si le mode a un canal ``intensity``, l'intensité effective y est envoyée et
  les canaux couleur gardent la couleur choisie ; sinon l'intensité effective
  multiplie les canaux rouge/vert/bleu/blanc/ambre ;
- l'intensité effective = intensité du projecteur × intensité générale ;
- le stroboscope (0..1) est ramené à la plage active du canal (``min``..``max`` du profil) ;
  à 0, le canal prend sa valeur par défaut (« aucune fonction »). Il n'est pas atténué par l'intensité ;
- les autres canaux non pilotés prennent la valeur par défaut du profil.
"""

from __future__ import annotations

from typing import Mapping

from .plan import Fixture, Plan, UNIVERSE_SIZE
from .scene import FixtureState

_RGB_INDEX = {"red": 0, "green": 1, "blue": 2}


def _to_dmx(value: float) -> int:
    return max(0, min(255, int(round(value * 255))))


def render_fixture(fixture: Fixture, state: FixtureState, master: float = 1.0) -> bytes:
    mode = fixture.mode
    effective = state.intensity * master
    has_intensity = mode.has("intensity")
    scale = 1.0 if has_intensity else effective
    out = bytearray(mode.size)
    for i, ch in enumerate(mode.channels):
        role = ch.role
        if role == "intensity":
            out[i] = _to_dmx(effective)
        elif role in _RGB_INDEX:
            out[i] = _to_dmx(state.rgb[_RGB_INDEX[role]] * scale)
        elif role == "white":
            out[i] = _to_dmx(state.white * scale)
        elif role == "amber":
            out[i] = _to_dmx(state.amber * scale)
        elif role == "strobe" and state.strobe > 0.0:
            out[i] = ch.min + int(round((ch.max - ch.min) * state.strobe))
        else:
            out[i] = ch.default
    return bytes(out)


def render(plan: Plan, states: Mapping[str, FixtureState], master: float = 1.0) -> bytes:
    """Renvoie l'univers complet (512 octets). Projecteur sans état : toutes ses
    couleurs et intensités à zéro (valeurs par défaut du profil pour le reste)."""
    if not 0.0 <= master <= 1.0:
        raise ValueError(f"intensité générale hors 0..1 : {master}")
    universe = bytearray(UNIVERSE_SIZE)
    empty = FixtureState()
    for f in plan.fixtures:
        data = render_fixture(f, states.get(f.id, empty), master)
        universe[f.address - 1:f.address - 1 + len(data)] = data
    return bytes(universe)
