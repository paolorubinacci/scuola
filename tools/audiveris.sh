#!/usr/bin/env bash
# Prepara Audiveris (lettura ottica delle partiture) dall'ultima versione pubblicata su GitHub; scrive AUDIVERIS in $GITHUB_ENV.
# Il pacchetto .deb viene solo estratto (contiene gia' Java): niente installazione di sistema.
set -euo pipefail
D=$(mktemp -d)
gh release download -R Audiveris/audiveris --pattern '*.deb' -D "$D"
DEB=$(ls "$D"/*.deb | grep -iE 'ubuntu-?24|24\.04' | grep -iE 'x86_64|amd64' | head -1 || true)
DEB=${DEB:-$(ls "$D"/*.deb | grep -iE 'x86_64|amd64' | head -1)}
echo "Estraggo $(basename "$DEB")"
dpkg-deb -x "$DEB" "$HOME/audiveris"
BIN=$(find "$HOME/audiveris" -type f -name Audiveris -perm -u+x | head -1)
test -n "$BIN" || { echo "Audiveris non trovato nel pacchetto"; find "$HOME/audiveris" -maxdepth 4; exit 1; }
echo "AUDIVERIS=$BIN" >> "$GITHUB_ENV"
"$BIN" -batch -help 2>&1 | head -20 || true
