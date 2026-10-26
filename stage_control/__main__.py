"""Point d'entrée : ``python3 -m stage_control --data /var/lib/stage-lights``.

Assemble le moteur, la sortie Art-Net vers ``spi_dmx``, le suivi d'état et le serveur web.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading

from .controller import Controller, EventBus, Ticker
from .output import ArtnetSender, OutputLoop
from .pedalboard import PedalboardLink
from .server import make_server
from .store import Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = logging.getLogger("stage_control")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="stage_control", description=__doc__.split("\n")[0])
    p.add_argument("--data", default=os.path.join(ROOT, "data"),
                   help="répertoire de données (plan, scènes, séquences, réglages)")
    p.add_argument("--profiles", default=os.path.join(ROOT, "profiles"),
                   help="répertoire des profils de projecteurs du dépôt")
    p.add_argument("--static", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"),
                   help="répertoire de l'interface web")
    p.add_argument("--host", default="0.0.0.0", help="adresse d'écoute HTTP")
    p.add_argument("--port", type=int, default=8080, help="port HTTP (défaut 8080)")
    p.add_argument("--dmx-host", default="127.0.0.1", help="hôte du démon spi_dmx (Art-Net)")
    p.add_argument("--dmx-port", type=int, default=6454, help="port Art-Net du démon spi_dmx")
    p.add_argument("--pedalboard", default="", metavar="PORT",
                   help="pédalier USB : « auto » (ports /dev/ttyACM*), un chemin (/dev/ttyACM0) ou tcp:hôte:port "
                        "(simulateur) ; vide = pas de pédalier")
    p.add_argument("--no-output", action="store_true", help="ne rien envoyer en Art-Net (essai de l'interface)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    store = Store(args.data, args.profiles)
    try:
        engine, settings = store.build_engine()
    except (ValueError, KeyError, OSError) as exc:
        log.error("données illisibles dans %s : %s", args.data, exc)
        return 1

    controller = Controller(engine, store, settings, EventBus())
    ticker = Ticker(controller)
    loop = None
    sender = None
    if not args.no_output:
        sender = ArtnetSender(args.dmx_host, args.dmx_port, settings.universe)
        loop = OutputLoop(engine, sender, settings.rate_hz)
    try:
        server = make_server(controller, args.host, args.port, args.static)
    except OSError as exc:
        log.error("écoute HTTP %s:%d impossible : %s", args.host, args.port, exc)
        return 1

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)

    link = None
    if args.pedalboard:
        link = PedalboardLink(controller, args.pedalboard)
        link.start()
        log.info("pédalier : recherche sur %s", args.pedalboard)
    ticker.start()
    if loop:
        loop.start()
        log.info("sortie Art-Net vers %s:%d, %d canaux, %.0f trames/s",
                 args.dmx_host, args.dmx_port, loop.channels, settings.rate_hz)
    log.info("interface sur http://%s:%d (données : %s)", args.host, args.port, args.data)
    try:
        server.serve_forever()
    finally:
        if link:
            link.stop()
            link.join(2)
        if loop:
            loop.stop()
            loop.join(2)
        ticker.stop()
        if sender:
            sender.close()
        server.server_close()
    log.info("arrêt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
