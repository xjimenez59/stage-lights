# Câblage

## Pi 2 B → module Waveshare TTL To RS485 (C)

| Pi 2 B (connecteur 40 broches) | Module | Remarque |
|---|---|---|
| 5 V (broche 2/4) ou 3,3 V (broche 1) | VCC | Plage 3,3 à 5 V selon fiche **(à vérifier)** |
| GND (broche 6) | GND | |
| **Option SPI** : MOSI GPIO10 (broche 19) | RXD / entrée TTL du module | Voir convention des noms sur la sérigraphie |
| **Option UART** : TXD GPIO14 (broche 8) | RXD du module | `/dev/ttyAMA0` |

Le module est isolé galvaniquement : côté RS485, alimentation et masse sont séparées de celles du Pi. La borne PE se raccorde au blindage si le montage le justifie.

## Module → XLR 3 broches femelle (châssis)

| Module | XLR | Rôle |
|---|---|---|
| A+ | broche 3 | D+ |
| B− | broche 2 | D− |
| PE / blindage | broche 1 | GND |

Si les projecteurs ne réagissent pas : inverser les broches 2 et 3.

Chaîne : sortie XLR femelle du boîtier → câble DMX (110 Ω) → entrée XLR mâle du 1er projecteur → sortie femelle → entrée du suivant… Terminaison de 120 Ω entre D+ et D− à la sortie du dernier projecteur si nécessaire.

## Réseau

Opal : WAN converti en LAN (voir `network/opal.md`), ports LAN : XR18 et Pi.

## Alimentation

Voir `CLAUDE.md` (décisions) : mesurer avant de choisir entre le bloc de l'Opal, un 5 V commun ou deux blocs séparés.
