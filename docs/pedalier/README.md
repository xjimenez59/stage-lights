# Pédalier de scène

Sous-projet **matériel** : un boîtier posé au sol avec 7 interrupteurs au pied et 7 LED, relié en USB au Raspberry Pi. Il ne connaît ni les scènes ni les séquences : il envoie des appuis et affiche les LED que le contrôleur lui indique. La logique (actions des pédales, règles des LED) est dans le **contrôleur** ([../specification-controleur.md](../specification-controleur.md), §4.5 et §7).

| Document | Contenu |
|---|---|
| [protocole.md](protocole.md) | interface avec le contrôleur : messages série, règles, essais sans matériel |
| [realisation.md](realisation.md) | câblage, matériel, étapes de construction |
| [schema.svg](schema.svg) | schéma de câblage |
| [../materiel.md](../materiel.md) | choix des composants, fournisseurs, prix |

Code : firmware [../../firmware/pedalboard/](../../firmware/pedalboard/pedalboard.ino) ; côté Pi [../../stage_control/pedalboard.py](../../stage_control/pedalboard.py) ; simulateur [../../tools/pedalboard_sim.py](../../tools/pedalboard_sim.py) ; tests [../../tests/test_pedalboard.py](../../tests/test_pedalboard.py).
