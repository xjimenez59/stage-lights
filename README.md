# stage-lights : contrôleur d'éclairage de scène

Boîtier de scène pour Raspberry Pi 2 B : contrôleur d'éclairage maison (scènes avec fondu, séquences, flash, blackout, pédalier USB à LED), sortie DMX512 isolée (RS485) pour des projecteurs Eurolite PARty Spot, et routeur GL.iNet Opal comme point d'accès WiFi.

- Contexte et décisions : [CLAUDE.md](CLAUDE.md)
- Spécification du contrôleur : [docs/specification-controleur.md](docs/specification-controleur.md)
- Étude matérielle (historique, avant l'abandon de QLC+) : [docs/etude-conception.md](docs/etude-conception.md)
- Câblage : [docs/cablage.md](docs/cablage.md) ; tests sur matériel : [docs/plan-de-tests.md](docs/plan-de-tests.md)

## État

| Brique | État |
|---|---|
| `spi_dmx` : démon Art-Net → SPI0 → DMX512 | écrit, testé hors matériel |
| `stage_control` : profils, plan de feu, scènes, rendu couleur → canaux | écrit, testé |
| `stage_control` : moteur (fondus, blackout, flash, séquences) | écrit, testé avec horloge simulée |
| `stage_control` : émetteur Art-Net vers `spi_dmx` | écrit, testé de bout en bout en local |
| Persistance, serveur web (SSE), interface tactile | à faire |
| Pédalier (firmware XIAO ESP32S3 + module d'entrées) | à faire |

**Rien n'est validé sur le Pi, sur un analyseur logique ni sur les projecteurs** : voir les points à vérifier dans `CLAUDE.md` et le plan de tests.

## Démarrage rapide (poste de développement)

Les tests utilisent la bibliothèque standard seule. Sous Windows, les lancer dans WSL (un test du démon utilise un signal POSIX).

```bash
python3 -m unittest discover -s tests -v

# Essai sans matériel : le démon écrit les trames dans un fichier
python3 -m spi_dmx --dry-run /tmp/frames.bin --channels 32 -v &
python3 tools/artnet_send.py --host 127.0.0.1 1=255 2=128 --duration 2
```

Dans VS Code : ouvrir le dossier, installer les extensions recommandées, tâches `Terminal > Run Task` (tests, déploiement).

## Sur le Pi

```bash
./scripts/deploy.sh pi@192.168.8.10      # copie le dépôt dans ~/stage-lights
ssh pi@192.168.8.10 'sudo ~/stage-lights/scripts/install-pi.sh'
```

`install-pi.sh` installe OLA (voie de repli), `python3-spidev`, active SPI et l'UART, installe les unités systemd (désactivées par défaut : à activer après les tests de `docs/plan-de-tests.md`). L'unité du contrôleur reste à écrire.

Essai matériel : `python3 -m spi_dmx --test-pattern --channels 32` puis analyseur logique sur la broche 19 (MOSI).

## Arborescence

```
CLAUDE.md          contexte pour l'assistant
spi_dmx/           démon Art-Net → SPI → DMX512
stage_control/     contrôleur : profils, scènes, moteur, séquences, sortie Art-Net
profiles/          profils de projecteurs (JSON)
tools/             outils de test
tests/             tests unitaires
config/            OLA, config.txt, cmdline.txt
scripts/           installation, déploiement, unités systemd
network/           routeur, faux internet
docs/              spécification, câblage, tests matériel, étude
```
