# CLAUDE.md : contrôleur d'éclairage de scène (Pi 2 B + DMX isolé + pédalier)

Contexte pour l'assistant (extension Claude pour VS Code). Projet en français ; réponds en français.
Les éléments marqués **(à vérifier)** ne sont pas validés sur matériel. Ne pas inventer de caractéristiques matérielles : signaler ce qui est à vérifier.

## Besoin
Un boîtier de scène compact : point d'accès WiFi robuste (remplace le WiFi fragile de la Behringer XR18, pilotée par Mixing Station sur tablette Android) et commande DMX de 4 projecteurs Eurolite LED PARty Spot Silent RGB/WW (XLR3, mode 6 canaux retenu). Un seul univers. Budget < 100 €, pas d'AliExpress, Raspberry Pi 2 B déjà possédés. Interface tactile (couleur « au doigt », scènes avec fondu, séquences) et pédalier au pied avec LED.

## Architecture
```
Secteur → alim(s) 5 V
  Routeur GL.iNet Opal (AP 2,4+5 GHz, DHCP) ── Ethernet ──┬─ XR18
                                                          └─ Raspberry Pi 2 B (contrôleur stage_control, web :8080)
Pi 2 B ── Art-Net (localhost) ── spi_dmx ── SPI0 MOSI ── module RS485 isolé ── XLR3 ── projecteurs
Pi 2 B ── USB série ── pédalier (LOLIN D32 : 6 emplacements + blackout, 7 LED)
Tablette Android ── WiFi ── Mixing Station + navigateur (interface du contrôleur)
```

## Documentation (où trouver quoi)
- `docs/specification-controleur.md` : le contrôleur (modèle de données, moteur, interface web, état d'avancement).
- `docs/sortie-dmx.md` : sortie DMX (voie SPI, repli OLA, fiabilité). `docs/cablage.md` : câblage. `network/opal.md` : réseau.
- `docs/pedalier/` : le pédalier (protocole, réalisation, schéma), distinct du contrôleur.
- `docs/materiel.md` : **tous** les choix de matériel, fournisseurs, prix, alternatives écartées, sources.
- `docs/plan-de-tests.md` : tests sur matériel, dans l'ordre.

## Décisions
- **Contrôleur maison** en Python (stdlib seule) : seul producteur de l'univers DMX. Scènes abstraites traduites selon des profils JSON de projecteurs (`profiles/`).
- **DMX** : voie principale `spi_dmx` (timing tenu par le matériel). Repli : OLA `uartdmx` ou adaptateur USB-RS485 FT232.
- **Pédalier USB filaire** (pas de Bluetooth/WiFi) : retour LED par série, protocole texte ; carte LOLIN D32, LED câblées directement. Liaison vers le boîtier du Pi par un câble USB-C (prise sur panneau) de quelques mètres.
- **Pas de simulation de blanc/ambre** avec les LED RGB : les curseurs « blanc chaud » et « ambre » n'existent que si le profil a ce canal.
- **Réseau** : l'Opal est le routeur et le point d'accès ; le XR18 reste sur un port LAN (pas d'ESP32 comme point d'accès). SSID 5 GHz pour la tablette, DHCP réservé pour XR18 et Pi. « Pas d'internet » : les téléphones basculent en 4G, atténué par un faux serveur de connectivité (`network/captive204.py`, **non garanti**).
- **Alimentation** : bloc de l'Opal envisageable pour Opal + Pi, **à mesurer au wattmètre USB** ; alimentations séparées recommandées. PoE et batterie : non retenus.
- L'enregistreur multipiste XR18 est un **projet séparé** (`xr18-recorder`), sur un second Pi 2 B.

## Contenu du dépôt
- `stage_control/` : contrôleur (profils, plan de feu, scènes, moteur de fondus, séquences, sortie Art-Net, serveur HTTP + SSE, liaison pédalier, `web/` = interface).
- `spi_dmx/` : démon Art-Net → SPI0 → DMX512 (stdlib + `spidev` importé paresseusement).
- `firmware/pedalboard/` : firmware du pédalier (Arduino, non compilé). `profiles/` : modèles de projecteurs. `config/` : OLA, `config.txt`, `cmdline.txt`, données d'exemple.
- `tools/` : envoi Art-Net de test, simulateur de pédalier. `scripts/` : installation, déploiement, unités systemd. `network/` : Opal, faux internet.
- `tests/` : `python3 -m unittest discover -s tests` (sous Windows, dans WSL).

## Points non validés (dans l'ordre de `docs/plan-de-tests.md`)
1. Fréquence SPI réelle (250 kHz exacts si `core_freq` est fixé) et durée d'un bit à l'analyseur logique.
2. Niveau de repos de MOSI entre deux transferts (doit rester haut).
3. Module RS485 à sens automatique : comportement au break (100 µs bas) et à 250 kbit/s.
4. Cadence et gigue de la boucle du contrôleur sur le Pi 2 B.
5. Mode 6 canaux et adressage des PARty Spot ; réglage `Lost` du projecteur.
6. Durée de boot de l'Opal ; consommation réelle du Pi.
7. Pédalier : firmware non compilé ; GPIO de la D32 ; redémarrage de la carte à l'ouverture du port série.

## Conventions
- Python ≥ 3.9 compatible Pi OS (bookworm : 3.11). Pas de dépendance hors stdlib sauf `spidev`.
- Tests en `unittest` (pytest les exécute aussi). Ne pas ajouter de dépendances lourdes : le Pi 2 B est un armv7 modeste.
- Messages de log et documentation en français. Un fait de matériel non vérifié est marqué **(à vérifier)**.
- Documentation : décrire l'état actuel du projet, sans mentions d'options abandonnées ; la recherche de matériel (fournisseurs, prix, alternatives) va dans `docs/materiel.md` seulement.
- Ne commiter ni pousser que sur demande.
