"""Liaison avec le pédalier USB (voir docs/pedalier/protocole.md).

Protocole texte, une ligne par message, terminée par ``\\n`` :

    pédalier -> Pi   HELLO <version> <nb de pédales>   réponse à WHO, ou à la mise sous tension
                     BTN <n> <1|0>                      appui (1) / relâchement (0), n de 1 à 7
                     PONG                               réponse à PING
    Pi -> pédalier   WHO                                « qui es-tu ? » (au début de la session)
                     PING                               toutes les 2 s : sans réponse, la liaison est jugée morte
                     LED <6 chiffres> <b>               LED des 6 emplacements, puis LED du blackout

Le Pi relance la liaison tout seul (câble débranché, pédalier redémarré). Si la liaison tombe pendant
qu'une pédale est enfoncée, les pédales sont relâchées : un flash ne reste jamais allumé.
"""

from __future__ import annotations

import glob
import logging
import os
import queue
import select
import socket
import threading
import time
from typing import Callable, List, Optional

from .controller import BLACKOUT_PEDAL, Controller

log = logging.getLogger("stage_control.pedalboard")

MAX_LINE = 64


class Transport:
    """Un canal d'octets : ``read`` renvoie ``b""`` à l'expiration du délai, lève ``EOFError`` si la liaison est fermée."""

    def read(self, timeout: float) -> bytes:
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SerialTransport(Transport):
    """Port série USB (puce USB-série ou CDC) ouvert en mode brut avec ``termios`` (bibliothèque standard, Linux)."""

    def __init__(self, path: str):
        import termios
        import tty

        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            tty.setraw(self.fd)
            attrs = termios.tcgetattr(self.fd)
            attrs[2] &= ~termios.HUPCL  # ne pas baisser DTR à la fermeture
            attrs[4] = attrs[5] = termios.B115200  # sans effet sur l'USB natif, requis avec une puce USB-série
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        except Exception:
            os.close(self.fd)
            raise

    def read(self, timeout: float) -> bytes:
        try:
            ready, _, _ = select.select([self.fd], [], [], timeout)
            if not ready:
                return b""
            data = os.read(self.fd, 256)
        except OSError as exc:
            raise EOFError(str(exc)) from exc
        if not data:
            raise EOFError("port fermé")
        return data

    def write(self, data: bytes) -> None:
        try:
            os.write(self.fd, data)
        except BlockingIOError:
            pass  # tampon plein : le prochain message d'état remplacera celui-ci
        except OSError as exc:
            raise EOFError(str(exc)) from exc

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass


class SocketTransport(Transport):
    """Connexion TCP : sert à essayer le logiciel sans matériel (voir ``tools/pedalboard_sim.py``)."""

    def __init__(self, host: str, port: int):
        self.sock = socket.create_connection((host, port), timeout=2.0)
        self.sock.settimeout(None)

    def read(self, timeout: float) -> bytes:
        try:
            ready, _, _ = select.select([self.sock], [], [], timeout)
            if not ready:
                return b""
            data = self.sock.recv(256)
        except OSError as exc:
            raise EOFError(str(exc)) from exc
        if not data:
            raise EOFError("connexion fermée")
        return data

    def write(self, data: bytes) -> None:
        try:
            self.sock.sendall(data)
        except OSError as exc:
            raise EOFError(str(exc)) from exc

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def open_transport(target: str) -> Transport:
    if target.startswith("tcp:"):
        host, _, port = target[4:].rpartition(":")
        return SocketTransport(host or "127.0.0.1", int(port))
    return SerialTransport(target)


def resolve_targets(spec: str) -> List[str]:
    """``auto`` : les ports ``/dev/ttyACM*`` et ``/dev/ttyUSB*`` présents ; sinon le chemin (ou ``tcp:hôte:port``) donné."""
    if spec == "auto":
        return sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    return [spec]


def format_leds(leds: dict) -> str:
    return "LED " + "".join("1" if on else "0" for on in leds["slots"]) + " " + ("1" if leds["blackout"] else "0")


