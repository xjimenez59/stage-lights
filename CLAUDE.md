# CLAUDE.md : contrôleur d'éclairage de scène (Pi 2 B + contrôleur maison + DMX isolé)

Contexte pour l'assistant (extension Claude pour VS Code). Projet en français ; réponds en français.
Étude de conception complète et historique : `docs/etude-conception.md` (version du 2026-10-23, **antérieure** à l'abandon de QLC+).
Spécification du contrôleur maison : `docs/specification-controleur.md` (2026-10-26) ; le code est écrit (`stage_control/`), testé hors matériel seulement.
Les éléments marqués **(à vérifier)** ne sont pas validés sur matériel.

## Besoin
Un boîtier de scène compact : point d'accès WiFi robuste (remplace le WiFi fragile de la Behringer XR18, pilotée par Mixing Station sur tablette Android) + commande DMX de 4 projecteurs Eurolite LED PARty Spot Silent RGB/WW (XLR3, 4/6/8 canaux, 17 W chacun). Un seul univers. Budget < 100 €, pas d'AliExpress, Raspberry Pi 2 B déjà possédés. **Art-Net n'est pas un prérequis** : DMX câblé depuis le Pi (option A).

## Architecture retenue
```
Secteur → alim(s) 5 V
  Routeur GL.iNet Opal GL-SFT1200 (AP 2,4+5 GHz, DHCP) ── Ethernet ──┬─ XR18
                                                                      └─ Raspberry Pi 2 B (contrôleur maison, web)
Pi 2 B ── contrôleur (Art-Net localhost) ── SPI0 MOSI (démon spi_dmx de ce dépôt)  ou  UART (/dev/ttyAMA0 via OLA uartdmx)
       ── Waveshare TTL To RS485 (C) isolé (sens automatique, sans DE/RE) ── XLR3 femelle châssis ── projecteurs
Pi 2 B ── USB série ── pédalier maison (LOLIN D32 : 6 emplacements de scène + blackout, 7 LED)
Tablette Android ── WiFi ── Mixing Station + navigateur (interface du contrôleur : roue de couleur, scènes)
```
Brochage XLR : 1 = GND/blindage, 2 = D− (B), 3 = D+ (A). Sans réponse des projecteurs : inverser 2 et 3.

## Décisions prises depuis l'étude
- **QLC+ abandonné au profit d'un contrôleur maison (2026-10-26).** Raisons : (1) la console virtuelle de QLC+ ne se construit pas depuis son interface web, et fabriquer des `.qxw` à la main demanderait un éditeur dédié ; (2) elle n'offre pas de roue de couleur (seulement sliders par canal, boutons de scène, XY pad non adapté), alors que le choix de couleur « au doigt » par projecteur est voulu pour des utilisateurs non spécialistes ; (3) le besoin est petit (4 PARty Spot + quelques projecteurs DMX, scènes avec fondu, pédalier, plus tard effets pilotés par la XR18 via OSC) et QLC+ ajouterait un second écrivain sur l'univers DMX et un conflit de port Art-Net 6454 ; (4) les fonctions perdues (chasers avancés, matrices RGB, EFX, shows, plugins d'entrée, bibliothèque de fixtures) ne sont pas nécessaires. Coût accepté : logiciel neuf à fiabiliser pour le concert, sortie DMX à valider (comme avant). Sortie de repli conservée : OLA ou FTDI.
- **Pédalier maison USB** (et non Bluetooth/WiFi) : liaison filaire plus simple et plus fiable, retour LED par série ; Pi 2 B sans Bluetooth intégré. Protocole texte, câblage et simulateur : `docs/pedalier/` (protocole, réalisation, schéma ; code Pi : `stage_control/pedalboard.py`, firmware `firmware/pedalboard/`, non essayé sur matériel). Variante envisagée : pads MIDI à LED (à étudier une fois un modèle choisi). Les XIAO ESP32S3 possédées permettront un éventuel essai BLE plus tard. Les Raspberry Pi 3 (BT intégré) ne sont pas la cible : sur Pi 3 l'UART PL011 est pris par le Bluetooth (impact sur la voie OLA `uartdmx`, **à vérifier**).
- **Pas de simulation de blanc/ambre** avec les LED RGB : les sliders « blanc chaud » et « ambre » n'existent que si le profil du projecteur a ce canal.
- **ESP32 comme point d'accès : écarté** (2,4 GHz seul, 4 à 15 clients, XR18 derrière le Pi = point de défaillance unique). Le XR18 reste sur le port LAN de l'Opal.
- **Opal** : 3 ports gigabit (WAN convertible en LAN), USB-C 5 V/3 A (< 6 W). Plan : SSID en 5 GHz pour la tablette, DHCP réservé pour XR18 et Pi.
- **Alimentation** : bloc fourni avec l'Opal envisageable pour l'Opal + Pi (Pi 2 B mesuré ~1,1 à 2,3 W, total pire cas ~3 A, **à mesurer au wattmètre USB**). Alternatives : Mean Well RS-25-5 / RS-35-5. Alimentations séparées recommandées pour l'indépendance du routeur. PoE (séparateurs) et batterie : explorés, **non retenus pour l'instant**.
- **« Pas d'internet » sur le WiFi** : Android/iOS basculent en 4G. Atténuations : XR18 en mode Ethernet, désactiver le basculement automatique, oublier les autres réseaux, et « faux internet » (dnsmasq de l'Opal redirige `connectivitycheck.gstatic.com`, `captive.apple.com`, etc. vers le Pi qui répond HTTP 204 : `network/captive204.py`, **non garanti**).
- **Plan B DMX** : adaptateur USB-RS485 à FT232 (ex. Waveshare USB TO RS232/485 (B), ~14 €). Il se pilotait par le plugin QLC+ « FTDI/Enttec open » ; avec le contrôleur maison, il faudra écrire une sortie dédiée ou passer par OLA.
- Le délai de démarrage de l'Opal est inconnu (AR750S : ~160 s rapportés) : **à mesurer**.
- L'enregistreur multipiste XR18 est un **projet séparé** (`xr18-recorder`), sur un second Pi 2 B.

