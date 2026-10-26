# Spécification : contrôleur d'éclairage (remplace QLC+)

Statut : **spécification validée dans ses grandes lignes** (2026-10-26). Étapes 1 à 3 du plan (§11) écrites et testées hors matériel ; rien n'est validé sur le Pi ni sur les projecteurs.
Les éléments marqués **(à vérifier)** ne sont pas validés sur matériel ou sur la documentation officielle.

## 1. Objectif et décision d'architecture

Remplacer QLC+ par un contrôleur maison, léger, qui est le **seul** producteur de l'univers DMX.
Motifs : le besoin se limite à quelques projecteurs, des scènes avec fondu, une interface tactile avec choix de couleur « au doigt » et un pédalier ; QLC+ n'offre pas de roue de couleur dans sa console virtuelle et sa console ne se construit pas depuis l'interface web.

Ce qu'on abandonne de QLC+ : chasers avancés, matrices RGB, EFX, Show, scripts, plugins d'entrée (MIDI...), bibliothèque de fixtures. Aucun n'est nécessaire pour la première version.

Risque assumé : un logiciel neuf à fiabiliser pour l'usage en concert. Repli : la sortie DMX reste interchangeable (voir §3).

## 2. Périmètre de la première version (v1)

Inclus :
- Plan de feu : 4 PARty Spot (modes 4/6/8 canaux **à vérifier**) et d'autres projecteurs DMX (PAR, etc.) décrits par des profils JSON.
- Scènes mémorisant couleur et niveaux par projecteur, avec fondu.
- Une bibliothèque de scènes (nombre non limité par le pédalier) et de **séquences** (enchaînements de scènes, délai ou action manuelle, §4.6) ; **6 emplacements de pédale** configurables (scène, séquence, étape suivante / précédente, flash), plus un **blackout** figé sur la 7ᵉ pédale.
- Interface web tactile : choix de projecteurs, roue de couleur, palette de pastilles, sliders, enregistrement et rappel de scènes, intensité générale.
- Pédalier maison USB avec une LED par pédale.

Hors v1 (à ne pas empêcher) : règles pilotées par la XR18 (OSC : « qui chante »), projecteurs à mouvement (lyre, pan/tilt et calibration), liaison Bluetooth des pédales (test possible sur les Raspberry Pi 3), import de fichiers `.qxf` de QLC+ (licence et format à vérifier).

## 3. Architecture

```
Navigateur (tablette) ──HTTP/WebSocket──┐
Pédalier USB (série) ───────────────────┼─> stage_control (Python stdlib)
(plus tard) XR18 OSC, BLE ──────────────┘      │ moteur : scènes, fondus, blackout
                                               │ boucle fixe 30 à 44 trames/s
                                               ▼
                                   Art-Net (UDP localhost) ─> spi_dmx ─> SPI0 ─> RS485 ─> XLR
```

- Le contrôleur émet de l'ArtDmx vers `spi_dmx` (déjà présent dans le dépôt), qui maintient la trame DMX côté matériel. Le port 6454 n'est plus partagé avec QLC+, donc le risque de conflit signalé dans CLAUDE.md disparaît.
- Sorties de repli à garder possibles derrière une petite interface « sink » : OLA `uartdmx`, adaptateur USB-RS485 FT232 (voir CLAUDE.md).
- Un seul processus, plusieurs threads (HTTP/WebSocket, série pédalier, boucle d'émission). Stdlib uniquement, comme le reste du dépôt. **Décision : Server-Sent Events** pour les notifications Pi vers tablette (état des scènes, blackout, pédalier), et requêtes HTTP ordinaires pour les commandes (le WebSocket n'est pas dans la stdlib).
- Service systemd, démarrage automatique, état persistant dans un répertoire de données (voir §8).

## 4. Modèle de données

