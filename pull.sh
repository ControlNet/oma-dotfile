#!/usr/bin/env bash
set -euo pipefail

# Download opencode.jsonc + oh-my-opencode.jsonc + _AGENTS.md from GitHub repo and overwrite *user-level* config.
# After install, if opencode.json / oh-my-opencode.json exists, rename it to *.json.bak-<timestamp>
# so only *.jsonc remains as the active config.

REPO_OWNER="${REPO_OWNER:-ControlNet}"
REPO_NAME="${REPO_NAME:-omo-dotfile}"
REPO_REV="${REPO_REV:-master}"   # branch, tag, or commit hash
CONFIG_DIR="${CONFIG_DIR:-}"  # optional override
NO_BACKUP="${NO_BACKUP:-0}"   # set to 1 to disable backing up existing .jsonc before overwrite (still renames .json)

usage() {
  cat <<'EOF'
sync-opencode-user.sh

Env:
  REPO_OWNER=ControlNet
  REPO_NAME=omo-dotfile
  REPO_REV=master   (branch, tag, or commit hash)
  CONFIG_DIR=<optional override, default: ${XDG_CONFIG_HOME:-~/.config}/opencode>
  NO_BACKUP=1   (optional) do not backup existing .jsonc before overwrite

Examples:
  curl -fsSL <RAW_SCRIPT_URL> | bash
  REPO_REV=v1.0.0 curl -fsSL <RAW_SCRIPT_URL> | bash
  CONFIG_DIR="$HOME/.config/opencode" curl -fsSL <RAW_SCRIPT_URL> | bash
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }; }

fetch() {
  local url="$1" out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -H 'Cache-Control: no-cache' -o "$out" "$url"
  else
    need_cmd wget
    wget -qO "$out" "$url"
  fi
  [[ -s "$out" ]] || { echo "Download failed or empty: $url" >&2; exit 1; }
}

ts() { date +"%Y%m%d-%H%M%S"; }

backup_and_install_file() {
  local src="$1" dst="$2" stamp="$3"
  mkdir -p "$(dirname "$dst")"
  if [[ "$NO_BACKUP" != "1" && -f "$dst" ]]; then
    cp -a "$dst" "${dst}.bak-${stamp}"
  fi
  mv -f "$src" "$dst"
}

rename_json_if_exists() {
  local json_path="$1" stamp="$2"
  if [[ -f "$json_path" ]]; then
    local bak="${json_path}.bak-${stamp}"
    # avoid collision just in case
    if [[ -e "$bak" ]]; then
      bak="${bak}-$$"
    fi
    mv -f "$json_path" "$bak"
  fi
}

# Decide user-level config dir
if [[ -z "$CONFIG_DIR" ]]; then
  XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
  CONFIG_DIR="${XDG_CONFIG_HOME}/opencode"
fi
mkdir -p "$CONFIG_DIR"

# Build download URLs for the config files
URL_OPENCODE="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${REPO_REV}/opencode.jsonc"
URL_OMOC="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${REPO_REV}/oh-my-opencode.jsonc"
URL_AGENTS="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${REPO_REV}/_AGENTS.md"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

STAMP="$(ts)"
TMP_OPENCODE="$TMP_DIR/opencode.jsonc"
TMP_OMOC="$TMP_DIR/oh-my-opencode.jsonc"
TMP_AGENTS="$TMP_DIR/_AGENTS.md"

echo "[1/3] Downloading:"
echo "      - $URL_OPENCODE"
echo "      - $URL_OMOC"
echo "      - $URL_AGENTS"

fetch "$URL_OPENCODE" "$TMP_OPENCODE"
fetch "$URL_OMOC" "$TMP_OMOC"
fetch "$URL_AGENTS" "$TMP_AGENTS"

echo "[2/3] Installing to user-level config dir: $CONFIG_DIR"
backup_and_install_file "$TMP_OPENCODE" "$CONFIG_DIR/opencode.jsonc" "$STAMP"
backup_and_install_file "$TMP_OMOC" "$CONFIG_DIR/oh-my-opencode.jsonc" "$STAMP"
backup_and_install_file "$TMP_AGENTS" "$CONFIG_DIR/AGENTS.md" "$STAMP"

echo "[3/3] Renaming legacy .json (if exists) so only .jsonc remains active"
rename_json_if_exists "$CONFIG_DIR/opencode.json" "$STAMP"
rename_json_if_exists "$CONFIG_DIR/oh-my-opencode.json" "$STAMP"

echo "Done."
echo "Timestamp: $STAMP"
if [[ "$NO_BACKUP" != "1" ]]; then
  echo "Backups: *.bak-${STAMP}"
fi
