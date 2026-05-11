#!/usr/bin/env bash
# =============================================================================
#  IRIS — Setup Script
#  Clones all 7 module repos into the modules/ directory.
#  Run this once after cloning the main IRIS-Admin repo.
#
#  Usage:
#      chmod +x setup.sh
#      ./setup.sh
# =============================================================================

set -e  # exit immediately on any error

MODULES_DIR="$(dirname "$0")/modules"
mkdir -p "$MODULES_DIR"

echo ""
echo "============================================================"
echo "  IRIS — Cloning all module repositories"
echo "============================================================"
echo ""

clone_module() {
    local name="$1"
    local url="$2"
    local target="$MODULES_DIR/$name"

    if [ -d "$target/.git" ]; then
        echo "  [✓] $name already cloned — pulling latest…"
        git -C "$target" pull --quiet
    else
        echo "  [↓] Cloning $name…"
        git clone --quiet "$url" "$target"
        echo "  [✓] $name ready."
    fi
}

clone_module "gps_navigation"    "https://github.com/Adithya2369/Voice-Guided-GPS-Navigation-for-the-Visually-Impaired.git"
clone_module "visionaid"         "https://github.com/Adithya2369/VisionAid-AI-Navigation-Assistant-for-the-Visually-Impaired.git"
clone_module "hybrid_navigation" "https://github.com/Adithya2369/AI-Vision-Assistant-for-the-Blind.git"
clone_module "face_recognition"  "https://github.com/Adithya2369/AI-Vision-Assistant-for-Real-Time-Face-Recognition.git"
clone_module "email_assistant"   "https://github.com/Adithya2369/AI-Voice-Based-Email-Assistant.git"
clone_module "scene_narrator"    "https://github.com/Adithya2369/AI-Scene-Narrator.git"
clone_module "sos_emergency"     "https://github.com/Adithya2369/Smart-SOS-alert-system.git"

echo ""
echo "============================================================"
echo "  All modules cloned successfully."
echo ""
echo "  Next steps:"
echo "    1. Set your Porcupine key:"
echo "         export PORCUPINE_ACCESS_KEY=\"your_key_here\""
echo "    2. Configure each module (API keys, SERVER_IP, etc.)"
echo "         See README.md → Per-Module Configuration"
echo "    3. Run IRIS:"
echo "         python3 iris_admin.py"
echo "============================================================"
echo ""