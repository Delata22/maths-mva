#!/usr/bin/env bash
# Ajoute Maths MVA au lanceur d'applications Ubuntu.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$APPS" "$ICONS"
cp "$ROOT/mathsapp/assets/icon.svg" "$ICONS/maths-mva.svg"

cat > "$APPS/maths-mva.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Maths MVA
Comment=Remise a niveau mathematiques pour le M2 MVA
Exec=$ROOT/run.sh
Path=$ROOT
Icon=maths-mva
Terminal=false
Categories=Education;Science;Math;
StartupWMClass=maths-mva
DESKTOP

chmod +x "$APPS/maths-mva.desktop"
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "Installe. Cherchez « Maths MVA » dans le lanceur."
