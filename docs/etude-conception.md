# Projet : boîtier de scène (WiFi + commande lumière DMX)

> **Document historique.** Les passages qui parlent de QLC+ sont **dépassés** : le 2026-10-26, QLC+ a été remplacé par un contrôleur maison (voir `docs/specification-controleur.md` et `CLAUDE.md`). Le matériel, le réseau, l'alimentation et la chaîne DMX décrits ici restent valables.

> Document de contexte du projet. Rédigé le 2026-10-21 à partir d'une discussion de conception, mis à jour le même jour (choix du module RS485, options de timing DMX), puis le 2026-10-23 (choix du routeur / point d'accès).
> Les éléments marqués **(à vérifier)** n'ont pas été confirmés et doivent être testés ou contrôlés avant d'être considérés comme acquis.

## 1. Besoin

- Un **seul boîtier compact** regroupant :
  - un **point d'accès WiFi robuste** (le WiFi intégré de la Behringer XR18 est réputé fragile) ;
  - la **commande de lumières DMX** (une seule sortie, un seul univers).
- La **Behringer XR18** est branchée en **Ethernet** et pilotée depuis une **tablette Android** avec **Mixing Station**.
- La **même tablette** doit aussi piloter les lumières.
- **4 projecteurs** Eurolite LED PARty Spot Silent RGB/WW : entrée DMX en **XLR 3 broches mâle**, sortie (traversante) en **XLR 3 broches femelle** (fiches des revendeurs) ; modes DMX à **4, 6 ou 8 canaux** (choix à faire dans la notice) ; 17 W par projecteur.
- **Budget serré** : viser **moins de 100 €**. Pas d'achat sur AliExpress.
- **Matériel déjà disponible** : plusieurs Raspberry Pi 2 B inutilisés.
- Contexte d'usage : scène, parfois en extérieur ou dans des salles aux installations électriques variables. L'isolation galvanique de la sortie DMX est donc souhaitable.

## 2. Solution retenue (état actuel)

### Architecture

> **Dépassé (QLC+ abandonné le 2026-10-26)** : la partie logicielle (QLC+, console virtuelle, port 9999) est remplacée par le contrôleur maison `stage_control` ; l'architecture à jour est dans `CLAUDE.md`. Le routeur, le RS485 et le DMX restent valables.

```
Secteur → alimentation(s)
   ├─ Routeur/AP WiFi (DHCP) ── Ethernet ──┬─ XR18
   │                                        ├─ Raspberry Pi 2 B (QLC+ + OLA)
   │                                        └─ (prise RJ45 de service, optionnelle)
   └─ (switch gigabit non administrable, seulement si plus de 3 appareils filaires)

Raspberry Pi 2 B ── UART (ou SPI, voir §3) ── Waveshare TTL To RS485 (C) isolé ── XLR 3 broches ── 4 projecteurs
Tablette Android ── WiFi ── Mixing Station (XR18) + navigateur (console virtuelle QLC+)
```

### Composants

| Fonction | Choix | Remarques |
|---|---|---|
| Routeur / AP | **GL.iNet Opal GL-SFT1200** (WiFi AC1200, 2,4 + 5 GHz, ~41 € sur Amazon.fr) | Le XR18 n'a pas de serveur DHCP : il faut un vrai routeur. Voir §2 ter. **Pas encore commandé.** |
| Switch | **Probablement inutile** (~10 € seulement si besoin) | L'Opal a 3 ports gigabit (1 WAN + 2 LAN) et son port WAN peut être converti en LAN (§2 ter) : XR18 + Pi + port de service. Switch seulement pour plus d'appareils filaires. |
| Cerveau lumière | Raspberry Pi 2 B, Raspberry Pi OS Lite **32 bits** | Sans écran, démarrage automatique. |
| Logiciel lumière | ~~**QLC+**~~ (abandonné, remplacé par `stage_control`) avec interface web (`-w`, port 9999 par défaut) | Console virtuelle utilisable depuis le navigateur de la tablette. |
| Pont DMX (première tentative) | **OLA** avec plugin `uartdmx` | QLC+ → plugin OLA → olad → UART. **Plugin OLA dans QLC+ à vérifier sur la version installée.** |
| **Module RS485 isolé** | **Waveshare TTL To RS485 (C)** (14,99 € sur Amazon.fr) | Voir §2 bis. |
| Sortie DMX | Module RS485 → embase **XLR 3 broches femelle** pour châssis | Une sortie DMX source est femelle (comme les interfaces USB-DMX du commerce). Quelques euros. |
| Alimentation | 5 V de qualité, à dimensionner | Opal : USB-C 5 V / 3 A, moins de 6 W (fiche GL.iNet) ; Pi 2 B et switch en plus. Prévoir de la marge (**à calculer**). |

