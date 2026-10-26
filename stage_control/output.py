"""Sortie DMX : envoie l'univers du moteur en Art-Net (UDP) vers le démon ``spi_dmx``.

La boucle émet à cadence fixe, indépendamment des requêtes web ou du pédalier. Si le
contrôleur ralentit ou s'arrête, ``spi_dmx`` continue d'émettre la dernière trame reçue.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Callable, Optional

from spi_dmx import artnet

from .engine import Engine

log = logging.getLogger("stage_control.output")


class ArtnetSender:
    def __init__(self, host: str = "127.0.0.1", port: int = artnet.ARTNET_PORT, universe: int = 0):
        self.addr = (host, port)
        self.universe = universe
        self._seq = 0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, data: bytes) -> None:
        # Le numéro de séquence Art-Net va de 1 à 255 (0 = désactivé).
        self._seq = self._seq % 255 + 1
        self._sock.sendto(artnet.build_artdmx(self.universe, data, self._seq), self.addr)

    def close(self) -> None:
        self._sock.close()


class OutputLoop(threading.Thread):
    """Appelle ``engine.frame()`` ``rate_hz`` fois par seconde et envoie le résultat."""

    def __init__(self, engine: Engine, sender: ArtnetSender, rate_hz: float = 40.0,
                 channels: Optional[int] = None,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__(daemon=True, name="dmx-output")
        if rate_hz <= 0:
            raise ValueError("rate_hz doit être > 0")
        self.engine = engine
        self.sender = sender
        self.period = 1.0 / rate_hz
        # Nombre de canaux émis : jusqu'au dernier utilisé (2 au minimum : longueur paire Art-Net).
        self.channels = channels if channels is not None else max(2, engine.plan.channel_count())
        self._clock = clock
        self._halt = threading.Event()
        self.sent = 0
        self.errors = 0

    def tick(self) -> None:
        try:
            self.sender.send(self.engine.frame()[: self.channels])
            self.sent += 1
        except OSError as exc:  # réseau indisponible : on continue au tick suivant
            self.errors += 1
            if self.errors == 1 or self.errors % 400 == 0:
                log.warning("envoi Art-Net impossible : %s", exc)

    def run(self) -> None:
        next_t = self._clock()
        while not self._halt.is_set():
            self.tick()
            next_t += self.period
            delay = next_t - self._clock()
            if delay > 0:
                self._halt.wait(delay)
            else:
                next_t = self._clock()  # en retard : on ne rattrape pas

    def stop(self) -> None:
        self._halt.set()
