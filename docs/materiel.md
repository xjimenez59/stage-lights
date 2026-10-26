# Matériel : choix, fournisseurs, coûts, alternatives

Seul document du dépôt qui regroupe les recherches de matériel. Les prix sont des **relevés d'octobre 2026, à revérifier** avant achat. Les éléments marqués **(à vérifier)** ne sont pas confirmés. Contraintes : budget global **< 100 €**, pas d'AliExpress, Raspberry Pi 2 B déjà possédés.

## 1. Budget

| Poste | Choix | Prix indicatif |
|---|---|---|
| Routeur / point d'accès | GL.iNet Opal GL-SFT1200 | ~41 € |
| Module RS485 isolé | Waveshare TTL To RS485 (C) | ~15 € |
| Embase XLR 3 broches femelle, câble DMX, boîtier, alimentation 5 V | | quelques euros chacun |
| Pédalier | LOLIN D32 (possédée), 7 interrupteurs au pied (commandés), LED, résistances, boîtier | non relevé |

Routeur + module RS485 : environ 56 €. Commandés ensemble sur Amazon.fr, ils dépassent le seuil de livraison gratuite (45 €, hors Prime, si les deux sont expédiés par Amazon).

## 2. Routeur / point d'accès : GL.iNet Opal (GL-SFT1200)

Relevé à **40,99 €** sur Amazon.fr le 2026-10-23 (4,4/5, environ 8 100 avis ; vérifier que le vendeur est Amazon ou GL.iNet).

- WiFi AC1200 : 300 Mbit/s en 2,4 GHz, 867 Mbit/s en 5 GHz ; 2 antennes externes non démontables.
- 3 ports Ethernet gigabit (1 WAN + 2 LAN), 1 USB 2.0 ; le WAN peut être converti en LAN (voir `network/opal.md`).
- Alimentation USB-C 5 V / 3 A, moins de 6 W ; livré avec un bloc secteur. Double cœur 1 GHz, 128 Mo de RAM.
- Le XR18 n'a pas de serveur DHCP : il faut un vrai routeur.

Points à gérer :
- les antennes ne se déportent pas : **boîtier en plastique**, ou routeur à l'extérieur du boîtier, relié en Ethernet (il n'a besoin que du 5 V) ;
- signal non mesuré : tester sur scène avec une application d'analyse WiFi, aux positions de jeu ;
- délai de démarrage inconnu (le GL-AR750S, plus ancien : environ 160 s rapportés) : **à mesurer**.

Alternatives examinées :

| Modèle | Prix | Pourquoi écarté |
|---|---|---|
| GL.iNet Slate Plus (GL-A1300) | 71,99 € | même 5 GHz, mêmes antennes ; processeur et USB 3.0 inutiles ici |
| GL.iNet Slate AX (GL-AXT1800) | ~121 € | trop cher |
| GL.iNet Beryl AX (GL-MT3000) | ~99-102 € | trop cher |
| GL.iNet Slate (GL-AR750S) | n/d | plus vendu neuf |
| MikroTik hAP ax² | 85-119 € | proche du prix du Slate AX |
| MikroTik hAP ac lite | 42-53 € | 5 GHz sur un seul flux, antennes internes faibles, ports 10/100 |
| MikroTik hAP ax lite | n/d | 2,4 GHz seul d'après un tableau de revendeur |
| GL.iNet Mango (GL-MT300N-V2) | ~25-35 € | 2,4 GHz seul ; à garder en dépannage |

Un **ESP32 comme point d'accès** a été écarté : 2,4 GHz seul, 4 à 15 clients, et le XR18 derrière le Pi serait un point de défaillance unique.

## 3. Module RS485 isolé : Waveshare TTL To RS485 (C)

Convertisseur isolé galvaniquement (module à trous métallisés, à souder) :
- logique TTL 3,3 V ou 5 V ;
- alimentation isolée intégrée (pas de DC-DC supplémentaire) ;
- protection contre les surtensions (TVS), terminaison 120 Ω activable par soudure ;
- broches : VCC, GND, TXD, RXD (côté Pi) ; A+, B−, PE (côté bus) ;
- **pas de broche DE/RE** : sens d'émission automatique (**à confirmer sur la fiche**).

Où l'acheter :
- **Grobotronics** (Grèce, UE) : en stock, expédié sous 24 h ; prix unitaire non vu (7,12 € à partir de 10 pièces) ;
- **RobotShop UK** : environ 6,45 £, hors UE (taxes et douane) ;
- **Amazon.fr** : 14,99 € le 2026-10-23 (12 avis) ; vérifier le vendeur ;
- variante **(B)**, en boîtier pour rail DIN avec bornier à vis : plus simple à câbler, prix non relevé.

À vérifier avant de s'y fier : le **débit maximal** (le DMX est à 250 kbauds) et le comportement du **sens automatique au break** (ligne basse ~100 µs) ; voir `docs/plan-de-tests.md`, section 3.

