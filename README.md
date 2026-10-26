# stage-lights : contrôleur d'éclairage de scène

Boîtier de scène pour Raspberry Pi 2 B : contrôleur d'éclairage (scènes avec fondu, séquences, flash, blackout), interface web tactile, sortie DMX512 isolée (RS485) pour 4 projecteurs Eurolite PARty Spot, pédalier USB à LED, et routeur GL.iNet Opal comme point d'accès WiFi.

## Documentation
| Sujet | Document |
|---|---|
| Contexte, décisions, conventions | [CLAUDE.md](CLAUDE.md) |
| Le contrôleur (modèle de données, moteur, interface) | [docs/specification-controleur.md](docs/specification-controleur.md) |
| Sortie DMX (SPI, repli OLA) | [docs/sortie-dmx.md](docs/sortie-dmx.md) |
| Câblage et réseau | [docs/cablage.md](docs/cablage.md), [network/opal.md](network/opal.md) |
| **Pédalier** (sous-projet matériel) | [docs/pedalier/](docs/pedalier/README.md) |
| Choix de matériel, fournisseurs, prix | [docs/materiel.md](docs/materiel.md) |
| Tests sur matériel | [docs/plan-de-tests.md](docs/plan-de-tests.md) |

## État

### Contrôleur et sortie DMX
| Brique | État |
|---|---|
| `spi_dmx` : démon Art-Net → SPI0 → DMX512 | écrit, testé hors matériel |
| `stage_control` : profils, plan de feu, scènes, moteur (fondus, blackout, flash, séquences) | écrit, testé |
| `stage_control` : émetteur Art-Net, persistance JSON, serveur HTTP + SSE | écrit, testé de bout en bout en local |
| Interface web tactile (`stage_control/web/`) | essayée dans Edge (pas sur la tablette) |

### Pédalier
| Brique | État |
|---|---|
| Liaison série côté Pi (`stage_control/pedalboard.py`), protocole, simulateur | écrit, testé avec un faux pédalier |
| Firmware LOLIN D32 (`firmware/pedalboard/`) | écrit, **non compilé ni essayé** |
| Boîtier et câblage | schéma fait, **à construire** |

**Rien n'est validé sur le Pi, sur un analyseur logique ni sur les projecteurs** : voir le plan de tests.

## Démarrage rapide (poste de développement)
Les tests n'utilisent que la bibliothèque standard. Sous Windows, les lancer dans WSL (un test du démon utilise un signal POSIX).

```bash
python3 -m unittest discover -s tests -v

# Contrôleur sans sortie DMX, interface sur http://127.0.0.1:8088
python3 -m stage_control --data ./data --no-output --host 127.0.0.1 --port 8088

# Démon DMX en essai : les trames vont dans un fichier
python3 -m spi_dmx --dry-run /tmp/frames.bin -v &
python3 tools/artnet_send.py --host 127.0.0.1 1=255 2=128 --duration 2
```

Dans VS Code : tâches `Terminal > Run Task` (tests, déploiement).

## Sur le Pi
```bash
./scripts/deploy.sh pi@192.168.8.10      # copie le dépôt dans ~/stage-lights
ssh pi@192.168.8.10 'sudo ~/stage-lights/scripts/install-pi.sh'
```
`install-pi.sh` installe OLA (repli), `python3-spidev`, active SPI et l'UART, copie une seule fois des données d'exemple dans `/var/lib/stage-lights` (4 PARty Spot en 6 canaux, 6 scènes, pédales affectées) et installe les unités systemd `spi-dmx`, `stage-control` et `captive204` (désactivées par défaut : à activer après les tests). L'interface est ensuite sur `http://<ip-du-pi>:8080`.

Les modèles de projecteurs (`profiles/*.json`) se téléchargent, s'importent et se modifient dans l'onglet « Projecteurs » ; un modèle modifié est enregistré dans `/var/lib/stage-lights/profiles/` après un contrôle. Le démon `spi_dmx` émet autant de canaux que le dernier paquet Art-Net reçu (`--channels N` force une valeur fixe).

Essai matériel : `python3 -m spi_dmx --test-pattern --channels 32`, puis analyseur logique sur la broche 19 (MOSI).

## Arborescence
```
stage_control/   contrôleur : profils, scènes, moteur, séquences, sortie Art-Net, pédalier, interface web
spi_dmx/         démon Art-Net → SPI → DMX512
firmware/        firmware du pédalier (Arduino, LOLIN D32)
profiles/        modèles de projecteurs (JSON)
tools/  tests/   outils de test, tests unitaires
config/          OLA, config.txt, cmdline.txt, données d'exemple
scripts/         installation, déploiement, unités systemd
network/         réglages de l'Opal, faux serveur de connectivité
docs/            spécification, sortie DMX, câblage, matériel, tests ; docs/pedalier/ pour le pédalier
```
