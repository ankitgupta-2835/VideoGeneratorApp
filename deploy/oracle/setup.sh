#!/usr/bin/env bash
#
# Oracle Cloud Always Free VM bootstrap for VideoGeneratorApp.
#
# Installs system dependencies, clones/updates the repo, creates a virtualenv,
# installs the package, and seeds `.env` from the template. Safe to re-run: it
# only installs/updates what is missing or out of date.
#
# Usage:
#   bash deploy/oracle/setup.sh                  # clone/update into $HOME/VideoGeneratorApp
#   REPO_URL=<url> REPO_DIR=<dir> bash deploy/oracle/setup.sh
#
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ankitgupta-2835/VideoGeneratorApp.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
REPO_DIR="${REPO_DIR:-$HOME/VideoGeneratorApp}"
VENV_DIR="${VENV_DIR:-$REPO_DIR/.venv}"

log() { printf '[setup] %s\n' "$*"; }

# ---- 1. System dependencies (idempotent apt install) ----------------------
# `apt-get install -y` is a no-op when the packages are already current.
if command -v apt-get >/dev/null 2>&1; then
  log "installing system packages (python3, venv, ffmpeg, git, jq)"
  sudo apt-get update -y
  sudo apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    ffmpeg \
    git \
    jq
else
  log "apt-get not found; skipping system package install (install python3/ffmpeg/git/jq manually)"
fi

# ---- 2. Clone or update the repository ------------------------------------
if [ -d "$REPO_DIR/.git" ]; then
  log "updating existing checkout at $REPO_DIR"
  git -C "$REPO_DIR" fetch --prune origin
  git -C "$REPO_DIR" checkout "$REPO_BRANCH"
  git -C "$REPO_DIR" pull --ff-only origin "$REPO_BRANCH"
elif [ -e "$REPO_DIR" ]; then
  log "ERROR: $REPO_DIR exists but is not a git checkout; move it aside and re-run"
  exit 1
else
  log "cloning $REPO_URL ($REPO_BRANCH) into $REPO_DIR"
  git clone --branch "$REPO_BRANCH" "$REPO_URL" "$REPO_DIR"
fi

# ---- 3. Virtualenv + editable install -------------------------------------
if [ ! -x "$VENV_DIR/bin/python" ]; then
  log "creating virtualenv at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi
log "installing package (editable) + edge-tts TTS into the venv"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -e "$REPO_DIR"
# edge-tts is an optional runtime dependency (lazy-imported for narration), so
# it is not pulled in by the package metadata; install it explicitly.
"$VENV_DIR/bin/python" -m pip install edge-tts

# ---- 4. Seed .env ----------------------------------------------------------
if [ ! -f "$REPO_DIR/.env" ]; then
  log "creating $REPO_DIR/.env from .env.example"
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
  log "WARNING: $REPO_DIR/.env still has empty placeholders — fill in your real keys."
else
  log "$REPO_DIR/.env already exists; leaving it untouched"
fi

# ---- 5. Next steps ---------------------------------------------------------
cat <<EOF

[setup] Done.

Next steps:
  1. Edit $REPO_DIR/.env and set your real keys (at minimum the LLM provider key).
  2. Verify the install:
       cd "$REPO_DIR" && "$VENV_DIR/bin/python" -m src.pipeline --category ai_tech --dry-run
  3. Schedule the daily batch — either:
       crontab -e                    # see deploy/oracle/videogen.cron.example
     or install the systemd timer:
       sudo cp deploy/systemd/videogen.* /etc/systemd/system/
       sudo systemctl enable --now videogen.timer
  4. See docs/deploy.md for the full runbook (Colab GPU step, secrets matrix, re-runs).
EOF
