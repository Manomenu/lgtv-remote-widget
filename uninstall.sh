#!/usr/bin/env bash
# Usuwa wszystko, co zainstalował setup.sh — i nic poza tym.
#
# Kolejność ma znaczenie: najpierw zatrzymujemy to, co działa, dopiero potem
# kasujemy pliki. Konfiguracja i dzienniki to jedyne rzeczy, których nie da się
# odtworzyć z repozytorium, więc domyślnie ZOSTAJĄ — deinstalacja bywa
# preludium do ponownej instalacji.
#
# Użycie:
#   ./uninstall.sh             — usuń instalację, zachowaj ustawienia i dzienniki
#   ./uninstall.sh --purge     — usuń również ustawienia i dzienniki
#   ./uninstall.sh --dry-run   — tylko pokaż, co by się stało
set -euo pipefail

UUID="lgtv-remote@maniumek"
SERVICE="lgtv-remote.service"

CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
RUNTIME_HOME="${XDG_RUNTIME_DIR:-$CACHE_HOME}"

CONFIG_DIR="$CONFIG_HOME/lgtv-remote"
EXT_DIR="$DATA_HOME/gnome-shell/extensions/$UUID"
UNIT_FILE="$CONFIG_HOME/systemd/user/$SERVICE"
STATE_DIR="$STATE_HOME/lgtv-remote"
CACHE_DIR="$CACHE_HOME/lgtv-remote"
RUNTIME_DIR="$RUNTIME_HOME/lgtv-remote"

PURGE=0
DRY=0
for arg in "$@"; do
  case "$arg" in
    --purge)   PURGE=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

REMOVED=()
KEPT=()

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
step() { printf '  %s\n' "$*"; }

run() {
  if [[ "$DRY" -eq 1 ]]; then
    printf '  would run: %s\n' "$*"
  else
    "$@" >/dev/null 2>&1 || true
  fi
}

drop() {
  local path="$1"
  [[ -e "$path" || -L "$path" ]] || return 0
  if [[ "$DRY" -eq 1 ]]; then
    printf '  would remove: %s\n' "$path"
  else
    rm -rf "$path"
  fi
  REMOVED+=("$path")
}

[[ "$DRY" -eq 1 ]] && bold "Dry run — nothing will be changed"

# --- 1. zatrzymaj to, co działa ----------------------------------------------
bold "Stopping"
if command -v gnome-extensions >/dev/null; then
  step "disabling the extension"
  run gnome-extensions disable "$UUID"
fi
step "stopping the service"
run systemctl --user disable --now "$SERVICE"

# --- 2. pliki instalacji ------------------------------------------------------
bold "Removing installed files"

# Kasujemy dowiązanie tylko wtedy, gdy to faktycznie NASZE dowiązanie — gdyby
# ktoś trzymał tam własną kopię rozszerzenia, nie jest nasza do usuwania.
if [[ -L "$EXT_DIR" ]]; then
  drop "$EXT_DIR"
elif [[ -d "$EXT_DIR" ]]; then
  if [[ -f "$EXT_DIR/metadata.json" ]] && grep -q "\"$UUID\"" "$EXT_DIR/metadata.json"; then
    drop "$EXT_DIR"
  else
    KEPT+=("$EXT_DIR (not installed by this script)")
  fi
fi

drop "$UNIT_FILE"
run systemctl --user daemon-reload

# Cache i gniazdo SSH są z definicji odtwarzalne — lecą zawsze.
drop "$CACHE_DIR"
drop "$RUNTIME_DIR"

# --- 3. ustawienia i dzienniki ------------------------------------------------
bold "Settings and logs"
if [[ "$PURGE" -eq 1 ]]; then
  drop "$CONFIG_DIR"
  drop "$STATE_DIR"
else
  for path in "$CONFIG_DIR" "$STATE_DIR"; do
    [[ -e "$path" ]] && KEPT+=("$path")
  done
  step "kept — run with --purge to remove them too"
fi

# --- 4. podsumowanie ----------------------------------------------------------
bold "Summary"
if [[ ${#REMOVED[@]} -gt 0 ]]; then
  printf '  removed:\n'
  printf '    %s\n' "${REMOVED[@]}"
else
  printf '  nothing to remove — was it installed?\n'
fi
if [[ ${#KEPT[@]} -gt 0 ]]; then
  printf '  kept:\n'
  printf '    %s\n' "${KEPT[@]}"
fi

cat <<'EOF'

  Your own scripts in ~/scripts/lgtv were not touched — they are not ours.
  Log out and back in to drop the widget from the panel.

EOF
