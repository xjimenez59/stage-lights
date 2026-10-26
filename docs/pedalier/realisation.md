# Pédalier : réalisation (boîtier au sol)

Statut : **à construire** ; rien n'a été essayé sur le matériel (à vérifier). Interface avec le contrôleur : [protocole.md](protocole.md). Schéma : [schema.svg](schema.svg). Choix des composants, fournisseurs et prix : [../materiel.md](../materiel.md), section 7.

## Principe
Un bloc posé au sol : toute l'électronique est dans le boîtier, un seul câble USB vers le boîtier du Pi. 7 interrupteurs au pied à contact fugitif **normalement ouverts**, 7 LED, une carte **LOLIN D32** (ESP32) qui a assez de GPIO pour tout câbler directement.

## Câblage
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
| 1 | LOLIN D32 | une seconde en rechange |
| 7 | interrupteurs au pied, contact fugitif normalement ouvert | |
| 7 | LED 3 ou 5 mm (la 7 rouge) | à 3,3 V avec 330 Ω : environ 4 mA chacune |
| 7 | résistances 330 Ω | |
| 1 | boîtier métal | assez solide pour être piétiné ; plaque de protection si besoin |
| 1 | prise USB-C à fixer sur panneau, reliée à la carte | avec 5,1 kΩ sur CC1 et CC2 ; voir [../materiel.md](../materiel.md) |
| 1 | câble USB-A vers USB-C de quelques mètres | vers le Pi |

## Liaison USB (à vérifier)
La D32 passe par une puce USB-série : sur le Pi, la carte apparaît en `/dev/ttyUSB0` (`--pedalboard auto` cherche aussi `/dev/ttyACM*`). Ouvrir le port peut **redémarrer** la carte (lignes DTR/RTS) : le contrôleur retrouve alors la liaison seul, mais à contrôler.

## Étapes
1. **Banc d'essai** : monter la D32 et une LED sur plaque d'essai ; compiler et téléverser le firmware ([firmware/pedalboard/](../../firmware/pedalboard/pedalboard.ino)) : `arduino-cli compile --fqbn esp32:esp32:d32 firmware/pedalboard` (non essayé).
2. **Interrupteurs** : normalement ouverts, donc `PRESSED_LEVEL = LOW` (défaut du firmware). Contrôle au multimètre avant de souder.
3. **Essai du protocole** depuis un PC avec un terminal série : `WHO` répond `HELLO 1.0 7` ; un appui donne `BTN 1 1` puis `BTN 1 0` ; `LED 100000 0` allume la LED 1.
4. **Montage final** : percer, fixer interrupteurs, LED et prise USB-C, câbler, fixer la carte.
5. **Essai avec le contrôleur** sur le Pi : `--pedalboard auto`, section 5 bis de [../plan-de-tests.md](../plan-de-tests.md).
