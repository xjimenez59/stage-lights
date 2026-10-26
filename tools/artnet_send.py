#!/usr/bin/env python3
"""Envoie des paquets ArtDmx de test (sans QLC+).

Exemples ::

    # canal 1 à 255, canal 2 à 128, vers le Pi
    tools/artnet_send.py --host 192.168.8.10 1=255 2=128

    # chenillard sur 32 canaux pendant 10 s
    tools/artnet_send.py --host 192.168.8.10 --chase --channels 32 --duration 10

Ce script n'utilise que la bibliothèque standard et le module spi_dmx.artnet.
"""

import argparse
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from spi_dmx import artnet  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=artnet.ARTNET_PORT)
    p.add_argument("--universe", type=int, default=0)
    p.add_argument("--channels", type=int, default=32, help="taille du paquet (défaut 32)")
    p.add_argument("--rate", type=float, default=30.0)
    p.add_argument("--duration", type=float, default=2.0, help="secondes (défaut 2)")
    p.add_argument("--chase", action="store_true", help="allume un canal à la fois")
    p.add_argument("values", nargs="*", help="CANAL=VALEUR (canaux numérotés à partir de 1)")
    args = p.parse_args(argv)

    base = bytearray(args.channels)
    for item in args.values:
        ch, _, val = item.partition("=")
        ch, val = int(ch), int(val)
        if not (1 <= ch <= args.channels and 0 <= val <= 255):
            p.error(f"valeur invalide : {item}")
        base[ch - 1] = val

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    t0 = time.monotonic()
    end = t0 + args.duration
    seq = 0
    while time.monotonic() < end:
        data = bytearray(base)
        if args.chase:
            step = int((time.monotonic() - t0) * 4)  # 4 pas par seconde
            data = bytearray(args.channels)
            data[step % args.channels] = 255
        sock.sendto(artnet.build_artdmx(args.universe, bytes(data), seq), (args.host, args.port))
        seq = (seq + 1) % 256
        time.sleep(1.0 / args.rate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
