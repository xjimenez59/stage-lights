# Plan de tests matériel (dans l'ordre)

Cocher au fur et à mesure et noter les mesures dans ce fichier.

## 0. Préparation
- [ ] Pi OS Lite 32 bits (bookworm) flashé, SSH activé, IP réservée (192.168.8.10 sur l'Opal).
- [ ] `sudo ./scripts/install-pi.sh` exécuté ; redémarrage.

## 1. Alimentation et réseau (Opal)
- [ ] Consommation Opal seul, Opal + Pi, Opal + Pi + XR18 (wattmètre USB). Résultat : ____ W / ____ A
- [ ] Durée de démarrage de l'Opal (de la mise sous tension à la connexion de la tablette) : ____ s
- [ ] XR18 en mode Ethernet, visible dans Mixing Station via l'Opal.
- [ ] SSID 5 GHz seul pour la tablette ; test à distance et avec obstacles.
- [ ] « Faux internet » (`network/`) : la tablette reste-t-elle connectée sans basculer en 4G ?

## 2. Sortie SPI (sans projecteur)
- [ ] `python3 -m spi_dmx --test-pattern --channels 32` ; analyseur logique sur GPIO10 (broche 19).
- [ ] Durée d'un bit = 4 µs (± 1 %) ? Mesure : ____ µs. Sinon, régler `core_freq` / `--spi-speed`.
- [ ] Break ≥ 92 µs (attendu 100 µs), MAB ≥ 12 µs (attendu 16 µs).
- [ ] MOSI reste haut entre deux trames ? (sinon ajouter un pull-up 10 kΩ sur l'entrée du module ou passer en polarité inversée)
- [ ] Périodicité de la trame stable (gigue) pendant une compilation lourde (`stress` ou `make -j4`) ?

## 3. Module RS485 isolé
- [ ] Alimentation 3,3 V ou 5 V du module (selon fiche) ; TX du module sur MOSI.
- [ ] Signaux A/B différentiels propres à l'oscilloscope/analyseur : break complet transmis (sens automatique) ?
- [ ] Tester avec le module seul puis avec les 4 projecteurs chaînés (ajouter une résistance de terminaison 120 Ω au bout de la chaîne si nécessaire).

## 4. Projecteurs
- [ ] Mode DMX **6 canaux** (menu `Addr`, puis `6CH`) sur chaque PARty Spot, adresses de départ 1, 7, 13, 19 (notice : `d001` à `d507` en 6CH). Profil : `profiles/eurolite-party-spot-silent-rgbww.json`.
- [ ] Menu `Lost` (comportement sans signal DMX) : choisir `Hold` (dernière valeur) ou `blac` (éteint) ; **éviter `FuLL`** (tout à 100 %). Relever le réglage d'usine.
- [ ] Menu `Slav` : le laisser désactivé (pas de mode esclave). Désactiver la télécommande IR (`InFr` = `oFF`) si des télécommandes parasites sont possibles.
- [ ] Canal 6 (stroboscope) : 0 = rien, 11 à 255 = stroboscope ; noter l'effet exact des valeurs 1 à 5 (« piloté par la musique ») **(à vérifier)**.
- [ ] `python3 tools/artnet_send.py --host 127.0.0.1 1=255 2=255 --duration 5` : réponse ?
- [ ] Sans réponse : inverser les fils 2 et 3 du XLR.

## 5. QLC+
- [ ] Version installée et options en ligne de commande : `qlcplus --help`.
- [ ] Plugin OLA présent ? sinon utiliser la voie Art-Net → `spi_dmx`.
- [ ] Interface web joignable depuis la tablette : `http://192.168.8.10:9999`.
- [ ] Projet `.qxw` : 4 fixtures + console virtuelle ; démarrage automatique.

## 6. Endurance
- [ ] 1 h de fonctionnement continu sans scintillement ni plantage ; relevés de température du Pi.
- [ ] Coupure/reprise du secteur : tout redémarre seul ; durée de remise en service totale : ____ s.
