#!/usr/bin/env bash
# Installa Audiveris (lettura ottica delle partiture) dall'ultima versione pubblicata su GitHub; scrive AUDIVERIS in $GITHUB_ENV.
set -euo pipefail
D=$(mktemp -d)
gh release view -R Audiveris/audiveris --json tagName,assets --jq '.tagName, (.assets[].name)'
gh release download -R Audiveris/audiveris --pattern '*.deb' -D "$D"
DEB=$(ls "$D"/*.deb | grep -iE 'ubuntu-?24|24\.04' | grep -iE 'x86_64|amd64' | head -1 || true)
DEB=${DEB:-$(ls "$D"/*.deb | grep -iE 'x86_64|amd64' | head -1)}
echo "Installo $DEB"
sudo apt-get update -qq
sudo apt-get install -y -qq "$DEB" tesseract-ocr > /dev/null
BIN=$(dpkg -L audiveris 2>/dev/null | grep -E '/bin/Audiveris$' | head -1 || true)
BIN=${BIN:-$(find /opt /usr -type f -name Audiveris -perm -u+x 2>/dev/null | head -1)}
test -n "$BIN" || { echo "Audiveris non trovato dopo l'installazione"; exit 1; }
echo "AUDIVERIS=$BIN" >> "$GITHUB_ENV"
"$BIN" -help 2>&1 | head -5 || true
