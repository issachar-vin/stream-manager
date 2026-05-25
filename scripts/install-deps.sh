#!/usr/bin/env bash
set -euo pipefail

# ── helpers ───────────────────────────────────────────────────────────────────

ok()   { echo "  [ok] $*"; }
info() { echo "  -->  $*"; }
fail() { echo "  [!]  $*" >&2; exit 1; }

# ── clear macOS quarantine ────────────────────────────────────────────────────

APP="/Applications/StreamManager.app"
if [[ -d "$APP" ]]; then
    xattr -cr "$APP"
    ok "Cleared macOS quarantine on $APP"
fi

# ── ffmpeg already available? ─────────────────────────────────────────────────

if command -v ffmpeg &>/dev/null; then
    ok "ffmpeg is already installed ($(ffmpeg -version 2>&1 | head -1))"
    exit 0
fi

echo "StreamManager requires ffmpeg for simultaneous streaming to multiple platforms."
echo ""

# ── ensure Homebrew ───────────────────────────────────────────────────────────

if ! command -v brew &>/dev/null; then
    # Apple Silicon puts brew at /opt/homebrew; Intel at /usr/local.
    # After a fresh install neither is on PATH yet, so check both.
    if [[ -x /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi

if ! command -v brew &>/dev/null; then
    info "Homebrew not found — installing it now."
    echo ""
    echo "  Homebrew requires the Xcode Command Line Tools."
    echo "  If a dialog appears asking to install them, click Install and wait"
    echo "  for it to finish before continuing."
    echo ""

    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Re-source brew for the rest of this script.
    if [[ -x /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    else
        fail "Homebrew installation finished but 'brew' could not be found. Open a new terminal and run this script again."
    fi

    ok "Homebrew installed."
else
    ok "Homebrew is already installed."
fi

# ── install ffmpeg ────────────────────────────────────────────────────────────

info "Installing ffmpeg..."
brew install ffmpeg
ok "ffmpeg installed — StreamManager is ready to use."
