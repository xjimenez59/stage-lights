# Réglages du GL.iNet Opal (GL-SFT1200)

Valeurs par défaut courantes : IP 192.168.8.1, interface `http://192.168.8.1` (à vérifier sur le modèle livré).

## À faire
1. Définir le mot de passe administrateur ; mettre le firmware à jour.
2. WiFi : SSID dédié scène, WPA2/WPA3 selon compatibilité des appareils ; **5 GHz** avec canal fixe (éviter DFS si la salle est chargée) ; 2,4 GHz éventuellement avec un autre SSID ou désactivé.
3. Réseau : convertir le port **WAN en LAN** (option de l'interface) afin d'avoir 3 ports pour XR18, Pi et service **(à vérifier dans l'interface)**.
4. DHCP : réservations d'adresses, par exemple Pi `192.168.8.10`, XR18 `192.168.8.20`.
5. Mode de fonctionnement : routeur sans WAN (aucune sortie internet).

## Faux internet (optionnel)
But : éviter que la tablette ou les téléphones ne quittent le WiFi parce qu'il n'a « pas d'internet ».

1. Sur le Pi : `network/captive204.py` (service `captive204.service`, port 80).
2. Sur l'Opal (OpenWrt, SSH) : ajouter à `/etc/dnsmasq.conf` (ou via `uci add_list dhcp.@dnsmasq[0].address=...`) :
   ```
   address=/connectivitycheck.gstatic.com/192.168.8.10
   address=/www.gstatic.com/192.168.8.10
   address=/clients3.google.com/192.168.8.10
   address=/captive.apple.com/192.168.8.10
   address=/tabletcaptiveportal.com/192.168.8.10
   ```
   puis `/etc/init.d/dnsmasq restart`. Les noms exacts varient selon la version d'Android et le fabricant **(à vérifier)**. Le trafic HTTPS (Android récent) peut contourner ce mécanisme.
3. Sur chaque appareil : désactiver « basculer automatiquement vers les données mobiles » / « WiFi+ » / « connexion réseau intelligente », et supprimer les autres réseaux enregistrés.
