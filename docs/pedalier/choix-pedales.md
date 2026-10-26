# Pédales et interrupteurs au pied : pistes

Statut : **exploration**, rien n'est acheté ni essayé. Les prix sont des ordres de grandeur tirés de pages de revendeurs consultées le 2026-10-26 ou de ma connaissance générale (marqués **(à vérifier)**) : ils varient et ne sont pas ceux d'un devis. Rappel du cahier des charges du projet : budget global serré, pas d'AliExpress.

## Ce dont le pédalier a besoin
- Un **contact fugitif** (« momentané », à rappel par ressort) : il se ferme tant qu'on appuie et s'ouvre au relâchement. C'est indispensable au **flash** (actif tant que le pied reste dessus). Un interrupteur à verrouillage (« latch », comme dans une pédale d'effet qui s'enclenche) ne convient pas.
- **Normalement ouvert** (NO) de préférence : le contact relie l'entrée à la masse quand on appuie. Certaines pédales de sustain sont « normalement fermées » ; le firmware gère les deux (constante `PRESSED_LEVEL` dans `firmware/pedalboard/pedalboard.ino`), à condition de toutes les prendre de même polarité.
- Un seul **contact sec** (deux fils, pas de tension). Rien d'électronique dans la pédale.
- De la robustesse : appui au pied, parfois avec une semelle dure, au sol, sur une scène (poussière, boissons).
- Un appui franc sans ambiguïté (retour tactile ou sonore), pour jouer sans regarder.

## Les familles de composants

| Famille | Exemples | Atouts | Limites | Prix par pédale **(à vérifier)** |
|---|---|---|---|---|
| **Pédale de sustain** (clavier, piano numérique) | Boss FS-5U (non verrouillante, sélecteur de polarité), Hosa FSC-604 (boîtier tout métal, NO/NC), Studiologic PS-100, Korg PS1, Yamaha FC5 | Contact fugitif, jack 6,35 mm standard, conçues pour être piétinées, câble fourni ou jack débrochable, on les remplace en 10 s sur scène | Plus encombrantes, certaines en plastique, un jack par pédale à câbler | 15 à 40 € (Hosa env. 35 $, PS-100 env. 23 CAD, FS-5U neuve entre 39 et 62 £ selon le revendeur) |
| **Interrupteur de pédale d'effets** (stomp) à contact momentané, monté dans un boîtier métal | commutateur « momentary SPST » de bricolage dans un boîtier moulé type Hammond 1590 ; pédales boutique (ex. Saturnworks, métal moulé + jack Neutrik) | Un seul boîtier robuste avec toute l'électronique à l'intérieur, un seul câble USB, très compact | À monter soi-même (perçage, soudure) ; la tenue du commutateur au piétinement répété est à contrôler | 5 à 10 € le commutateur + 10 à 30 € le boîtier |
| **Gros boutons « arcade » lumineux** (60 mm ou plus) | boutons poussoirs de borne d'arcade, avec LED intégrée | La **LED est dans le bouton** : plus de LED à part, grande surface d'appui, très peu cher | Pas conçus pour un piétinement : prévoir une plaque de protection ou un capot, tenue à vérifier | 3 à 8 € |
| **Interrupteur industriel au pied** (type machine-outil, avec carter) | commutateurs à pédale à carter métal (Herga, Steute, etc.) | Très robustes, carter anti-appui accidentel | Lourds, chers, trop massifs pour une scène | 30 à 100 € |
| **Contrôleurs MIDI à pied tout faits** | Behringer FCB1010 (10 pédales, MIDI DIN seulement), M-Vave Chocolate (4 pédales, Bluetooth), Morningstar | Pratiques, déjà au sol | **Les LED ne se pilotent pas depuis le Pi** pour la plupart (la FCB1010 allume ses LED toute seule), ou sont hors budget ; certains modèles sont vendus surtout sur AliExpress | 30 à 300 € |

## Ce que je recommande d'étudier en premier
1. **Un boîtier unique, au sol, avec l'électronique dedans** (XIAO + 74HC595) et des commutateurs montés sur le dessus. C'est la solution la plus fiable en scène (une seule liaison USB, rien à rebrancher) et la moins chère. Deux sous-variantes :
   - **Commutateurs de pédale d'effets** (momentanés) + 7 LED de panneau : le moins cher (environ 60 à 90 € de pièces et de boîtier **(à vérifier)**), le plus à bricoler ;
   - **Gros boutons arcade lumineux** : le plus simple à câbler (LED dans le bouton), à protéger contre les coups de talon.
2. **Un boîtier à 7 prises jack 6,35 mm** (entrées) + 7 LED sur le dessus, où l'on branche des **pédales de sustain** du commerce : on choisit ses pédales (et on les remplace sur scène), mais c'est la solution la plus chère (7 pédales à 15–40 €) et elle fait un faisceau de câbles. À réserver si l'on veut poser les pédales ailleurs qu'au même endroit.

Dans les deux cas, le schéma de [schema.svg](schema.svg) reste valable : un contact entre l'entrée et la masse par pédale. Pour les arcade avec LED intégrée, les 7 LED du schéma se placent dans les boutons (en vérifiant leur tension : une LED de bouton « 5 V » ou « 12 V » contient sa résistance et ne se pilote pas directement par le 74HC595 ; on y mettrait un transistor, ou on choisirait des boutons à LED simple, avec résistance extérieure).

## Choses à vérifier avant d'acheter
- Le contact est-il bien **fugitif** et **normalement ouvert** (ou de polarité connue) ?
- Durée de vie annoncée (en millions de manœuvres) et tenue à l'appui de la **semelle**.
- Bruit de l'interrupteur (un « clic » audible au micro n'est pas souhaitable sur scène).
- Distance au boîtier : longs câbles blindés + 220 Ω et 10 nF sur chaque entrée (voir les notes du schéma).
- Surface d'appui et espacement : on doit viser **sans regarder**, à l'aveugle, avec 7 pédales.

## Décisions (2026-10-26)
- **Un bloc posé au sol**, réalisé par l'utilisateur (perçage, soudure) ; interrupteurs au pied et registres à décalage commandés. Suite : [realisation.md](realisation.md).
- Budget et nombre de pédales : 7 (6 emplacements + blackout), pas de budget séparé précisé.

## Sources consultées
- [Boss FS-5U (Woodbrass)](https://www.woodbrass.com/footswitch-controleurs-boss-fs5u-p14724.html) et [Boss FS-6 (Woodbrass)](https://www.woodbrass.com/footswitch-controleurs-boss-fs6-p26327.html)
- [Hosa FSC-604 (zZounds)](https://www.zzounds.com/item--HOSFSC604)
- [Studiologic PS-100 (Music Redone)](https://musicredone.com/products/studiologic-ps-100)
- [Pédale d'interrupteur à ressort, jack mono (Little Bird Electronics)](https://littlebirdelectronics.com.au/collections/game-controllers/products/foot-pedal-switch)
- [Behringer FCB1010, fiche technique (Full Compass)](https://www.fullcompass.com/common/files/40095-FCB1010DataSheet.pdf)
