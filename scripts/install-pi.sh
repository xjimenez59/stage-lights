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

for unit in spi-dmx captive204; do
  sed "s|@REPO@|$REPO|g; s|@USER@|$USER_NAME|g" "$REPO/scripts/$unit.service" \
    > "/etc/systemd/system/$unit.service"
done
systemctl daemon-reload
echo "Unités installées mais NON activées. Après les tests :"
echo "  sudo systemctl enable --now spi-dmx"
echo "  sudo systemctl enable --now captive204   # optionnel"
