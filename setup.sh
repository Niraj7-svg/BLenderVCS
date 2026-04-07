#!/usr/bin/env bash
# =============================================================================
#  BlenderVCS — Setup Script
#  Run once after cloning the repo.
#
#  What this does automatically:
#    1. Detects your OS (macOS / Linux / Windows via Git Bash)
#    2. Installs rclone if missing
#    3. Walks you through Google Drive auth (browser opens once)
#    4. Verifies the connection
#    5. Tells you the remote name to paste into Blender
#
#  Nothing is installed system-wide without your knowledge.
#  rclone config is stored in ~/.config/rclone/rclone.conf
# =============================================================================

set -e  # exit on any error

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'  # no colour

step()    { echo -e "\n${BLUE}${BOLD}━━  $1${NC}"; }
ok()      { echo -e "${GREEN}✔  $1${NC}"; }
warn()    { echo -e "${YELLOW}⚠  $1${NC}"; }
info()    { echo -e "   ${CYAN}$1${NC}"; }
ask()     { echo -e "\n${BOLD}$1${NC}"; }
die()     { echo -e "\n${RED}✘  $1${NC}"; exit 1; }

# ── Banner ────────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║         BlenderVCS  —  Setup Wizard          ║"
echo "  ║                                              ║"
echo "  ║  Sets up rclone + Google Drive in ~5 min     ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  This script will:"
echo -e "  ${CYAN}1.${NC} Install rclone on your machine"
echo -e "  ${CYAN}2.${NC} Connect rclone to your Google Drive"
echo -e "  ${CYAN}3.${NC} Verify everything works"
echo ""
echo -e "  You only need to do this ${BOLD}once${NC}."
echo ""
read -rp "  Press ENTER to start…"

# ── Detect OS ─────────────────────────────────────────────────────────────────
step "Detecting operating system…"
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin)
        OS_NAME="macOS"
        ok "macOS detected (arch: $ARCH)"
        ;;
    Linux)
        OS_NAME="Linux"
        ok "Linux detected (arch: $ARCH)"
        ;;
    MINGW*|MSYS*|CYGWIN*)
        OS_NAME="Windows"
        ok "Windows (Git Bash) detected"
        ;;
    *)
        die "Unsupported OS: $OS. Please install rclone manually from https://rclone.org/install/"
        ;;
esac

# ── Step 1: Install rclone ────────────────────────────────────────────────────
step "Installing rclone…"

if command -v rclone &>/dev/null; then
    RCLONE_VER=$(rclone --version | head -1)
    ok "rclone already installed: $RCLONE_VER"
    RCLONE_INSTALLED=true
else
    info "rclone not found — installing now…"
    RCLONE_INSTALLED=false
fi

if [ "$RCLONE_INSTALLED" = false ]; then
    case "$OS_NAME" in

        macOS)
            # ── Try Homebrew first ────────────────────────────────────────────
            if command -v brew &>/dev/null; then
                info "Installing via Homebrew…"
                brew install rclone
                ok "rclone installed via Homebrew."

            else
                # ── Direct binary download as fallback ────────────────────────
                info "Homebrew not found — downloading rclone binary directly…"

                # Pick the right architecture
                if [ "$ARCH" = "arm64" ]; then
                    RCLONE_ZIP="rclone-current-osx-arm64.zip"
                else
                    RCLONE_ZIP="rclone-current-osx-amd64.zip"
                fi

                RCLONE_URL="https://downloads.rclone.org/rclone-current-osx-amd64.zip"
                TMP_DIR=$(mktemp -d)

                info "Downloading from rclone.org…"
                curl -fsSL "https://downloads.rclone.org/$RCLONE_ZIP" \
                    -o "$TMP_DIR/rclone.zip"

                info "Unpacking…"
                unzip -q "$TMP_DIR/rclone.zip" -d "$TMP_DIR"

                # Find the binary inside the extracted folder
                RCLONE_BIN=$(find "$TMP_DIR" -name "rclone" -type f | head -1)
                if [ -z "$RCLONE_BIN" ]; then
                    die "Could not find rclone binary after extraction."
                fi

                # Install to /usr/local/bin (standard PATH location)
                info "Installing to /usr/local/bin/rclone (may ask for password)…"
                sudo mkdir -p /usr/local/bin
                sudo cp "$RCLONE_BIN" /usr/local/bin/rclone
                sudo chmod +x /usr/local/bin/rclone

                rm -rf "$TMP_DIR"
                ok "rclone installed to /usr/local/bin/rclone"
            fi
            ;;

        Linux)
            # rclone provides an official install script
            info "Running rclone's official install script…"
            curl -fsSL https://rclone.org/install.sh | sudo bash
            ok "rclone installed."
            ;;

        Windows)
            # Download and unzip into ~/bin
            info "Downloading rclone for Windows…"
            TMP_DIR=$(mktemp -d)
            RCLONE_URL="https://downloads.rclone.org/rclone-current-windows-amd64.zip"
            curl -fsSL "$RCLONE_URL" -o "$TMP_DIR/rclone.zip"
            unzip -q "$TMP_DIR/rclone.zip" -d "$TMP_DIR"
            mkdir -p "$HOME/bin"
            find "$TMP_DIR" -name "rclone.exe" -exec cp {} "$HOME/bin/rclone.exe" \;
            rm -rf "$TMP_DIR"
            export PATH="$HOME/bin:$PATH"
            ok "rclone installed to ~/bin/rclone.exe"
            warn "Add ~/bin to your system PATH to use rclone from any terminal."
            ;;
    esac

    # Verify install worked
    if ! command -v rclone &>/dev/null; then
        die "rclone install failed. Please install manually: https://rclone.org/install/"
    fi