Modules écartés :
- **Waveshare 2-CH RS485 HAT** (SC16IS752 + SP3485, ~17-20 €) : pont SPI→UART, quartz probablement de 14,7456 MHz (déduction) qui rend 250 kbauds impossibles à 8 % près ; break et MAB resteraient commandés par le logiciel.
- **Waveshare RS485 CAN HAT** (18,72 à 22,99 €) : partie CAN inutile, isolation non confirmée.
- **Hailege / HiLetgo TTL→RS485 à contrôle de flux automatique** (lot de 5 à 8,99 €) : **non isolé**. Utile seulement comme outil d'essai sur table.
- **Module Tindie « isolé à direction automatique »** : stock incertain, vendeur en Chine.
- **ADM2483 seul** (Analog Devices, RS-485 isolé) : plan B de bricolage, en boîtier SOIC-16, avec alimentation isolée 5 V à ajouter.

## 4. Plan B pour le DMX

- **Adaptateur USB-RS485 à FT232**, par exemple Waveshare USB TO RS232/485 (B), ~14 €. Il demande une sortie dédiée dans le contrôleur, ou OLA.
- **Eurolite USB-DMX512 PRO Interface MK2** : ~98 € TTC chez Thomann France, sortie isolée, boîtier métal, XLR 3 broches ; alimenté par l'USB (attention à la limite de courant USB du Pi 2 B, option `max_usb_current`, **à vérifier**).
- **Pico + firmware rp2040-dmxsun** : DMX par PIO (timing matériel), exposé en réseau USB ; aucun matériel prêt à l'emploi, projet peu actif. Écarté.
- Adaptateurs **Open DMX USB** bon marché : scintillements possibles faute de timing matériel. Écartés.

## 5. Alimentation

- Opal : 5 V / 3 A (< 6 W). Pi 2 B : environ 1,1 à 2,3 W d'après les relevés trouvés ; total pire cas environ 3 A. **À mesurer au wattmètre USB.**
- Le bloc fourni avec l'Opal est envisageable pour Opal + Pi ; alternatives : Mean Well RS-25-5 ou RS-35-5. Alimentations séparées recommandées pour l'indépendance du routeur.
- Explorés et non retenus pour l'instant : PoE (séparateurs), batterie.

## 6. Projecteurs : Eurolite LED PARty Spot Silent RGB/WW

