# Pédalier : réalisation (boîtier au sol)

Statut : **à construire** ; composants commandés (interrupteurs au pied, registres à décalage), le reste à réunir. Rien ici n'a été essayé sur le matériel (à vérifier). Interface avec le contrôleur : [protocole.md](protocole.md). Schéma : [schema.svg](schema.svg) (à ouvrir dans un navigateur).

## Décisions
- **Un bloc posé au sol** : toute l'électronique est dans le boîtier, un seul câble USB vers le Pi.
- Réalisation maison (perçage, soudure) ; 7 interrupteurs au pied à contact fugitif **normalement ouverts** (confirmé par l'utilisateur, 2026-10-26), 7 LED, 1 XIAO ESP32S3 possédée.
- LED pilotées par un registre à décalage **74HC595** (la carte n'a que 11 broches).

## Câblage (XIAO ESP32S3)
La carte n'a que 11 broches (D0 à D10) : 7 pédales + 7 LED = 14, trop. Les LED passent par le 74HC595 (3 broches). Total : 10 broches.

| Fonction | Broche XIAO | Branchement |
|---|---|---|
| Pédales 1 à 6 | D0 à D5 | interrupteur vers GND (rappel interne activé) |
| Pédale 7 (blackout) | D6 | idem |
| 74HC595 DS (données) | D8 | broche 14 |
| 74HC595 SHCP (horloge) | D9 | broche 11 |
| 74HC595 STCP (verrou) | D10 | broche 12 |
| 74HC595 /OE, /SRCLR, VCC, GND | GND, 3,3 V, 3,3 V, GND | broches 13, 10, 16, 8 |
| LED 1 à 7 | sorties Q0 à Q6 (broches 15, 1 à 6) | résistance 330 Ω puis LED vers GND |

Un condensateur de 100 nF entre VCC et GND, près du 74HC595.

À vérifier :
- D6 est la sortie série de démarrage (GPIO43) : de petits messages y passent au démarrage, sans conséquence avec un simple interrupteur ;
- D2 (GPIO3) est une broche de configuration : pas de rappel externe fort ;
- si les pédales sont reliées par de longs câbles : 220 Ω en série et 10 nF vers la masse sur chaque entrée.

## Liste de matériel
| Quantité | Pièce | Remarque |
|---|---|---|
| 1 | Seeed Studio XIAO ESP32S3 | possédée |
| 1 (+1 de rechange) | 74HC595 (DIP-16) | en boîtier DIP pour la soudure ; alimenté en 3,3 V |
| 7 | interrupteurs au pied, **contact fugitif** | commandés ; vérifier NO/NC (voir [choix-pedales.md](choix-pedales.md)) |
| 7 | LED 3 ou 5 mm (la 7 rouge) | à 3,3 V avec 330 Ω : environ 4 mA chacune |
| 7 | résistances 330 Ω | |
| 1 | condensateur 100 nF | découplage |
| 1 | boîtier métal | assez solide pour être piétiné ; si besoin, plaque de protection |
| 1 | cordon USB de qualité | vers le Pi ; décharge de traction dans le boîtier |
| — | fil, plaque à pastilles ou support DIP | |

## Étapes
1. **Banc d'essai** : monter la XIAO, le 74HC595 et une LED sur plaque d'essai ; téléverser le firmware ([firmware/pedalboard/](../../firmware/pedalboard/pedalboard.ino)). Le compiler : `arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:CDCOnBoot=cdc firmware/pedalboard` (non essayé ; **à vérifier** : `Serial.setTxTimeoutMs`, reset à l'ouverture du port).
2. **Polarité des interrupteurs** : normalement ouverts, donc `PRESSED_LEVEL = LOW` (valeur par défaut du firmware, rien à changer). Un contrôle au multimètre (ouvert au repos, fermé à l'appui) reste utile avant de souder.
3. **Essai du protocole** depuis un PC, avec un terminal série : `WHO` répond `HELLO 1.0 7` ; un appui donne `BTN 1 1` puis `BTN 1 0` ; `LED 100000 0` allume la LED 1.
4. **Montage final** dans le boîtier : percer, fixer les interrupteurs et les LED (ou boutons lumineux), souder sur plaque, fixer la carte.
5. **Essai avec le contrôleur** sur le Pi : `--pedalboard auto`, étapes de la section 5 bis de [../plan-de-tests.md](../plan-de-tests.md).

## Variantes
- Boutons « arcade » lumineux (LED intégrée) : transistor si la LED est prévue pour 5 ou 12 V ; plaque de protection contre les talons.
- Pédales de sustain du commerce sur prises jack : voir [choix-pedales.md](choix-pedales.md).
- Pads MIDI à LED : voir [protocole.md](protocole.md).