### 4.1 Profil de projecteur (JSON, un fichier par modèle)
- Nom, fabricant, liste de **modes** ; chaque mode donne le nombre de canaux et le **rôle** de chacun :
  `intensity`, `red`, `green`, `blue`, `white` (blanc chaud), `amber`, `uv`, `strobe`, `macro`, `speed`, plus tard `pan`, `tilt`.
- Valeur par défaut des canaux non pilotés (ex. stroboscope = désactivé, programme automatique = aucun).
- Pour les canaux à plage active (stroboscope), `min` et `max` donnent la plage DMX utile (ex. 11 à 255 en 6 canaux).
- Le profil des PARty Spot (modes 4, 6 et 8 canaux, d'après la notice Eurolite) est dans `profiles/eurolite-party-spot-silent-rgbww.json`. Mode retenu : **6 canaux**.

### 4.2 Projecteur du plan de feu
Identifiant, nom affiché, profil, mode, adresse DMX de départ.
Validation : plages d'adresses sans chevauchement, fin ≤ 512.

### 4.3 Scène
Identifiant, nom, temps de fondu (optionnel, sinon valeur par défaut globale), et pour chaque projecteur concerné (une scène peut ne couvrir qu'une partie des projecteurs) :
`couleur RGB`, `blanc` (0 à 100 %), `ambre` (0 à 100 %), `intensité` (0 à 100 %), `stroboscope` (0 = aucun, puis vitesse croissante jusqu'à 100 %).
Les scènes sont **abstraites** (indépendantes des canaux) ; le moteur les traduit selon le profil.
Un projecteur non concerné par une scène reste **tel quel** (la scène se superpose à l'état courant) ; pour le mettre à zéro, on l'inclut dans la scène avec une intensité à 0.

### 4.4 Règles de traduction (couleur vers canaux)
- Un canal absent du profil est **ignoré** (pas de simulation : ni blanc fabriqué avec RGB, ni ambre avec R+G).
- Si le profil a un canal `intensity`, l'intensité du projecteur y est envoyée et les canaux couleur gardent la couleur choisie ; sinon l'intensité multiplie les canaux couleur/blanc/ambre.
- Une option de profil précise cette règle si un modèle se comporte autrement **(à vérifier sur matériel)**.
- L'**intensité générale** multiplie l'intensité de tous les projecteurs, sauf mention contraire d'un profil.

### 4.5 Affectation du pédalier
Tableau de 6 emplacements ; chacun porte une **action** choisie dans l'interface web, mémorisée dans `settings.json`. Une pédale sans action ne fait rien et sa LED reste éteinte. Actions prévues :
- **Scène** `<identifiant>` : rappelle la scène (LED allumée tant qu'elle est la scène active).
- **Séquence** `<identifiant>` : lance la séquence (LED allumée pendant sa lecture). Un nouvel appui sur la pédale d'une séquence en cours l'**arrête** : la dernière scène jouée reste active. Lancer une autre séquence remplace la séquence en cours (circulation couplet / refrain en affectant chaque séquence à une pédale).
- **Étape suivante** et **étape précédente** de la séquence en cours (actions distinctes, affectables à deux pédales). Sans séquence en cours, elles ne font rien.
- **Flash** `<scène>` : la scène est appliquée **tant que le pied reste sur la pédale** ; au relâchement, retour à l'état d'avant (fondu). Une séquence en cours **continue de tourner** derrière le flash (le flash se superpose) ; son état n'est pas modifié.
- **Blackout** : bascule le blackout (LED allumée pendant le blackout).

Actions écartées : « scène suivante / précédente » hors séquence (doublon avec les séquences) et réglage d'intensité générale au pied (l'intensité générale se règle sur l'interface web avant le concert).

Le 7ᵉ bouton du pédalier est **figé en blackout** (pédale de sécurité toujours au même endroit) ; les 6 autres sont configurables.

### 4.6 Séquence
Un enchaînement de scènes s'appelle une **séquence** (chaser ou chenillard dans QLC+, *cue list* sur les consoles lumière ; chaque scène de la liste est une *étape* ou *cue*). Modèle volontairement minimal :
- liste ordonnée d'étapes ; chaque étape : une scène, un temps de fondu, et une **condition de passage** à l'étape suivante, qui est soit un **délai** (secondes) soit une **action manuelle** (pédale « étape suivante ») ;
- réglage par séquence de la **fin** : *s'arrête* sur la dernière scène (défaut) ou *boucle* ;
- pas d'aller-retour, d'aléatoire ni de vitesse variable en v1.
Une séquence est jouée par le même moteur de fondus que les scènes ; sa lecture est un petit automate à états (étape courante, minuteur), testable avec une horloge simulée. Une séquence en cours peut être arrêtée au pied (voir §4.5) ; une étape précédente / suivante manuelle est possible quelle que soit la condition de passage de l'étape (le minuteur repart).

## 5. Moteur de scènes, fondus et blackout

- **État cible** : scène active (1 à 6 ou aucune) et indicateur `blackout` (vrai/faux).
- **Boucle d'émission** à cadence fixe, indépendante des requêtes réseau. À chaque tick, l'état courant est rapproché de l'état cible par interpolation sur les valeurs abstraites (puis traduit en canaux), avec une **courbe en S** (accélération puis décélération douces, de type smoothstep) plutôt qu'une rampe linéaire. Courbe et éventuelle correction de gamma (la luminosité perçue d'une LED n'est pas linéaire) à ajuster à l'œil sur les projecteurs ; l'option « linéaire » reste disponible.
- **Appui pendant un fondu** : nouveau fondu depuis la valeur courante, sans saut.
- **Blackout** : couche par-dessus la scène active, avec son propre temps de fondu. Il ne modifie pas la scène active.
  - 1er appui : fondu vers le noir ; LED blackout allumée, LED de la scène active **restée allumée**.
  - 2e appui : fondu retour vers la scène active.
- **Appui sur une scène pendant le blackout** : la scène devient active (sa LED s'allume, l'ancienne s'éteint), le blackout **reste en place**.
- **Démarrage** : le contrôleur démarre **en blackout**. Le premier appui sur le blackout rétablit la dernière scène active mémorisée, ou la scène 1 à défaut.
- **Temps de fondu** : par scène (réglable), défaut global, et temps propre au blackout.
- **Intensité générale** : réglée sur l'interface web avant le concert, mémorisée.
- Modification à chaud d'une scène active depuis l'interface : appliquée immédiatement, enregistrement explicite pour la mémoriser.

## 6. Interface web (tablette)

Mise en page tactile, grandes cibles, sans aucune ressource externe (le boîtier n'a pas internet). Cinq onglets, le bouton **Blackout** restant visible en permanence :

- **Jeu** (pendant le concert) : les scènes sous forme de cartes cliquables (la scène active est surlignée) ; un mode « Réorganiser » (flèches) règle l'ordre de présentation, enregistré dans l'ordre du fichier des scènes ; les séquences sous forme de cartes (un appui lance ou arrête ; les boutons étape précédente / suivante apparaissent sur la séquence en cours) ; le pédalier simulé (maintenir une case pour un flash, les LED suivent l'état réel).
- **Scènes** (préparation) : la liste des scènes et « + Nouvelle scène » (point de départ : l'éclairage actuel, tout éteint, ou la copie d'une scène). L'éditeur d'une scène donne le nom, le temps de fondu, la sélection des projecteurs avec pour chacun une case **inclus dans la scène** (un projecteur non inclus reste tel quel quand on joue la scène ; régler un projecteur l'inclut automatiquement), la **roue de couleur**, les curseurs **Luminosité du projecteur**, **Couleurs**, **Blanc chaud**, **Ambre**, **Stroboscope** (affichés si le profil a le canal ; couleurs et blanc se règlent séparément) et une palette rapide. L'édition est **en direct** : les changements s'affichent sur scène (bandeau d'avertissement, rappel si le blackout est actif). **Enregistrer** garde la scène ; **Annuler** rétablit l'éclairage d'avant l'édition ; si la scène enregistrée est la scène jouée, elle est rappelée pour montrer son nouvel aspect.
- **Séquences** : éditeur d'étapes (scène, fondu, délai ou passage à la pédale, ordre, boucle).
- **Projecteurs** : plan de feu (liste, ajout, modification, retrait ; adresse libre proposée, chevauchements refusés, rappel « à régler sur le projecteur : mode X, adresse Y », barre d'occupation des 512 canaux) et consultation des modèles (modes, fonction de chaque canal, plages pilotées). Le plan s'applique à chaud ; `spi_dmx` suit le nombre de canaux reçus. Les modèles sont des fichiers JSON (un par modèle) : on peut les **télécharger** (un fichier, ou une archive .zip de tous), les **importer** (fichier .json) ou les **modifier en texte** dans l'interface. Tout modèle est **contrôlé avant intégration** (structure, rôles et valeurs, projecteurs concernés, changements par rapport à la version actuelle, modes utilisés par le plan de feu toujours présents, plan de feu toujours valide) ; l'enregistrement impose un contrôle visible préalable, puis écrit le fichier dans le répertoire de données (avec copie `.bak` de la version précédente). Un modèle modifié remplace celui du dépôt sans le toucher ; le plan de feu s'applique à chaud. Un modèle **personnalisé** peut être supprimé : si le dépôt fournit ce modèle, on revient à la version fournie (après contrôle de sa compatibilité avec le plan de feu), sinon le modèle disparaît à condition qu'aucun projecteur ne l'utilise ; une copie `.bak` du fichier supprimé est conservée. Les modèles fournis ne se suppriment pas. Pas d'éditeur à formulaire en v1. Hors périmètre pour l'instant : mise à jour de la bibliothèque de modèles depuis GitHub.
- **Réglages** : intensité générale, temps de fondu (scènes, blackout, flash), affectation des 6 pédales.
- Une scène à stroboscope, affectée à une pédale « flash », donne un stroboscope tant que la pédale est enfoncée.
- Pas d'authentification en v1 (réseau WiFi fermé, voir risques §9) ; aucune écriture de fichier hors du répertoire de données.

## 7. Pédalier maison (USB)

- Carte : Seeed Studio XIAO ESP32S3 (déjà possédées ; USB natif **et** radio disponible pour un essai BLE ultérieur). Nombre de broches libres suffisant pour 7 boutons + 7 LED **à vérifier**. 7 boutons et 7 LED : emplacements 1 à 6, blackout.
- Liaison **série USB** vers le Pi, protocole texte, une ligne par message, UTF-8, `\n` :
  - pédalier → Pi : `BTN <n> <1|0>` (n = 1 à 7 ; 1 = appui, 0 = relâchement, nécessaire pour le flash ; 7 = blackout) ;
  - Pi → pédalier : `LED <emplacement 0-6> <blackout 0/1>` (emplacement 0 = aucun) à chaque changement d'état, et à la connexion/reconnexion. La LED d'un emplacement « scène » ou « séquence » est allumée tant que cette scène est active / cette séquence en cours ; un emplacement « flash » est allumé pendant l'appui ; « étape suivante / précédente » ne s'allument pas. À préciser : `LED` devra porter un état par emplacement (masque de 6 bits) plutôt qu'un numéro unique ;
  - `HELLO <version>` du pédalier à la connexion ; `PING`/`PONG` pour détecter une liaison morte.
- Règles de LED : une seule LED de scène allumée (scène active) ; LED blackout allumée pendant le blackout ; la LED de la scène active reste allumée pendant le blackout.
- Antirebond côté pédalier ; reconnexion automatique du Pi ; fonctionnement dégradé sans pédalier (interface web seule).
- Le module d'entrées du contrôleur est une interface commune « entrée → action » (rappeler scène N, basculer blackout) partagée par l'interface web et le pédalier, pour permettre d'ajouter plus tard d'autres sources (BLE, MIDI, OSC).

## 8. Persistance et robustesse

- Données en JSON : `fixtures.json` (plan de feu), `profiles/*.json`, `scenes.json`, `settings.json` (intensité générale, fondus, dernière scène active).
- Écriture atomique (fichier temporaire puis renommage) ; copie `.bak` de la version précédente.
- Compatible avec un système de fichiers en lecture seule si les données sont dans une partition ou un répertoire inscriptible séparé **(à vérifier)**.
- Perte d'un client web ou du pédalier : la sortie DMX continue sur l'état courant.
- Arrêt propre : blackout final comme `spi_dmx`.

## 9. Risques et points à vérifier

1. PARty Spot : effet exact des valeurs 1 à 5 du canal 6 (« piloté par la musique », capteur sonore intégré ?), réglage d'usine du menu `Lost` (comportement sans signal DMX ; utiliser `Hold` ou `blac`, pas `FuLL`). Le mode musique n'est pas utilisé pour l'instant.
2. Sortie DMX : tous les points du `docs/plan-de-tests.md` §2 à §4 s'appliquent (SPI, RS485 isolé, projecteurs). Rien n'est validé sur matériel.
3. Cadence de la boucle sur un Pi 2 B avec serveur web et pédalier : mesurer la gigue.
4. Fiabilité en concert d'un logiciel neuf : plan d'endurance (1 h minimum) et test de coupures (débranchement du pédalier, redémarrage de la tablette).
5. Sécurité : interface sans mot de passe sur le WiFi de la scène ; acceptable en réseau fermé, à réévaluer si le réseau est partagé.
6. Rendu des couleurs : sans simulation de blanc/ambre ; le rendu dépend des LED des projecteurs. Courbe de fondu et correction de gamma à ajuster à l'œil.

## 10. Décisions prises et point ouvert

Décisions : QLC+ abandonné (raisons dans `CLAUDE.md`) ; Server-Sent Events pour les notifications vers la tablette ; fondu en courbe en S ; blackout figé sur la 7ᵉ pédale et qui masque aussi le flash ; démarrage en blackout ; un projecteur absent d'une scène reste tel quel ; séquences en v1 (délai ou manuel, boucle ou arrêt) ; pédalier maison sur XIAO ESP32S3 en USB série ; mode 6 canaux pour les PARty Spot ; mode musique des PARty Spot non utilisé.

Point ouvert : format exact du message `LED` (masque de 6 bits + blackout), à fixer avant le firmware.

## 11. Plan de réalisation et avancement

1. ✔ Modèle de données, profils, validation, traduction couleur vers canaux, stroboscope (`stage_control/profile.py`, `plan.py`, `scene.py`, `render.py`).
2. ✔ Moteur de scènes, fondus, blackout, flash, séquences (`engine.py`, `sequence.py`), tests avec horloge simulée.
3. ✔ Émetteur ArtDmx vers `spi_dmx` (`output.py`), test de bout en bout contre le récepteur de `spi_dmx`.
4. ✔ Persistance JSON : écriture atomique, `.bak`, repli sur la copie en cas de fichier corrompu (`store.py`).
5. ✔ Serveur HTTP + SSE (`controller.py`, `server.py`, `__main__.py` ; API décrite en tête de `server.py`). Interface web tactile ✔ (`stage_control/web/`, 4 onglets : Jeu, Couleurs, Séquences, Réglages ; essayée dans Edge, à essayer sur la tablette Android).
6. Module d'entrées et protocole série du pédalier (simulateur logiciel, puis firmware).
7. Tests matériel : suite de `docs/plan-de-tests.md` (à compléter par une section « contrôleur »).
