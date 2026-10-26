# Pédalier : réalisation (boîtier au sol)

Statut : **à construire** ; interrupteurs au pied commandés, le reste à réunir. Rien ici n'a été essayé sur le matériel (à vérifier). Interface avec le contrôleur : [protocole.md](protocole.md). Schéma : [schema.svg](schema.svg) (à ouvrir dans un navigateur).

## Décisions
- **Un bloc posé au sol** : toute l'électronique est dans le boîtier, un seul câble USB vers le Pi.
- Réalisation maison (perçage, soudure) ; 7 interrupteurs au pied à contact fugitif **normalement ouverts** (confirmé par l'utilisateur, 2026-10-26), 7 LED.
- **Carte : LOLIN D32** (ESP32, mini-USB, connecteur de batterie ; l'utilisateur en possède deux, dont une de rechange). Elle a assez de broches pour relier les 14 fils directement : **pas de registre à décalage**. Les registres 74HC595 commandés restent en réserve (voir la variante XIAO plus bas).

## Câblage (LOLIN D32)
Numéros de **GPIO** de l'ESP32 (**à vérifier** sur la sérigraphie de la carte).

| Fonction | GPIO | Branchement |
|---|---|---|
| Pédales 1 à 6 | 13, 14, 16, 17, 18, 19 | interrupteur vers GND (rappel interne activé) |
| Pédale 7 (blackout) | 23 | idem |
| LED 1 à 6 | 21, 22, 25, 26, 27, 32 | résistance 330 Ω puis LED vers GND |
| LED 7 (blackout, rouge) | 33 | idem |

Broches **évitées** : 0, 2, 5, 12, 15 (configuration au démarrage ; le 5 porte la LED de la carte), 34 à 39 (entrées seules, sans rappel interne ; le 35 lit la batterie), 1 et 3 (liaison USB). Si les pédales sont reliées par de longs câbles : 220 Ω en série et 10 nF vers la masse sur chaque entrée.

## Liste de matériel
| Quantité | Pièce | Remarque |
|---|---|---|
| 1 | LOLIN D32 | possédée (2 exemplaires) |
| 7 | interrupteurs au pied, **contact fugitif normalement ouvert** | commandés |
| 7 | LED 3 ou 5 mm (la 7 rouge) | à 3,3 V avec 330 Ω : environ 4 mA chacune |
| 7 | résistances 330 Ω | |
| 1 | boîtier métal | assez solide pour être piétiné ; si besoin, plaque de protection |
| 1 | cordon micro/mini-USB de qualité | vers le Pi ; décharge de traction dans le boîtier |
| — | fil, plaque à pastilles ou barrettes | |

## Étapes
1. **Banc d'essai** : monter la D32 et une LED sur plaque d'essai ; téléverser le firmware ([firmware/pedalboard/](../../firmware/pedalboard/pedalboard.ino)). Le compiler : `arduino-cli compile --fqbn esp32:esp32:d32 firmware/pedalboard` (non essayé ; **à vérifier** : nom de la carte, pilote USB-série sous Windows).
2. **Polarité des interrupteurs** : normalement ouverts, donc `PRESSED_LEVEL = LOW` (valeur par défaut du firmware, rien à changer). Un contrôle au multimètre (ouvert au repos, fermé à l'appui) reste utile avant de souder.
3. **Essai du protocole** depuis un PC, avec un terminal série : `WHO` répond `HELLO 1.0 7` ; un appui donne `BTN 1 1` puis `BTN 1 0` ; `LED 100000 0` allume la LED 1.
4. **Montage final** dans le boîtier : percer, fixer les interrupteurs et les LED (ou boutons lumineux), câbler la carte, la fixer (le connecteur USB doit rester accessible).
5. **Essai avec le contrôleur** sur le Pi : `--pedalboard auto`, étapes de la section 5 bis de [../plan-de-tests.md](../plan-de-tests.md).

## Liaison USB (à vérifier)
La D32 passe par une puce USB-série : sur le Pi, la carte apparaît en `/dev/ttyUSB0` (le contrôleur, avec `--pedalboard auto`, cherche aussi `/dev/ttyUSB*`). Ouvrir le port peut **redémarrer** la carte (lignes DTR/RTS) : le contrôleur retrouve alors la liaison seul, mais à contrôler.

## Variantes
- **XIAO ESP32S3 + 74HC595** (11 broches seulement, LED via registre à décalage, USB natif) : abandonnée pour la D32 ; le schéma et le firmware correspondants sont dans l'historique git (commit `51990a9`).
- Boutons « arcade » lumineux (LED intégrée) : transistor si la LED est prévue pour 5 ou 12 V ; plaque de protection contre les talons.
- Pédales de sustain du commerce sur prises jack : voir [choix-pedales.md](choix-pedales.md).
- Pads MIDI à LED : voir [protocole.md](protocole.md).