4 projecteurs de 17 W, XLR 3 broches (entrée mâle, sortie femelle), modes 4, 6 ou 8 canaux. Mode retenu : 6 canaux. Notice : [Kirstein](https://www.kirstein.de/en/Live-Studio/Light/Headlights/Eurolite-LED-PARty-Spot-Silent-RGB-WW.html), [Thomann](https://www.thomann.de/be/eurolite_led_party_spot_silent_rgb_ww.htm).

## 7. Pédalier

### Carte
**LOLIN D32** (ESP32, micro-USB, connecteur de batterie), possédée en deux exemplaires : assez de GPIO pour 7 pédales et 7 LED en liaison directe. Autres cartes possibles : XIAO ESP32S3 (USB natif, mais seulement 11 broches : il faudrait un registre 74HC595 pour les LED).

### Interrupteurs au pied
Besoin : contact fugitif (momentané), normalement ouvert, deux fils sans tension, robuste, appui franc. Interrupteurs **commandés : normalement ouverts**.

| Famille | Exemples | Atouts | Limites | Prix par pédale |
|---|---|---|---|---|
| Pédale de sustain | Boss FS-5U, Hosa FSC-604, Studiologic PS-100, Korg PS1, Yamaha FC5 | contact fugitif, jack 6,35 mm, conçues pour être piétinées | encombrantes, un jack par pédale | 15 à 40 € |
| Interrupteur de pédale d'effets (stomp) à contact momentané, dans un boîtier métal | commutateur SPST dans un boîtier moulé type Hammond 1590 | un seul boîtier, un seul câble | perçage et soudure | 5 à 10 € + 10 à 30 € le boîtier |
| Gros boutons « arcade » lumineux | boutons de borne d'arcade avec LED | LED intégrée, grande surface | pas conçus pour être piétinés ; LED « 5 V » ou « 12 V » : transistor nécessaire | 3 à 8 € |
| Interrupteur industriel au pied | Herga, Steute | très robuste | lourd, cher | 30 à 100 € |
| Contrôleur MIDI à pied tout fait | Behringer FCB1010, M-Vave Chocolate, Morningstar | prêt à l'emploi | LED non pilotables depuis le Pi, ou hors budget ; M-Vave surtout vendu sur AliExpress | 30 à 300 € |

À contrôler avant de percer : durée de vie annoncée, bruit de l'interrupteur (un clic audible au micro est indésirable), surface d'appui et espacement pour viser sans regarder.

### Liaison avec le Pi (pédalier à plusieurs mètres)

| Option | Distance | Remarque |
|---|---|---|
| USB, câble passif | 5 m au plus | la plus simple |
| USB, rallonge active (répéteur ou extension sur câble réseau) | 10 à 50 m | aucun changement logiciel ; 10 à 30 € **(à vérifier)** |
| RS-485 / RS-422 sur câble blindé, alimentation dans le même câble | dizaines de mètres | un module de plus ; le protocole texte est inchangé ; éviter les prises RJ45 (risque de brancher un switch) |
| WiFi (la D32 en a) | portée de l'Opal | alimentation à part ; à éviter en solution principale |
| MIDI DIN, Ethernet (W5500) | | écartés : protocole à réécrire, ou disproportionné |

**Retenu** : USB avec une prise USB-C sur le boîtier du pédalier et un câble USB-A vers USB-C de quelques mètres (le Pi n'a que des prises USB-A). La prise USB-C du boîtier doit avoir deux résistances de 5,1 kΩ sur CC1 et CC2 (les modules « breakout » en ont). Aucune rallonge « micro-USB mâle vers USB-C femelle à fixer sur panneau » n'a été trouvée dans le commerce ; deux montages : (1) adaptateur micro-USB vers USB-C femelle branché sur la carte, puis [rallonge USB-C à fixer sur panneau](https://www.melopero.com/en/shop/components/Cavi/panel-mount-usb-3-1-type-c-male-90-degree-angle-to-female-extension-cable/) ; (2) module USB-C à fixer sur panneau, relié par 4 fils à un petit câble micro-USB. Pour de plus grandes distances : rallonge active ou RS-485.

## 8. Pistes écartées (architecture)

- Tout fusionner sur une seule carte : moins robuste et plus long à dépanner que des modules du commerce.
- Matériel « pro » (MikroTik + Enttec ODE Mk3 / DMXKing eDMX2) : environ 350-450 €, surdimensionné pour 4 projecteurs.
- Nœud Art-Net générique du commerce : fiabilité et isolation incertaines.
- ESP32 en WiFi pour le DMX : pas assez fiable pour la scène.
- Applications Android d'Art-Net : offre maigre, liée à du matériel propriétaire (myDMX GO d'ADJ, Cuety d'Elation).

## 9. Sources

- Waveshare TTL To RS485 (C) : [fiche](https://www.waveshare.com/product/ttl-to-rs485-c.htm), [Grobotronics](https://grobotronics.com/ttl-to-rs485-galvanic-isolated-lightningproof-and-anti-surge.html?sl=en), [RobotShop UK](https://uk.robotshop.com/products/waveshare-ttl-to-rs485-c-galvanic-isolated-converter-half-duplex-communication-multi-isolation-protection)
- [Waveshare 2-CH RS485 HAT (wiki)](https://www.waveshare.com/wiki/2-CH_RS485_HAT), [ADM2483](https://www.analog.com/en/products/adm2483.html), [quartz du SC16IS750 (SparkFun)](https://sparkfun.com/products/9981), [erreur de débit (NXP)](https://community.nxp.com/thread/452067)
- GL.iNet : [Opal](https://www.gl-inet.com/products/gl-sft1200/), [spécifications](https://docs.gl-inet.com/router/en/3/specification/gl-sft1200/), [Slate Plus](https://www.gl-inet.com/products/gl-a1300/), [Slate AX](https://store-eu.gl-inet.com/fr/products/free-shipping-slate-gl-axt1800-eu-plug), [WAN en LAN](https://docs.gl-inet.com/router/en/4/faq/change_wan_to_lan/)
- MikroTik : [hAP ax²](https://www.mimovrste.com/mrezna-oprema/mikrotik-routerboard-c52ig5haxd2haxdtc-100149630631), [hAP ac lite](https://shop.gigafy.com.au/mikrotik-hap-ac-lite-tc)
- [Eurolite USB-DMX512 PRO MK2 (avis Thomann)](https://www.thomann.fr/eurolite_usb_dmx512_pro_interface_mk2_reviews.htm), [rp2040-dmxsun](https://github.com/OpenLightingProject/rp2040-dmxsun), [Pico-ArtNet-DMX-Node](https://github.com/tmingos/Pico-ArtNet-DMX-Node)
- Pédales : [Boss FS-5U](https://www.woodbrass.com/footswitch-controleurs-boss-fs5u-p14724.html), [Boss FS-6](https://www.woodbrass.com/footswitch-controleurs-boss-fs6-p26327.html), [Hosa FSC-604](https://www.zzounds.com/item--HOSFSC604), [Studiologic PS-100](https://musicredone.com/products/studiologic-ps-100), [interrupteur à ressort à jack (Little Bird)](https://littlebirdelectronics.com.au/collections/game-controllers/products/foot-pedal-switch), [Behringer FCB1010](https://www.fullcompass.com/common/files/40095-FCB1010DataSheet.pdf)
- Panneaux USB : [micro-USB panneau (The Pi Hut)](https://www.thepihut.com/products/panel-mount-extension-usb-cable-micro-b-male-to-micro-b-female), [Parts Express](https://www.parts-express.com/Panel-Mount-Micro-USB-Extension-Cable-Male-to-Female-130-031)
