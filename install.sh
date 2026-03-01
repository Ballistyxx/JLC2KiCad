#!/usr/bin/env bash
# install.sh — Install the JLCPCB Component Importer plugin into KiCad.
#
# Creates symlinks from the KiCad scripting plugins directory to the
# jlcpcb_importer and vendor directories in this repository.  This
# allows live development: edits to the source are reflected immediately
# in KiCad after a restart.
#
# Usage:
#   ./install.sh          # auto-detect KiCad version
#   ./install.sh 9.0      # specify KiCad version explicitly

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Detect KiCad version ──────────────────────────────────────────────
if [[ -n "${1:-}" ]]; then
    KICAD_VERSION="$1"
else
    # Look for the most recent versioned directory under ~/.local/share/kicad/
    KICAD_BASE="${HOME}/.local/share/kicad"
    if [[ ! -d "$KICAD_BASE" ]]; then
        echo "Error: KiCad data directory not found at ${KICAD_BASE}"
        echo "Is KiCad installed?"
        exit 1
    fi
    KICAD_VERSION=$(ls -1 "$KICAD_BASE" | sort -V | tail -n1)
    if [[ -z "$KICAD_VERSION" ]]; then
        echo "Error: No KiCad version directories found in ${KICAD_BASE}"
        exit 1
    fi
fi

PLUGINS_DIR="${HOME}/.local/share/kicad/${KICAD_VERSION}/scripting/plugins"

echo "KiCad version: ${KICAD_VERSION}"
echo "Plugin directory: ${PLUGINS_DIR}"
echo ""

# ── Create plugin directory if needed ─────────────────────────────────
mkdir -p "$PLUGINS_DIR"

# ── Install symlinks ──────────────────────────────────────────────────
install_link() {
    local name="$1"
    local target="${SCRIPT_DIR}/${name}"
    local link="${PLUGINS_DIR}/${name}"

    if [[ ! -e "$target" ]]; then
        echo "Error: Source directory '${target}' does not exist."
        exit 1
    fi

    if [[ -L "$link" ]]; then
        existing=$(readlink -f "$link")
        if [[ "$existing" == "$(readlink -f "$target")" ]]; then
            echo "  ${name}: already linked (OK)"
            return
        fi
        echo "  ${name}: updating existing symlink"
        rm "$link"
    elif [[ -e "$link" ]]; then
        echo "  ${name}: WARNING — '${link}' exists and is not a symlink."
        echo "          Back it up or remove it, then re-run this script."
        exit 1
    fi

    ln -s "$target" "$link"
    echo "  ${name}: linked -> ${target}"
}

echo "Installing plugin..."
install_link "jlcpcb_importer"
install_link "vendor"

echo ""
echo "Installation complete."
echo ""
echo "Next steps:"
echo "  1. (Re)start KiCad."
echo "  2. Open the PCB Editor (pcbnew)."
echo "  3. The 'JLCPCB Component Importer' appears in the toolbar or"
echo "     under Tools > External Plugins."
echo ""
echo "To uninstall, run:"
echo "  rm \"${PLUGINS_DIR}/jlcpcb_importer\""
echo "  rm \"${PLUGINS_DIR}/vendor\""
