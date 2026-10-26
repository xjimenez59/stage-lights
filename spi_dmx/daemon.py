"""Démon : reçoit de l'Art-Net (ArtDmx, UDP) et émet du DMX512 sur SPI0.

Usage typique sur le Pi (le contrôleur ``stage_control`` envoie de l'Art-Net vers la machine locale) ::

    python3 -m spi_dmx --universe 0 --channels 32 --rate 40

Le nombre de canaux émis peut être réduit (``--channels``) : 4 projecteurs en
mode 8 canaux n'en utilisent que 32, ce qui raccourcit la trame (~1,5 ms au
lieu de ~23 ms) et permet un rafraîchissement bien plus élevé.
"""

from __future__ import annotations

import argparse
import logging
import signal
import socket
import threading
import time

from . import artnet, frame

log = logging.getLogger("spi_dmx")


class DmxState:
    """Tampon DMX partagé entre le thread réseau et la boucle d'émission."""

    def __init__(self, n_channels: int, auto: bool = False):
        self.n = n_channels
        self.auto = auto  # True : le nombre de canaux suit la longueur des paquets reçus
        self._buf = bytearray(n_channels)
        self._lock = threading.Lock()
        self.last_rx = 0.0  # time.monotonic() du dernier paquet utile

    def update(self, data: bytes, now: float | None = None) -> None:
        with self._lock:
            if self.auto:
                size = max(1, min(len(data), frame.MAX_CHANNELS))
                if size != self.n:  # le plan de feu a changé : la trame suit
                    log.info("nombre de canaux émis : %d -> %d", self.n, size)
                    self.n = size
                    self._buf = bytearray(size)
            chunk = data[: self.n]
            self._buf[: len(chunk)] = chunk
            self.last_rx = time.monotonic() if now is None else now

    def snapshot(self) -> bytes:
        with self._lock:
            return bytes(self._buf)

    def blackout(self) -> None:
        with self._lock:
            self._buf[:] = bytes(self.n)


class SpiSink:
    """Sortie SPI0 (spidev). Importé paresseusement pour permettre les tests hors Pi."""

    def __init__(self, bus: int = 0, device: int = 0, speed_hz: int = 250_000):
        import spidev  # type: ignore

        self._spi = spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.mode = 0
        self._spi.bits_per_word = 8
        self._spi.max_speed_hz = speed_hz
        self.speed_hz = speed_hz

    def write(self, data: bytes) -> None:
        # writebytes2 accepte bytes et découpe selon la taille du buffer spidev
        # (4096 par défaut : une trame DMX de 513 slots ~ 709 octets tient en un bloc).
        self._spi.writebytes2(data)

    def close(self) -> None:
        self._spi.close()


class FileSink:
    """Sortie de débogage : écrit chaque trame dans un fichier (``--dry-run``)."""

    def __init__(self, path: str):
        self._f = open(path, "wb")

    def write(self, data: bytes) -> None:
        self._f.write(data)
        self._f.flush()

    def close(self) -> None:
        self._f.close()


class NullSink:
    def __init__(self):
        self.frames = 0

    def write(self, data: bytes) -> None:
        self.frames += 1

    def close(self) -> None:
        pass


class ArtnetReceiver(threading.Thread):
    def __init__(self, state: DmxState, universe: int, bind: str = "0.0.0.0",
                 port: int = artnet.ARTNET_PORT):
        super().__init__(daemon=True, name="artnet-rx")
        self.state = state
        self.universe = universe
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        self.sock.bind((bind, port))
        self.sock.settimeout(0.25)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self.packets = 0

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                packet, _ = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = artnet.parse_artdmx(packet)
            if parsed is None:
                continue
            universe, _seq, data = parsed
            if universe != self.universe:
                continue
            self.packets += 1
            self.state.update(data)

    def stop(self) -> None:
        self._stop.set()
        self.sock.close()


