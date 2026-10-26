"""Encodage d'une trame DMX512 en flux binaire pré-calculé pour le bus SPI.

Principe : le SPI0 du Pi est cadencé à 250 kHz, soit 4 µs par bit, ce qui est
exactement la durée d'un bit DMX512 (250 kbit/s). Une trame complète (break,
MAB, start code, canaux) est donc écrite sous forme d'une suite de bits que
l'on envoie telle quelle sur MOSI, d'un seul transfert (DMA côté noyau pour
les transferts longs). Le timing est alors tenu par le matériel, pas par
l'ordonnanceur de Linux.

Structure d'une trame (premier bit émis = bit de poids fort du premier octet) :

    BREAK  : ``break_bits`` bits à 0   (25 bits = 100 µs ; norme : >= 92 µs)
    MAB    : ``mab_bits``  bits à 1    (4 bits  =  16 µs ; norme : >= 12 µs)
    SLOT*N : 0 (start) + 8 bits de données LSB d'abord + 1 1 (stop, x2)
             = 11 bits = 44 µs ; le premier slot est le start code (0x00)
    IDLE   : bits à 1 jusqu'à la fin de l'octet (+ ``idle_bytes`` octets)

Les bits de bourrage finaux sont à 1 : la ligne reste au repos haut (MARK)
entre deux trames, à condition que MOSI conserve son dernier niveau en fin de
transfert (**à vérifier à l'analyseur logique**).
"""

from __future__ import annotations

BIT_US = 4  # durée d'un bit DMX512 en microsecondes
SLOT_BITS = 11  # 1 start + 8 données + 2 stop
MAX_CHANNELS = 512

DEFAULT_BREAK_BITS = 25  # 100 µs
DEFAULT_MAB_BITS = 4  # 16 µs


def _make_slot_table() -> tuple[int, ...]:
    """Table des 256 slots de 11 bits (valeur entière, bit de poids fort = 1er émis)."""
    table = []
    for value in range(256):
        bits = [0]  # bit de start
        bits += [(value >> i) & 1 for i in range(8)]  # LSB d'abord
        bits += [1, 1]  # 2 bits de stop
        word = 0
        for b in bits:
            word = (word << 1) | b
        table.append(word)
    return tuple(table)


_SLOT_TABLE = _make_slot_table()


def build_frame(
    channels: bytes | bytearray | list[int],
    start_code: int = 0x00,
    break_bits: int = DEFAULT_BREAK_BITS,
    mab_bits: int = DEFAULT_MAB_BITS,
    idle_bytes: int = 0,
) -> bytes:
    """Construit le flux binaire SPI d'une trame DMX.

    ``channels`` contient les valeurs des canaux 1..N (N <= 512).
    ``idle_bytes`` ajoute des octets 0xFF après la trame (espacement
    inter-trames supplémentaire).
    """
    data = bytes(channels)
    if len(data) > MAX_CHANNELS:
        raise ValueError(f"trop de canaux : {len(data)} > {MAX_CHANNELS}")
    if not 0 <= start_code <= 255:
        raise ValueError("start_code hors de 0..255")
    if break_bits < 1 or mab_bits < 1:
        raise ValueError("break_bits et mab_bits doivent être >= 1")
    if idle_bytes < 0:
        raise ValueError("idle_bytes < 0")

    # MAB (bits à 1), puis les slots. Le break (bits à 0) correspond aux bits de
    # poids fort nuls : il n'a pas besoin d'être accumulé, seulement compté.
    acc = (1 << mab_bits) - 1
    nbits = mab_bits
    for value in (start_code, *data):
        acc = (acc << SLOT_BITS) | _SLOT_TABLE[value]
        nbits += SLOT_BITS

    total = break_bits + nbits
    pad = (-total) % 8
    if pad:
        acc = (acc << pad) | ((1 << pad) - 1)
        total += pad
    if idle_bytes:
        acc = (acc << (8 * idle_bytes)) | ((1 << (8 * idle_bytes)) - 1)
        total += 8 * idle_bytes
    return acc.to_bytes(total // 8, "big")


def frame_duration_us(n_channels: int, break_bits: int = DEFAULT_BREAK_BITS,
                      mab_bits: int = DEFAULT_MAB_BITS, idle_bytes: int = 0) -> int:
    """Durée approximative d'une trame (octets arrondis compris), en µs."""
    return len(build_frame(bytes(n_channels), break_bits=break_bits,
                           mab_bits=mab_bits, idle_bytes=idle_bytes)) * 8 * BIT_US


class FrameDecodeError(ValueError):
    pass


def decode_frame(stream: bytes) -> dict:
    """Décode un flux produit par :func:`build_frame` (outil de test).

    Renvoie ``{"break_bits", "mab_bits", "start_code", "channels"}``.
    Lève :class:`FrameDecodeError` si le flux n'est pas une trame DMX valide.
    Le décodage s'arrête à la première suite de bits ne formant plus un slot
    valide dans la zone de repos finale (que des 1).
    """
    bits = "".join(f"{byte:08b}" for byte in stream)
    i = 0
    while i < len(bits) and bits[i] == "0":
        i += 1
    break_bits = i
    if break_bits == 0:
        raise FrameDecodeError("pas de break en tête de flux")
    j = i
    while j < len(bits) and bits[j] == "1":
        j += 1
    mab_bits = j - i
    if mab_bits == 0:
        raise FrameDecodeError("pas de MAB après le break")
    # Le dernier '1' de la MAB peut être suivi directement d'un start bit à 0.
    pos = j
    slots = []
    while pos + SLOT_BITS <= len(bits):
        word = bits[pos:pos + SLOT_BITS]
        if word == "1" * SLOT_BITS:
            break  # repos
        if word[0] != "0":
            raise FrameDecodeError(f"start bit manquant à la position {pos}")
        if word[9:] != "11":
            raise FrameDecodeError(f"bits de stop invalides à la position {pos}")
        value = sum(int(word[1 + k]) << k for k in range(8))
        slots.append(value)
        pos += SLOT_BITS
    if not slots:
        raise FrameDecodeError("aucun slot")
    rest = bits[pos:]
    if "0" in rest:
        raise FrameDecodeError("bits à 0 inattendus après le dernier slot")
    return {
        "break_bits": break_bits,
        "mab_bits": mab_bits,
        "start_code": slots[0],
        "channels": bytes(slots[1:]),
    }
