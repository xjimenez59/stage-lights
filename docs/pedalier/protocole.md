# Pédalier : protocole entre le Pi et le pédalier

Statut : côté Pi (`stage_control/pedalboard.py`) écrit et testé avec un faux pédalier ; **firmware non compilé, non essayé** (à vérifier). Ce document décrit seulement l'**interface** entre le contrôleur et le pédalier ; la fabrication du boîtier est dans [realisation.md](realisation.md), le choix des pédales dans [choix-pedales.md](choix-pedales.md).

## Rôle
Sept pédales (6 emplacements configurables + blackout) avec une LED chacune. Le Pi décide de l'action de chaque pédale (réglage « Pédales » de l'interface) et dit au pédalier quelles LED allumer. Le pédalier ne connaît ni les scènes ni les séquences : il envoie des appuis et affiche des LED.

## Liaison
USB, port série (puce USB-série de la LOLIN D32) : sur le Pi, `/dev/ttyUSB0` (ou suivant ; `/dev/ttyACM*` pour une carte à USB natif). Le firmware ouvre l'UART à 115200 bauds, le Pi l'ouvre à la même vitesse (`SerialTransport`). L'utilisateur du service doit être dans le groupe `dialout` (déjà le cas de `pi` ; l'unité systemd l'ajoute aussi).

Texte ASCII, **une ligne par message**, terminée par `\n` (le `\r` est ignoré). Une ligne de plus de 64 octets est abandonnée.

### Pédalier → Pi
| Message | Sens |
|---|---|
| `HELLO <version> <n>` | mise sous tension, et réponse à `WHO` ; `n` = nombre de pédales (7) |
| `BTN <p> <1\|0>` | pédale `p` (1 à 7 ; 7 = blackout) enfoncée (1) ou relâchée (0) |
| `PONG` | réponse à `PING` |

### Pi → pédalier
| Message | Sens |
|---|---|
| `WHO` | début de session : « qui es-tu ? » (réponse `HELLO`, sinon le port est écarté après 3 s) |
| `PING` | toutes les 2 s (réponse `PONG`) |
| `LED <abcdef> <g>` | état des LED : `a` à `f` = emplacements 1 à 6, `g` = blackout ; chacun `0` ou `1`. Exemple : `LED 010010 1` |

Le Pi envoie `LED` à chaque changement d'état et à chaque (re)connexion.

## Règles
- **Appui / relâchement** : tous deux sont envoyés (le relâchement sert au flash). Les répétitions sont ignorées côté Pi.
- **Liaison morte** : le Pi attend une réponse (toute ligne) au moins toutes les 6 s ; sinon il ferme et rouvre le port. Le pédalier, sans nouvelle du Pi pendant 5 s, fait clignoter ses 7 LED.
- **Perte de liaison pendant un appui** : le Pi relâche toutes les pédales enfoncées (un flash ne reste pas bloqué).
- **Démarrage** : une pédale tenue au branchement ne produit pas d'appui ; seul son relâchement est signalé (`BTN <p> 0`), que le Pi ignore.
- **Détection automatique** : avec `--pedalboard auto`, le Pi essaie chaque `/dev/ttyACM*` et `/dev/ttyUSB*` et ne garde que celui qui répond `HELLO` à `WHO`.

## Règles des LED (calculées par le Pi)
| Action de la pédale | LED allumée quand |
|---|---|
| Scène | la scène est active **et aucune séquence ne tourne** |
| Séquence | la séquence est en cours |
| Flash | la pédale est enfoncée |
| Étape suivante / précédente, aucune | jamais |
| Blackout (pédale 7) | le blackout est actif |

## Essais sans matériel
- `tests/test_pedalboard.py` : un faux pédalier TCP joue le protocole (connexion, boutons, LED, perte de liaison, silence, mauvais appareil, lignes invalides).
- `tools/pedalboard_sim.py` : simulateur interactif. Lancer le simulateur, puis `python3 -m stage_control --pedalboard tcp:127.0.0.1:7000` ; taper `4` pour une pédale, `d 4` / `u 4` pour un flash maintenu.

## Variante : pads MIDI à LED
Des **pads** (petits contrôleurs MIDI USB avec LED, de type Launchpad, APC mini, etc.) peuvent jouer le même rôle que le pédalier : l'architecture « entrée → action + retour d'état » s'y prête. Ce qu'il faudrait :
- lire les notes MIDI (un pad = une note ; note on = appui, note off = relâchement) ; sous Linux, les pads « class-compliant » apparaissent comme des fichiers `/dev/snd/midiC*D*` lisibles sans bibliothèque ;
- renvoyer les LED : le message dépend du modèle (souvent une note avec une vélocité qui sert de code couleur) ; certains pads permettraient même d'afficher la **couleur de la scène** sur son pad ;
- un fichier de correspondance note → pédale et état → couleur pour chaque modèle.

Précautions : ce sont des pads à frapper à la main, pas à fouler au pied (à moins d'un modèle conçu pour) ; le protocole des LED doit être vérifié sur le modèle exact. À étudier une fois un modèle choisi ; le firmware maison n'est alors pas nécessaire.