## Contenu du dépôt
- `spi_dmx/` : démon Python (stdlib uniquement + `spidev` sur le Pi). `frame.py` encode une trame DMX512 en flux de bits pour SPI0 à 250 kHz (4 µs/bit) ; `artnet.py` analyse l'ArtDmx ; `daemon.py` relie les deux.
- `tools/artnet_send.py` : envoi de paquets Art-Net de test.
- `tests/` : `python3 -m unittest discover -s tests` (aucune dépendance).
- `config/` : `ola-uartdmx.conf`, extraits `config.txt` / `cmdline.txt`.
- `scripts/` : `install-pi.sh`, `deploy.sh` (rsync vers le Pi), unités systemd.
- `network/` : réglages de l'Opal, serveur « faux internet ».
- `stage_control/` : contrôleur maison ; `firmware/` : firmware du pédalier ; `profiles/` : modèles de projecteurs.
- `docs/` : spécification, câblage, plan de tests matériel, étude complète ; `docs/pedalier/` : documentation du pédalier, séparée de celle du contrôleur.

## Chaîne logicielle : deux voies pour sortir le DMX (à comparer sur matériel)
1. **OLA `uartdmx`** : contrôleur → OLA → olad → `/dev/ttyAMA0`. Simple mais timing logiciel (break par ioctl) ; scintillement possible sous charge.
2. **Démon `spi_dmx`** : contrôleur → Art-Net (localhost) → `spi_dmx` → SPI0 MOSI (GPIO10, broche 19). Timing tenu par le matériel (DMA). Voie principale ; le conflit de port 6454 avec QLC+ n'existe plus.

## Points non validés (à tester dans l'ordre de `docs/plan-de-tests.md`)
1. Fréquence SPI réelle (horloge cœur à 250 MHz → diviseur 1000 = 250 kHz exact, si `core_freq` est bien fixé ; **à vérifier**) et durée d'un bit mesurée à l'analyseur logique.
2. Niveau de repos de MOSI entre deux transferts (doit rester haut) ; le CS0 est inutilisé.
3. Module RS485 à sens automatique : comportement au break (100 µs bas) et à 250 kbit/s.
4. Cadence et gigue de la boucle du contrôleur sur le Pi 2 B (serveur web + pédalier) ; choix SSE / WebSocket pour l'interface (voir la spécification).
5. Mode 4/6/8 canaux et adressage des PARty Spot (notice Eurolite).
6. Durée de boot de l'Opal ; consommation réelle du Pi.

## Conventions
- Python ≥ 3.9 compatible Pi OS (bookworm : 3.11). Pas de dépendance hors stdlib sauf `spidev` (importé paresseusement).
- Tests sans pytest obligatoire (`unittest`) ; pytest les exécute aussi.
- Ne pas ajouter de dépendances lourdes : le Pi 2 B est un armv7 modeste.
- Messages de log et docs en français.

## Comment m'aider
Aide à : compléter/valider le démon, écrire le contrôleur maison selon `docs/specification-controleur.md` (modèle de données, moteur de fondus, interface web, protocole du pédalier et son firmware), scripts de test d'analyseur logique, durcissement systemd (démarrage rapide, système de fichiers en lecture seule). Ne pas inventer de caractéristiques matérielles : signaler ce qui est à vérifier.