fi

# Show version
ok "rclone version: $(rclone --version | head -1)"

# ── Step 2: Check if Google Drive remote already configured ───────────────────
step "Checking existing rclone configuration…"

REMOTE_NAME="gdrive"

# List configured remotes
EXISTING=$(rclone listremotes 2>/dev/null | tr -d ':' | tr '\n' ' ')

if echo "$EXISTING" | grep -qw "$REMOTE_NAME"; then
    ok "Remote '$REMOTE_NAME' is already configured."
    echo ""
    ask "Do you want to use the existing configuration? (y/n)"
    read -rp "  → " USE_EXISTING
    if [[ "$USE_EXISTING" =~ ^[Yy]$ ]]; then
        info "Using existing remote '$REMOTE_NAME'."
        SKIP_CONFIG=true
    else
        warn "Will reconfigure remote '$REMOTE_NAME'."
        SKIP_CONFIG=false
    fi
else
    info "No '$REMOTE_NAME' remote found — will set it up now."
    SKIP_CONFIG=false
fi

# ── Step 3: Configure Google Drive remote ─────────────────────────────────────
if [ "$SKIP_CONFIG" != true ]; then
    step "Configuring Google Drive remote…"
    echo ""
    echo -e "  ${BOLD}What happens next:${NC}"
    echo -e "  ${CYAN}1.${NC} rclone will start an interactive config session"
    echo -e "  ${CYAN}2.${NC} Your ${BOLD}browser will open${NC} to a Google sign-in page"
    echo -e "  ${CYAN}3.${NC} Sign in with the Google account where you want"
    echo -e "     your .blend files stored"
    echo -e "  ${CYAN}4.${NC} Click ${BOLD}Allow${NC} — that's it, done forever"
    echo ""
    echo -e "  ${YELLOW}When rclone asks you questions, type these answers:${NC}"
    echo ""
    echo -e "  ${BOLD}Storage type${NC}  →  type ${CYAN}drive${NC} and press Enter"
    echo -e "  ${BOLD}Client ID${NC}     →  just press Enter (leave blank)"
    echo -e "  ${BOLD}Client Secret${NC} →  just press Enter (leave blank)"
    echo -e "  ${BOLD}Scope${NC}         →  type ${CYAN}1${NC} (full access) and press Enter"
    echo -e "  ${BOLD}Service Account${NC} → just press Enter (leave blank)"
    echo -e "  ${BOLD}Advanced config${NC} → type ${CYAN}n${NC} and press Enter"
    echo -e "  ${BOLD}Use web browser${NC} → type ${CYAN}y${NC} and press Enter  ← browser opens here"
    echo -e "  ${BOLD}Is this OK?${NC}   →  type ${CYAN}y${NC} and press Enter"
    echo ""
    read -rp "  Press ENTER when ready to start the rclone config…"
    echo ""

    # Run rclone config create for Google Drive
    # We use 'rclone config create' which is non-interactive for most fields,
    # then 'rclone config reconnect' to do the browser auth step.
    #
    # WHY NOT FULLY AUTOMATE:
    # Google OAuth requires a real browser sign-in by a human.
    # There is no way to skip this step — it's a security requirement.
    # rclone handles the token exchange; we just need the user to click Allow.

    rclone config create "$REMOTE_NAME" drive \
        scope "drive" \
        2>/dev/null || true

    # Now do the auth (this opens the browser)
    echo ""
    info "Opening browser for Google sign-in…"
    rclone config reconnect "${REMOTE_NAME}:"

    ok "Google Drive configuration complete."
fi

# ── Step 4: Verify the connection ─────────────────────────────────────────────
step "Verifying connection to Google Drive…"

info "Listing root of your Google Drive (takes a few seconds)…"

if rclone lsd "${REMOTE_NAME}:" --max-depth 1 &>/dev/null; then
    ok "Connection verified! rclone can access your Google Drive."
else
    die (
        "Connection test failed.\n"
        "Try running 'rclone config reconnect ${REMOTE_NAME}:' manually."
    )
fi

# ── Step 5: Create the BlenderVCS folder ──────────────────────────────────────
step "Setting up BlenderVCS folder on Google Drive…"

if rclone lsd "${REMOTE_NAME}:BlenderVCS" &>/dev/null; then
    ok "BlenderVCS folder already exists on Drive."
else
    info "Creating BlenderVCS folder…"
    rclone mkdir "${REMOTE_NAME}:BlenderVCS"
    ok "BlenderVCS folder created."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║           Setup Complete!  ✔                 ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${BOLD}Your remote name:${NC}  ${CYAN}${REMOTE_NAME}${NC}"
echo ""
echo -e "  ${BOLD}Next steps:${NC}"
echo ""
echo -e "  ${CYAN}1.${NC} Install ${BOLD}blender_vcs.zip${NC} in Blender:"
echo -e "     Edit → Preferences → Add-ons → Install"
echo ""
echo -e "  ${CYAN}2.${NC} In Blender → press ${BOLD}N${NC} → go to the ${BOLD}VCS${NC} tab"
echo -e "     The remote name ${CYAN}${REMOTE_NAME}${NC} is already filled in"
echo -e "     Click ${BOLD}Connect${NC} to verify"
echo ""
echo -e "  ${CYAN}3.${NC} Open any ${BOLD}.blend${NC} file, type a message, click ${BOLD}Push${NC}"
echo -e "     Your file appears in Google Drive under:"
echo -e "     ${CYAN}BlenderVCS / <project-name> / <timestamp>_<message>.blend${NC}"
echo ""
echo -e "  That's it. Run this script again on any new machine"
echo -e "  and your Drive connection transfers automatically."
echo ""
