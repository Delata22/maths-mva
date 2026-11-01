#!/usr/bin/env bash
# Ajoute FastLearning au lanceur d'applications Ubuntu.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$APPS" "$ICONS"
cp "$ROOT/mathsapp/assets/icon.svg" "$ICONS/fastlearning.svg"

cat > "$APPS/fastlearning.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=FastLearning
Comment=Cursus scientifiques generes a la demande
Exec=$ROOT/run.sh
Path=$ROOT
Icon=fastlearning
Terminal=false
Categories=Education;Science;
StartupWMClass=fastlearning
DESKTOP

chmod +x "$APPS/fastlearning.desktop"
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "Installe. Cherchez « FastLearning » dans le lanceur."