class PedalboardLink(threading.Thread):
    def __init__(self, controller: Controller, spec: str, *,
                 opener: Callable[[str], Transport] = open_transport,
                 ping_s: float = 2.0, dead_s: float = 6.0, hello_s: float = 3.0, retry_s: float = 2.0,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__(daemon=True, name="pedalboard")
        self.controller = controller
        self.spec = spec
        self._opener = opener
        self.ping_s, self.dead_s, self.hello_s, self.retry_s = ping_s, dead_s, hello_s, retry_s
        self._clock = clock
        self._halt = threading.Event()
        self.down: set = set()  # pédales actuellement enfoncées
        self.ignored = 0  # lignes reçues non comprises
        controller.set_pedalboard(enabled=True, connected=False, port=None, version=None)

    def stop(self) -> None:
        self._halt.set()

    # -- boucle de connexion -----------------------------------------------

    def run(self) -> None:
        while not self._halt.is_set():
            for target in resolve_targets(self.spec):
                if self._halt.is_set():
                    break
                try:
                    transport = self._opener(target)
                except (OSError, ValueError, ImportError) as exc:
                    log.debug("pédalier : ouverture de %s impossible : %s", target, exc)
                    continue
                try:
                    self._session(transport, target)
                finally:
                    transport.close()
                    self._release_all()
                    self.controller.set_pedalboard(connected=False, port=None, version=None)
            self._halt.wait(self.retry_s)

    def _release_all(self) -> None:
        for n in sorted(self.down):
            try:
                self.controller.pedal(n, False)
            except Exception:
                log.exception("relâchement de la pédale %d", n)
        self.down.clear()

    # -- une session -------------------------------------------------------

    def _session(self, transport: Transport, target: str) -> None:
        buf = b""
        queue_ = self.controller.bus.subscribe()
        version: Optional[str] = None
        try:
            now = self._clock()
            start = last_rx = last_ping = now
            self._send(transport, "WHO")
            last_leds: Optional[str] = None
            while not self._halt.is_set():
                try:
                    chunk = transport.read(0.05)
                except EOFError as exc:
                    log.info("pédalier : liaison perdue (%s)", exc)
                    return
                now = self._clock()
                if chunk:
                    last_rx = now
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        hello = self._handle(line.strip().decode("ascii", "replace"))
                        if hello is not None:
                            version = hello
                            self.controller.set_pedalboard(connected=True, port=target, version=version)
                            log.info("pédalier connecté sur %s (version %s)", target, version)
                            last_leds = None  # (re)envoi de l'état complet
                    if len(buf) > MAX_LINE:
                        buf = b""  # pas de fin de ligne : on repart de zéro
                if version is None:
                    if now - start > self.hello_s:
                        log.debug("pédalier : %s ne répond pas à WHO", target)
                        return
                    continue
                if now - last_rx > self.dead_s:
                    log.warning("pédalier : plus de réponse depuis %.0f s, liaison relancée", self.dead_s)
                    return
                if now - last_ping >= self.ping_s:
                    self._send(transport, "PING")
                    last_ping = now
                msg = self._pending_leds(queue_)
                if msg is not None and msg != last_leds:
                    self._send(transport, msg)
                    last_leds = msg
                elif last_leds is None:
                    last_leds = format_leds(self.controller.status()["leds"])
                    self._send(transport, last_leds)
        except EOFError as exc:
            log.info("pédalier : liaison perdue (%s)", exc)
        finally:
            self.controller.bus.unsubscribe(queue_)

    def _pending_leds(self, q: "queue.Queue") -> Optional[str]:
        """Dernier état de LED publié depuis le dernier passage (les intermédiaires sont inutiles)."""
        msg = None
        while True:
            try:
                event, data = q.get_nowait()
            except queue.Empty:
                return msg
            if event == "status":
                msg = format_leds(data["leds"])

    @staticmethod
    def _send(transport: Transport, line: str) -> None:
        transport.write((line + "\n").encode("ascii"))

    # -- messages reçus ----------------------------------------------------

    def _handle(self, line: str) -> Optional[str]:
        """Traite une ligne ; renvoie la version si c'est un HELLO."""
        parts = line.split()
        if not parts:
            return None
        cmd = parts[0]
        if cmd == "HELLO":
            return parts[1] if len(parts) > 1 else "?"
        if cmd == "PONG":
            return None
        if cmd == "BTN" and len(parts) == 3 and parts[1].isdigit() and parts[2] in ("0", "1"):
            n, down = int(parts[1]), parts[2] == "1"
            if not 1 <= n <= BLACKOUT_PEDAL:
                self.ignored += 1
                return None
            if down == (n in self.down):
                return None  # répétition : sans effet
            (self.down.add if down else self.down.discard)(n)
            try:
                self.controller.pedal(n, down)
            except Exception:  # une scène supprimée, par exemple : le pédalier ne doit jamais bloquer
                log.exception("pédale %d ignorée", n)
            return None
        self.ignored += 1
        return None
