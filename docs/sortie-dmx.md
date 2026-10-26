# Sortie DMX : protocole, voies logicielles, repli

## Rappels sur le DMX512
- 250 kbauds, 1 bit de start (0), 8 bits de données (poids faible en premier), 2 bits de stop (1) : 11 bits par octet, 4 µs par bit.
- Trame : *break* (au moins 92 µs côté émetteur), *Mark After Break* (au moins 12 µs), start code, puis jusqu'à 512 canaux.
- Le repos entre deux trames peut aller jusqu'à environ 1 seconde : une cadence irrégulière est tolérée ; un break ou un MAB trop courts ne le sont pas.
- Brochage XLR : 1 = masse, 2 = D− (B), 3 = D+ (A). Sans réponse des projecteurs : inverser 2 et 3. Câblage complet : [cablage.md](cablage.md).

## Pourquoi le timing compte
Le Pi n'est pas temps réel : l'incertitude vient du **séquencement** du break, du MAB et de la cadence quand il est fait par un thread utilisateur, pas des interruptions.

## Voie principale : démon `spi_dmx` (SPI0)
Le démon (`spi_dmx/`) construit la trame complète en bits à 4 µs par bit et l'envoie en **un seul transfert SPI à 250 kHz** : break (25 bits à 0), MAB (3 bits à 1), puis 513 octets à 11 bits, soit environ 5 670 bits (un bloc d'environ 709 octets, ~22,7 ms). Break, MAB et débit sont fixés par le matériel ; seul l'intervalle entre trames varie, ce que le DMX tolère. La sortie est la broche MOSI du SPI0 (GPIO10, broche 19), vers le module RS485. Le nombre de canaux émis suit le dernier paquet Art-Net reçu.

À vérifier sur matériel (voir `plan-de-tests.md`, section 2) :
- horloge SPI exacte à 250 kHz (diviseur de l'horloge du cœur ; fixer `core_freq` ; 250 MHz sur Pi 2 B de mémoire) ;
- niveau de repos de MOSI entre transferts (doit rester haut, soit MARK) ;
- taille d'un transfert `spidev` (4096 octets par défaut, suffisant pour ~709) ;
- comportement du module à direction automatique pendant le break.

## Voie de repli : OLA `uartdmx` (UART)
Contrôleur → OLA → olad → `/dev/ttyAMA0`. Plus simple, mais le break, le MAB et l'intervalle sont générés par un thread logiciel (une issue du dépôt OLA, [#1087](https://github.com/OpenLightingProject/ola/issues/1087), en décrit les limites) : scintillement possible sous charge. Fichier `config/ola-uartdmx.conf` (plugin désactivé par défaut) :

```
enabled = true
device = /dev/ttyAMA0        # ou /dev/serial0 selon l'image ; à confirmer sur le Pi 2 B
/dev/ttyAMA0-break = 100     # durée du break en µs (optionnel)
/dev/ttyAMA0-malf = 100      # Mark After Last Frame en µs (optionnel)
```

- Activer l'UART et libérer le port du terminal série ; sur Pi 2 B (sans Bluetooth) l'UART principal est probablement libre **(à vérifier)**.
- Les adaptateurs USB-série ne sont pas gérés par ce plugin (le plugin `ftdidmx` existe pour les puces FTDI).
- En cas de scintillement : override systemd de `olad` (`CPUSchedulingPolicy=fifo`, `CPUSchedulingPriority=50`, `CPUAffinity=3`), `isolcpus=3` dans `cmdline.txt`, gouverneur CPU `performance`, pas d'écritures disque. Mesures : `cyclictest` (paquet `rt-tests`) et analyseur logique. Un noyau PREEMPT_RT est jugé disproportionné.

## Autre repli
Adaptateur USB-RS485 à FT232 ou interface « Pro » : voir [materiel.md](materiel.md). Le contrôleur n'a pas encore de sortie dédiée pour ces adaptateurs.

## Fiabilité du système
- Système de fichiers en **lecture seule** (Overlay FS dans `raspi-config`) une fois le projet au point, pour résister aux coupures de courant ; carte SD de qualité.
- Délai de démarrage du Pi : environ 30 à 45 s avant que l'interface web réponde **(à vérifier)**.
- Une alimentation faible provoque des plantages difficiles à diagnostiquer.
- Un boîtier métallique atténue fortement le WiFi ; XR18 en filaire.
- Art-Net reste sur la boucle locale (127.0.0.1). S'il devait sortir sur le réseau : unicast, jamais en broadcast sur le WiFi.