### Budget estimé (Pi déjà possédé)

Routeur Opal ~41 € + module RS485 isolé ~15 € (soit environ 56 €) + XLR / connectique / alim 5 V / boîtier ; un switch (~10 €) seulement si besoin. Objectif : **moins de 100 €**. Ces deux articles commandés ensemble sur Amazon.fr dépassent le seuil de 45 € de livraison gratuite (hors Prime), s'ils sont tous deux expédiés par Amazon.

### Utilisation

> **Dépassé** : ce scénario d'utilisation était celui de QLC+ ; voir `docs/specification-controleur.md`.

1. Préparer le projet QLC+ (projecteurs, scènes, console virtuelle) **sur un PC**, l'enregistrer en `.qxw`, le copier sur le Pi.
2. Sur scène : la tablette se connecte au WiFi du boîtier, Mixing Station pilote la XR18, le navigateur ouvre `http://<ip-du-pi>:9999` pour la console virtuelle QLC+.
3. Attention : l'interface web de QLC+ **ne permet pas d'éditer** la console virtuelle ; elle sert à l'utiliser. Elle reproduit la console du projet chargé (boutons, curseurs, cue lists, pads XY, etc.). Limitation connue : le Grand Master de la console virtuelle n'y est pas géré.

## 2 bis. Module RS485 isolé choisi

**Waveshare TTL To RS485 (C)**, convertisseur isolé galvaniquement (module compact à trous métallisés, à souder) :

- Logique TTL **3,3 V ou 5 V** (compatible avec l'UART et le SPI du Pi).
- **Alimentation isolée intégrée** : pas de convertisseur DC-DC supplémentaire côté bus.
- Protection contre les surtensions (TVS), résistance de terminaison **120 Ω activable par soudure**.
- Broches : VCC, GND, TXD, RXD (côté Pi) ; A+, B-, PE = masse du signal RS485 (côté bus).
- **Pas de broche DE/RE** : le sens d'émission est donc automatique (déduit de la liste des broches, **à confirmer sur la fiche**).

**Où l'acheter** (prix indicatifs, **à revérifier**) :
- **Grobotronics** (Grèce, UE) : en stock, expédié sous 24 h ; tarif dégressif affiché à 7,12 € à partir de 10 pièces (prix unitaire non vu).
- **RobotShop UK** : environ 6,45 £, « à la demande », hors UE (taxes et douane).
- **Amazon.fr** : 14,99 € vu le 2026-10-23 (4,4/5, 12 avis seulement) ; **vérifier le vendeur** (« expédié par Amazon » ou non).
- Variante **(B)**, en boîtier pour rail DIN avec **bornier à vis** et protection contre l'inversion d'alimentation : plus simple à câbler, prix non relevé.

**Deux vérifications avant de s'y fier** :
1. **Débit maximal** : le DMX tourne à 250 kbauds ; la limite du module n'était pas dans les extraits lus (fiche Waveshare à consulter).
2. **Sens automatique et break** : certains circuits à direction automatique réagissent mal au *break* (ligne basse ~100 µs). À tester, idéalement avec un analyseur logique.

**Câblage prévu (à confirmer sur la fiche)** :
- Pi **TXD** (ou MOSI, voir §3) → module **TXD** ; **RXD** non connecté ; GND commun côté Pi ; VCC sur 3,3 V ou 5 V.
- Côté bus : **PE** → broche 1 du XLR (masse) ; **A+** → broche 3 ; **B-** → broche 2. Si les projecteurs ne réagissent pas, **inverser 2 et 3**.
- Terminaison 120 Ω **non activée** au départ (elle se met normalement à la fin de la ligne).

**Modules écartés** :
- **Waveshare 2-CH RS485 HAT** (SC16IS752 + SP3485, ~17-20 €) : pont SPI→UART, isolé (ADuM1412, B0505LS), mais inadapté ici (voir §3).
- **Waveshare RS485 CAN HAT** (versions à 18,72 € et 22,99 € sur Amazon.fr) : pont SPI→UART avec une partie CAN inutile ; les fiches vues ne mentionnent pas d'isolation (la version isolée s'appelle « Isolated RS485 CAN HAT **(B)** »), et les photos ne montrent pas de puces d'isolation (**déduction à vérifier**). Écarté.
- **Hailege / HiLetgo TTL→RS485 à contrôle de flux automatique** (lot de 5 à 8,99 € sur Amazon.fr) : **non isolé** (protections TVS et fusibles, borne « terre », mais masse commune avec le Pi). Pas pour la scène ; utile comme **outil d'essai sur table** : valider la chaîne logicielle (UART + OLA, ou programme SPI) et le comportement d'un module à direction automatique face au débit de 250 kbauds et au break (des fiches de cette famille annoncent 110 à 256 000 bauds, non confirmé pour ce vendeur ; cela ne prouve rien pour le Waveshare (C), dont le circuit est différent).
- **Module Tindie « isolé avec direction automatique »** : stock incertain, vendeur en Chine.
- **ADM2483 seul** (puce Analog Devices, RS-485 isolé, logique 3 V ou 5 V, côté bus en 5 V, 500 kbps) : plan B de bricolage, en boîtier SOIC-16, avec alimentation isolée 5 V à ajouter.

