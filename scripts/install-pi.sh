#!/usr/bin/env bash
# Installation sur le Pi (Raspberry Pi OS Lite 32 bits). À lancer en root depuis le dépôt copié.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "à lancer avec sudo" >&2; exit 1; fi
REPO="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:-pi}"

apt-get update
apt-get install -y python3 python3-spidev ola ola-python rsync || \
  echo "!! un paquet manque (ola ?) : voir CLAUDE.md, points à vérifier"

CONFIG=/boot/firmware/config.txt
[ -f "$CONFIG" ] || CONFIG=/boot/config.txt
if ! grep -q "stage-lights" "$CONFIG"; then
  { echo; echo "# --- stage-lights ---"; cat "$REPO/config/config.txt.snippet"; } >> "$CONFIG"
  echo "config.txt mis à jour ($CONFIG) : redémarrage nécessaire"
fi

install -m 644 "$REPO/config/ola-uartdmx.conf" /etc/ola/ola-uartdmx.conf || true

# Données du contrôleur : copiées une seule fois (jamais écrasées lors d'une mise à jour).
DATA=/var/lib/stage-lights
install -d -o "$USER_NAME" -g "$USER_NAME" "$DATA"
if [ ! -e "$DATA/fixtures.json" ]; then
  install -o "$USER_NAME" -g "$USER_NAME" -m 644 "$REPO"/config/data-example/*.json "$DATA/"
  echo "données d'exemple installées dans $DATA (4 PARty Spot en 6 canaux, adresses 1, 7, 13, 19)"
fi

for unit in spi-dmx stage-control captive204; do
  sed "s|@REPO@|$REPO|g; s|@USER@|$USER_NAME|g" "$REPO/scripts/$unit.service" \
    > "/etc/systemd/system/$unit.service"
done
systemctl daemon-reload
echo "Unités installées mais NON activées. Après les tests de docs/plan-de-tests.md :"
echo "  sudo systemctl enable --now spi-dmx stage-control"
echo "  sudo systemctl enable --now captive204   # optionnel"
echo "Interface : http://<ip-du-pi>:8080"
