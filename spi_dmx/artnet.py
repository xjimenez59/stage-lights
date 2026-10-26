"""Analyse et construction minimales de paquets Art-Net (ArtDmx uniquement)."""

from __future__ import annotations

import struct

ARTNET_PORT = 6454
ARTNET_ID = b"Art-Net\x00"
OP_DMX = 0x5000
PROTOCOL_VERSION = 14


def parse_artdmx(packet: bytes):
    """Renvoie ``(universe, sequence, data)`` pour un ArtDmx valide, sinon ``None``.

    ``universe`` est l'adresse 15 bits (Net << 8 | SubUni).
    """
    if len(packet) < 18 or not packet.startswith(ARTNET_ID):
        return None
    (opcode,) = struct.unpack_from("<H", packet, 8)
    if opcode != OP_DMX:
        return None
    (ver,) = struct.unpack_from(">H", packet, 10)
    if ver < PROTOCOL_VERSION:
        return None
    sequence = packet[12]
    sub_uni = packet[14]
    net = packet[15] & 0x7F
    (length,) = struct.unpack_from(">H", packet, 16)
    if length < 1 or length > 512:
        return None
    data = packet[18:18 + length]
    if len(data) != length:
        return None
    return (net << 8) | sub_uni, sequence, bytes(data)


def build_artdmx(universe: int, data: bytes, sequence: int = 0) -> bytes:
    """Construit un paquet ArtDmx (longueur paire imposée par la spec, complétée par 0)."""
    if not 0 <= universe < 0x8000:
        raise ValueError("univers hors de 0..32767")
    data = bytes(data)
    if not 1 <= len(data) <= 512:
        raise ValueError("1 à 512 canaux attendus")
    if len(data) % 2:
        data += b"\x00"
    header = (
        ARTNET_ID
        + struct.pack("<H", OP_DMX)
        + struct.pack(">H", PROTOCOL_VERSION)
        + bytes([sequence & 0xFF, 0, universe & 0xFF, (universe >> 8) & 0x7F])
        + struct.pack(">H", len(data))
    )
    return header + data