def run_output_loop(state: DmxState, sink, rate_hz: float, stop: threading.Event,
                    timeout_s: float = 0.0, idle_bytes: int = 0,
                    break_bits: int = frame.DEFAULT_BREAK_BITS,
                    mab_bits: int = frame.DEFAULT_MAB_BITS) -> int:
    """Émet des trames à cadence fixe jusqu'à ``stop``. Renvoie le nombre de trames.

    ``timeout_s`` > 0 : si aucun paquet Art-Net n'est reçu depuis ce délai
    (après en avoir reçu au moins un), les canaux sont remis à 0 (blackout).
    ``timeout_s`` = 0 : on garde la dernière valeur indéfiniment (défaut, plus
    sûr en spectacle si la tablette se déconnecte un instant).
    """
    period = 1.0 / rate_hz
    next_t = time.monotonic()
    count = 0
    blacked = False
    while not stop.is_set():
        if timeout_s > 0 and state.last_rx and not blacked:
            if time.monotonic() - state.last_rx > timeout_s:
                log.warning("aucun Art-Net depuis %.1f s : blackout", timeout_s)
                state.blackout()
                blacked = True
        if blacked and state.last_rx and time.monotonic() - state.last_rx <= timeout_s:
            blacked = False
        sink.write(frame.build_frame(state.snapshot(), break_bits=break_bits,
                                     mab_bits=mab_bits, idle_bytes=idle_bytes))
        count += 1
        next_t += period
        delay = next_t - time.monotonic()
        if delay > 0:
            stop.wait(delay)
        else:
            next_t = time.monotonic()  # en retard : on ne rattrape pas
    return count


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="spi_dmx", description=__doc__.split("\n")[0])
    p.add_argument("--universe", type=int, default=0, help="univers Art-Net écouté (défaut 0)")
    p.add_argument("--channels", type=int, default=0,
                   help="nombre de canaux émis, 1..512 ; 0 (défaut) = automatique : le nombre de canaux "
                        "du dernier paquet Art-Net reçu (le contrôleur envoie jusqu'au dernier canal utilisé)")
    p.add_argument("--rate", type=float, default=40.0, help="trames/s (défaut 40)")
    p.add_argument("--bind", default="0.0.0.0", help="adresse d'écoute UDP")
    p.add_argument("--port", type=int, default=artnet.ARTNET_PORT, help="port UDP (défaut 6454)")
    p.add_argument("--spi-bus", type=int, default=0)
    p.add_argument("--spi-device", type=int, default=0)
    p.add_argument("--spi-speed", type=int, default=250_000,
                   help="fréquence SPI en Hz (250000 = 4 µs/bit)")
    p.add_argument("--break-bits", type=int, default=frame.DEFAULT_BREAK_BITS)
    p.add_argument("--mab-bits", type=int, default=frame.DEFAULT_MAB_BITS)
    p.add_argument("--idle-bytes", type=int, default=0,
                   help="octets de repos ajoutés après chaque trame")
    p.add_argument("--timeout", type=float, default=0.0,
                   help="blackout si aucun Art-Net depuis N s (0 = garder la dernière valeur)")
    p.add_argument("--dry-run", metavar="FICHIER", default=None,
                   help="n'utilise pas le SPI : écrit les trames dans FICHIER")
    p.add_argument("--no-output", action="store_true", help="ne rien émettre (test réseau)")
    p.add_argument("--test-pattern", action="store_true",
                   help="émet un motif fixe (canaux croissants) sans Art-Net, pour l'analyseur logique")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if not 0 <= args.channels <= frame.MAX_CHANNELS:
        log.error("--channels doit être entre 0 (automatique) et 512")
        return 2
    auto = args.channels == 0
    if auto and args.test_pattern:
        args.channels, auto = 32, False  # le motif de test a besoin d'une taille fixe
    if auto:
        args.channels = 2  # taille initiale, avant le premier paquet (puis suit l'Art-Net reçu)

    state = DmxState(args.channels, auto=auto)
    if args.test_pattern:
        state.update(bytes((i * 8) & 0xFF for i in range(args.channels)))

    if args.no_output:
        sink = NullSink()
    elif args.dry_run:
        sink = FileSink(args.dry_run)
    else:
        try:
            sink = SpiSink(args.spi_bus, args.spi_device, args.spi_speed)
        except Exception as exc:  # spidev absent, SPI désactivé, droits...
            log.error("ouverture SPI impossible : %s (SPI activé ? paquet python3-spidev ?)", exc)
            return 1

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    receiver = None
    if not args.test_pattern:
        try:
            receiver = ArtnetReceiver(state, args.universe, args.bind, args.port)
        except OSError as exc:
            log.error("écoute UDP %s:%d impossible : %s", args.bind, args.port, exc)
            return 1
        receiver.start()
        log.info("écoute Art-Net %s:%d, univers %d", args.bind, receiver.port, args.universe)

    log.info("émission DMX : %s, %.1f trames/s, trame %d µs",
             "canaux automatiques (suivent l'Art-Net reçu)" if auto else f"{args.channels} canaux",
             args.rate, frame.frame_duration_us(args.channels, args.break_bits, args.mab_bits, args.idle_bytes))
    try:
        n = run_output_loop(state, sink, args.rate, stop, args.timeout, args.idle_bytes,
                            args.break_bits, args.mab_bits)
    finally:
        # Fin propre : un dernier blackout évite de laisser des projecteurs allumés
        # sur une valeur figée si le démon est arrêté volontairement.
        state.blackout()
        try:
            sink.write(frame.build_frame(state.snapshot(), break_bits=args.break_bits,
                                         mab_bits=args.mab_bits))
        except Exception:
            pass
        if receiver:
            receiver.stop()
        sink.close()
    log.info("arrêt après %d trames", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