## 2 ter. Routeur / point d'accès choisi

**GL.iNet Opal (GL-SFT1200)**, vu à **40,99 €** sur Amazon.fr le 2026-10-23 (4,4/5, environ 8 100 avis ; livraison gratuite dès 45 € d'achats expédiés par Amazon, ou avec Prime ; **vérifier que le vendeur est Amazon ou GL.iNet / GL Technologies**) :

- WiFi AC1200 : 300 Mbit/s en 2,4 GHz, **867 Mbit/s en 5 GHz**.
- **2 antennes externes non démontables**.
- **3 ports Ethernet gigabit** (1 WAN + 2 LAN, confirmé par la fiche et la photo Amazon), 1 USB 2.0, pas de lecteur microSD. Le port WAN peut être **converti en port LAN** (voir ci-dessous) : 3 ports LAN utilisables, donc pas de switch nécessaire.
- Alimentation **USB-C 5 V / 3 A**, consommation inférieure à 6 W (fiche GL.iNet) ; livré avec un bloc secteur (utile pour les essais sur table).
- Processeur double cœur 1 GHz, 128 Mo de RAM.
- Rôle : routeur avec serveur DHCP et point d'accès, XR18 et Pi branchés sur ses ports LAN.

**Points à gérer** :
- Les antennes ne se déportent pas : **boîtier en plastique**, ou routeur **à l'extérieur du boîtier** relié en Ethernet (il n'a besoin que du 5 V).
- Signal non mesuré : tester sur scène avec une application d'analyse WiFi sur la tablette, aux positions réelles de jeu.
- Réglages WiFi : 5 GHz sur canal fixe (**canaux 36 à 48 pour éviter le DFS, à vérifier**), garder le 2,4 GHz en secours (le 5 GHz est plus sensible à l'absorption par le public).
- Réserver des adresses IP fixes (réservation DHCP) pour la XR18 et le Pi.
- **Convertir le port WAN en LAN** (aide officielle GL.iNet) : laisser le port WAN débranché, se connecter au panneau d'administration web, puis, en firmware 4.7 et plus récent, INTERNET → Ethernet → roue dentée (Port Management) → choisir LAN → Apply ; en firmware 4.6 et antérieur, INTERNET → Ethernet → « Change to LAN ». Se reconnecter ensuite. Retour possible depuis Port Management, ou bouton RESET 4 secondes. La documentation présente surtout cette option pour le mode répéteur ; un utilisateur du forum GL.iNet indique qu'elle fonctionne aussi en mode routeur, **à valider sur l'Opal à la réception**.

**Alternatives examinées** (prix relevés en octobre 2026, à revérifier) :
- **GL.iNet Slate Plus (GL-A1300)** : 71,99 € sur Amazon.fr ; même 5 GHz (867 Mbit/s), mêmes antennes et même alimentation que l'Opal ; apporte un processeur plus puissant (VPN), un USB 3.0 et un 2,4 GHz à 400 Mbit/s, inutiles ici. Écarté.
- **GL.iNet Slate AX (GL-AXT1800)** : environ 121 €, trop cher. **GL.iNet Slate (GL-AR750S)** : plus vendu neuf (Amazon.fr « indisponible »). **Beryl AX (GL-MT3000)** : environ 99-102 €.
- **MikroTik hAP ax²** : 85-119 € selon revendeur ; Wi-Fi 6 en 2×2 sur les deux bandes (antennes internes 4-4,5 dBi), alimentation 12-28 V ou PoE, plus robuste sur le papier mais proche du prix du Slate AX.
- **MikroTik hAP ac lite** : 42-53 € ; 5 GHz sur un seul flux et antennes internes faibles, 5 ports 10/100, alimentation 12-30 V. Écarté. **hAP ax lite** : 2,4 GHz seul d'après un tableau de revendeur, écarté.
- **GL.iNet Mango (GL-MT300N-V2)** : 2,4 GHz seul, option la moins chère (~25-35 €), à garder en dépannage.

## 3. Notes techniques

### Câblage XLR 3 broches (DMX)

- Broche 1 : masse. Broches 2 et 3 : les deux lignes de données. **Si les projecteurs ne réagissent pas, inverser 2 et 3** (la polarité est une source d'erreur fréquente).
- Niveaux logiques du Pi : 3,3 V. Le module retenu accepte 3,3 V à 5 V.
- **Genre du connecteur** : l'embase du boîtier est **femelle** (sortie DMX source) ; l'entrée des projecteurs est **mâle**. Le câble DMX (type câble micro) est donc **mâle d'un côté** (vers le boîtier) et **femelle de l'autre** (vers l'entrée du premier projecteur). Chaque projecteur se chaîne ensuite : sa sortie femelle vers l'entrée mâle du suivant.

### Rappels sur le protocole DMX

- 250 kbauds, 1 bit de start (0), 8 bits de données (poids faible en premier), 2 bits de stop (1) : 11 bits par octet, 4 µs par bit.
- Trame : *break* (au moins 92 µs côté émetteur), *Mark After Break* (au moins 12 µs), start code, puis jusqu'à 512 canaux.
- Le temps de repos entre trames peut aller jusqu'à environ **1 seconde** : une cadence irrégulière est tolérée par la norme ; un break ou un MAB trop courts ne le sont pas.

### Configuration OLA (plugin UART) — première tentative

Fichier `ola-uartdmx.conf` (plugin **désactivé par défaut**) :

```
enabled = true
device = /dev/ttyAMA0        # ou /dev/serial0 selon l'image ; à confirmer sur le Pi 2 B
/dev/ttyAMA0-break = 100     # durée du break en µs (optionnel)
/dev/ttyAMA0-malf = 100      # Mark After Last Frame en µs (optionnel)
```

- Activer l'UART dans la configuration du Pi et **libérer le port du terminal série**.
- Les adaptateurs USB-série ne sont **pas** gérés par ce plugin (le plugin `ftdidmx` existe pour les puces FTDI).
- Sur Pi 2 B (sans Bluetooth), l'UART principal est probablement disponible directement **(à vérifier)**.
- Limite connue : le break, le MAB et l'intervalle entre trames sont générés par un thread logiciel (`UartDmxThread`) ; une issue du dépôt OLA (#1087) montre que la pause entre trames n'était pas mesurée à partir de la fin de la trame, avec une granularité grossière de `tcdrain()`.

### QLC+ en mode sans écran

> **Abandonné** : QLC+ n'est plus utilisé ; section conservée pour l'historique.

- Option `-w` / `--web` pour activer l'interface web ; `-wp <port>` pour changer le port ; `-wa` pour l'authentification.
- Selon la version, il peut être nécessaire d'ajouter `-n` et la variable `QT_QPA_PLATFORM=offscreen` **(à vérifier)**.
- Le plugin OLA de QLC+ est en sortie seule. Vérifier que le paquet installé inclut ce plugin.

### Fiabilité du système

- Système de fichiers en **lecture seule** (Overlay FS dans `raspi-config`) une fois le projet au point, pour résister aux coupures de courant. Carte SD de qualité.
- Délai de démarrage : environ 30 à 45 s avant que l'interface web réponde.
- Alimentation : une alim faible provoque des plantages difficiles à diagnostiquer.
- WiFi : un boîtier métallique atténue fortement le signal. Les antennes de l'Opal ne se déportent pas : boîtier plastique, ou routeur en dehors du boîtier. En 5 GHz : canal fixe, band steering désactivé. Pour la XR18, privilégier le filaire.
- Art-Net n'est pas utilisé sur le WiFi dans la solution actuelle (liaison locale via OLA/UART). Si Art-Net devait l'être plus tard : unicast, jamais en broadcast sur le WiFi.

### Timing DMX : options, de la plus simple à la plus robuste

Le Pi n'est pas temps réel. Les interruptions ne règlent pas le problème : le pilote série du noyau les utilise déjà ; l'incertitude vient du **séquencement** (break, MAB, cadence) géré par un thread utilisateur.

1. **UART + OLA (première tentative)**. Si scintillements, réglages :
   ```ini
   # Override systemd du service olad
   [Service]
   CPUSchedulingPolicy=fifo
   CPUSchedulingPriority=50
   CPUAffinity=3
   ```
   - Ajouter `isolcpus=3` à `cmdline.txt` (dans `/boot/` ou `/boot/firmware/`) pour dédier un cœur à OLA.
   - Gouverneur CPU en `performance`, QLC+ sans écran, pas d'écritures disque.
   - Mesures : `cyclictest` (paquet `rt-tests`) sous charge ; analyseur logique pour observer break / MAB / cadence.
   - Noyau PREEMPT_RT : possible mais jugé disproportionné pour 4 projecteurs.

2. **SPI natif du Pi, trame DMX précodée en bits (idée à évaluer, aucun projet existant trouvé)**.
   - Le programme construit la trame complète en bits à 4 µs par bit : break = 25 bits à 0 (100 µs), MAB = 3 bits à 1 (12 µs), puis 513 octets (start code + 512 canaux) à 11 bits chacun (start 0, 8 bits poids faible en premier, 2 stop à 1), soit environ 5 670 bits, un bloc d'environ **709 octets** et ~22,7 ms. Il l'envoie en **un seul transfert SPI à 250 kHz** ; break, MAB et débit sont alors fixés par le matériel, indépendamment de l'ordonnancement Linux. Seul l'intervalle entre deux trames varie, ce que le DMX tolère.
   - Le **module RS485 reste le même** : seule la broche change (MOSI du SPI0, GPIO10, broche 19, au lieu de TXD).
   - Il faut écrire un petit programme (Python avec `spidev`, ou C) qui reçoit l'Art-Net de QLC+ sur le Pi (UDP 6454), construit le bloc et l'écrit sur `/dev/spidev0.0`.
   - **À vérifier** : (a) horloge SPI exacte à 250 kHz (diviseur de l'horloge noyau ; fixer `core_freq` ; 250 MHz sur Pi 2 B de mémoire) ; (b) taille maximale d'un transfert `spidev` (4096 octets par défaut, suffisant pour ~709) ; (c) **niveau de repos de MOSI entre transferts** (doit rester haut = MARK ; terminer le bloc par des bits à 1) ; (d) comportement du module à direction automatique pendant le break ; (e) QLC+ capable d'envoyer son Art-Net à l'adresse du Pi.

3. **Pico + firmware rp2040-dmxsun** : génération du DMX par PIO (timing matériel), exposé en réseau USB (CDC NCM), à piloter en **Art-Net** (plugin Art-Net de QLC+, pas « DMX USB »). Module RS485 isolé branché sur un GPIO (GPIO 6 à 21 ; le GPIO du port 1 est à confirmer dans `src/localdmx.cpp`).

4. **Adaptateur USB-DMX « Pro » du commerce** (voir §4).

### Pont SPI→UART (SC16IS752) : écarté

Un HAT comme le **Waveshare 2-CH RS485 HAT** (overlay `sc16is752-spi1`, ports `/dev/ttySC0` et `/dev/ttySC1`) n'apporte rien ici :
- **Débit** : Waveshare annonce 300 à 921 600 bauds, ce qui correspond très probablement à un quartz de 14,7456 MHz **(déduction, quartz non confirmé sur ce HAT)**. Avec ce quartz, 250 kbauds exacts sont impossibles (diviseur 3,6864, donc 230 400 bauds, environ 8 % d'écart).
- **Timing** : le break et le MAB restent commandés par le logiciel, avec en plus le bus SPI et le pilote noyau.
- **Compatibilité** du plugin `uartdmx` d'OLA avec ce type de port : incertaine.
- Coût : 17 à 20 €, contre ~7-10 € pour le module TTL → RS485.

## 4. Points ouverts

> Les points qui parlent de QLC+ (3 et 6) sont **sans objet** depuis l'abandon de QLC+ ; la liste à jour est dans `CLAUDE.md` et `docs/plan-de-tests.md`.

1. **Stabilité du timing DMX** sous charge (scintillements). Test de charge repoussé à plus tard. Ordre prévu : UART + OLA d'abord, puis SPI natif si besoin, puis Pico/dmxsun ou adaptateur « Pro ».
2. **Module RS485** : confirmer sur la fiche Waveshare le débit maximal et le sens automatique ; tester le comportement au break.
3. **Plugin OLA dans QLC+** : présent ou non dans le paquet installé ?
4. **Programme SPI** : à écrire et à valider à l'analyseur logique si l'option 2 du §3 est retenue.
5. **Adaptateur USB-DMX « Pro »** (plan B) : par exemple **Eurolite USB-DMX512 PRO Interface MK2** (~98 € TTC chez Thomann France au moment de la recherche, **prix à revérifier**) : sortie isolée, boîtier métal, XLR 3 broches ; sous QLC+, il faut **forcer le protocole « Pro RX/TX »**. Avis partagés avec QLC+. Alimenté par l'USB : attention à la limite d'intensité USB du Pi 2 B (option `max_usb_current`, **à vérifier**).
6. **Ergonomie de l'interface web de QLC+** : si insuffisante, **TouchOSC** (OSC vers QLC+, interface sur mesure ; appli payante, disponibilité Android et prix **à vérifier**).
7. **Routeur** : Opal retenu (§2 ter), à commander ; vérifier le vendeur ; décider boîtier plastique ou routeur à l'extérieur ; mesurer le signal sur place.
8. **Notice des LED PARty Spot** : le XLR 3 broches est confirmé (entrée mâle, sortie femelle). Reste à choisir le mode (4, 6 ou 8 canaux), la fonction de chaque canal et l'adressage DMX de chacun des 4 projecteurs, à relever dans la notice.
9. **Port UART du Pi 2 B** : `/dev/ttyAMA0` ou `/dev/serial0`.
10. **Achat du module** : 1 exemplaire de Waveshare TTL To RS485 (C) (Amazon.fr à 14,99 €, ou Grobotronics), à tester avant d'en commander un second ; éventuellement un lot Hailege à 8,99 € pour les essais sur table.

## 5. Pistes écartées (et pourquoi)

- **Tout fusionner sur une seule carte** : moins robuste et plus long à dépanner que des modules du commerce.
- **Matériel « pro » (MikroTik + Enttec ODE Mk3 / DMXKing eDMX2)** : environ 350-450 €, surdimensionné pour 4 projecteurs.
- **Nœud Art-Net générique du commerce** : fiabilité et isolation incertaines.
- **ESP32 en WiFi pour le DMX** : pas assez fiable pour la scène (en filaire avec W5500, c'est possible mais du bricolage).
- **Applications Android d'Art-Net** : offre maigre et surtout liée à du matériel propriétaire (myDMX GO d'ADJ, Cuety d'Elation). Les applis ouvertes (Photon, Vibrio, StageLight) sont sur iPad.
- **rp2040-dmxsun en projet complet** : aucun matériel prêt à l'emploi (circuits imprimés à commander), cartes isolées non terminées, projet peu actif. Seule la version minimale (Pico nu + module RS485) reste envisageable.
- **Adaptateurs Open DMX USB bon marché** : scintillements possibles faute de timing matériel.
- **Pont SPI→UART (SC16IS752, HAT Waveshare)** : voir §3.
- **Slate AX, Slate Plus, Beryl AX, MikroTik hAP ax² / hAP ac lite / hAP ax lite** : plus chers que nécessaire, ou signal plus faible, ou sans 5 GHz (voir §2 ter).

## 6. Comment m'aider sur ce projet

> **Dépassé** : les consignes actuelles sont dans `CLAUDE.md`.

- Répondre en **français**, de façon concise.
- Pour les éléments marqués « à vérifier », proposer d'abord de vérifier (documentation, test) plutôt que d'affirmer.
- Respecter les contraintes : budget < 100 €, pas d'AliExpress, Pi 2 B, 1 univers DMX, tablette Android, QLC+ en interface web.
- Aides utiles :
  - schéma de câblage Pi → module RS485 → XLR ;
  - scripts d'installation (OLA, QLC+, démarrage automatique, lecture seule) ;
  - exemple de projet QLC+ pour 4 projecteurs ;
  - **programme de sortie DMX par SPI** (réception Art-Net → trame précodée → `/dev/spidev0.0`) ;
  - procédure de test de charge.

## 7. Sources consultées

> Les liens QLC+ ci-dessous ne sont conservés que pour l'historique.

- QLC+, interface web : https://docs.qlcplus.org/v5/advanced/web-interface
- QLC+, matériel compatible : https://mail.qlcplus.org/discover/compatibility
- QLC+, plugin DMX USB : https://github.com/mcallegari/qlcplus-docs/blob/master/pages/09.plugins/02.dmx-usb/default.v4.md
- QLC+, plugin OLA : https://www.mintlify.com/mcallegari/qlcplus/plugins/ola
- OLA, plugin UART DMX : https://docs.openlighting.org/ola/conf/ola-uartdmx.conf.html
- OLA, issue sur le timing du plugin uartdmx : https://github.com/OpenLightingProject/ola/issues/1087
- rp2040-dmxsun : https://github.com/OpenLightingProject/rp2040-dmxsun
- Pico-ArtNet-DMX-Node : https://github.com/tmingos/Pico-ArtNet-DMX-Node
- Forum QLC+, TouchOSC et interface web : https://www.forum.qlcplus.org/viewtopic.php?p=41479
- Eurolite USB-DMX512 PRO MK2 (avis) : https://www.thomann.fr/eurolite_usb_dmx512_pro_interface_mk2_reviews.htm
- Waveshare TTL To RS485 (C) : https://www.waveshare.com/product/ttl-to-rs485-c.htm
- Grobotronics, TTL To RS485 (C) : https://grobotronics.com/ttl-to-rs485-galvanic-isolated-lightningproof-and-anti-surge.html?sl=en
- RobotShop UK, TTL To RS485 (C) : https://uk.robotshop.com/products/waveshare-ttl-to-rs485-c-galvanic-isolated-converter-half-duplex-communication-multi-isolation-protection
- Waveshare 2-CH RS485 HAT (wiki) : https://www.waveshare.com/wiki/2-CH_RS485_HAT
- ADM2483 (Analog Devices) : https://www.analog.com/en/products/adm2483.html
- Quartz et débits du SC16IS750 (SparkFun) : https://sparkfun.com/products/9981
- Erreur de débit et quartz (NXP) : https://community.nxp.com/thread/452067
- Trame DMX (Université d'Aberdeen) : https://erg.abdn.ac.uk/users/Gorry/eg3576/DMX-frame.html
- GL.iNet Opal (GL-SFT1200), page produit : https://www.gl-inet.com/products/gl-sft1200/
- GL.iNet Opal, spécifications : https://docs.gl-inet.com/router/en/3/specification/gl-sft1200/
- GL.iNet Slate Plus (GL-A1300) : https://www.gl-inet.com/products/gl-a1300/
- GL.iNet Slate AX, boutique européenne : https://store-eu.gl-inet.com/fr/products/free-shipping-slate-gl-axt1800-eu-plug
- MikroTik hAP ax² (Mimovrste) : https://www.mimovrste.com/mrezna-oprema/mikrotik-routerboard-c52ig5haxd2haxdtc-100149630631
- MikroTik hAP ac lite (spécifications) : https://shop.gigafy.com.au/mikrotik-hap-ac-lite-tc
- Eurolite LED PARty Spot Silent RGB/WW (connecteurs DMX, modes) : https://www.kirstein.de/en/Live-Studio/Light/Headlights/Eurolite-LED-PARty-Spot-Silent-RGB-WW.html
- Eurolite LED PARty Spot Silent RGB/WW (Thomann) : https://www.thomann.de/be/eurolite_led_party_spot_silent_rgb_ww.htm
- GL.iNet, convertir le port WAN en LAN : https://docs.gl-inet.com/router/en/4/faq/change_wan_to_lan/
