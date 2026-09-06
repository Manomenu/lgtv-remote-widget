#!/usr/bin/env bash
# Instaluje pilota LG: usługę w tle i rozszerzenie GNOME Shell.
#
# Idempotentny — można puszczać wielokrotnie. Nie potrzebuje uprawnień roota
# i nie dotyka niczego poza katalogami użytkownika. NIGDY nie nadpisuje
# istniejącej konfiguracji; zamiast tego mówi, czego w niej brakuje.
#
# Użycie:
#   ./setup.sh              — zainstaluj albo zaktualizuj
#   ./setup.sh --no-enable  — zainstaluj pliki, ale nie uruchamiaj usługi
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UUID="lgtv-remote@maniumek"
SERVICE="lgtv-remote.service"

CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
RUNTIME_HOME="${XDG_RUNTIME_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}}"

CONFIG_DIR="$CONFIG_HOME/lgtv-remote"
CONFIG_FILE="$CONFIG_DIR/config.ini"
EXT_DIR="$DATA_HOME/gnome-shell/extensions/$UUID"
UNIT_FILE="$CONFIG_HOME/systemd/user/$SERVICE"
STATE_DIR="$STATE_HOME/lgtv-remote"
LEGACY_ENV="$HOME/scripts/lgtv/lgtv.env"

ENABLE=1
[[ "${1:-}" == "--no-enable" ]] && ENABLE=0

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '  \033[33m! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

# --- 1. czy jest czym to uruchomić -------------------------------------------
bold "Checking requirements"

command -v python3 >/dev/null || die "python3 not found"
python3 - <<'PY' || die "python 3.11 or newer is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
info "python3 $(python3 -c 'import platform; print(platform.python_version())')"

# PyGObject daje D-Bus bez żadnej zależności spoza pakietów dystrybucji.
python3 -c "import gi; gi.require_version('Gio', '2.0'); from gi.repository import Gio" 2>/dev/null \
  || die "PyGObject is missing — install it with: sudo dnf install python3-gobject-base"
info "PyGObject present"

command -v ssh >/dev/null || die "ssh not found"
command -v systemctl >/dev/null || die "systemctl not found"

if ! command -v gnome-extensions >/dev/null; then
  warn "gnome-extensions not found — the widget will be installed but not enabled"
fi

# --- 2. konfiguracja ----------------------------------------------------------
bold "Configuration"

mkdir -p "$CONFIG_DIR"

if [[ -f "$CONFIG_FILE" ]]; then
  info "keeping your existing $CONFIG_FILE"

  # Nie ruszamy zawartości — sprawdzamy tylko, czy nowe wydanie nie przyniosło
  # kluczy, których nie ma u ciebie. To cała potrzebna „migracja konfiguracji”.
  missing="$(python3 - "$REPO/setup.cfg.example" "$CONFIG_FILE" <<'PY'
import configparser, sys

example, current = (configparser.ConfigParser() for _ in range(2))
example.read(sys.argv[1], encoding="utf-8")
current.read(sys.argv[2], encoding="utf-8")

gaps = [
    f"{section}.{key}"
    for section in example.sections()
    for key in example[section]
    if not current.has_option(section, key)
]
print(" ".join(gaps))
PY
)"
  if [[ -n "$missing" ]]; then
    warn "settings missing from your file (built-in defaults apply):"
    for key in $missing; do warn "    $key"; done
    warn "see $REPO/setup.cfg.example for what they do"
  fi
else
  if [[ -f "$REPO/setup.cfg" ]]; then
    source_file="$REPO/setup.cfg"
    info "installing your setup.cfg"
  else
    source_file="$REPO/setup.cfg.example"
    info "no setup.cfg found — starting from the template"
  fi
  install -m 600 "$source_file" "$CONFIG_FILE"

  # Wartości z poprzedniego zestawu skryptów, jeśli tam są — żeby nie
  # przepisywać adresu MAC z palca.
  if [[ "$source_file" == *example && -f "$LEGACY_ENV" ]]; then
    # shellcheck source=/dev/null
    ( set +u; source "$LEGACY_ENV"
      for pair in "host:${LGTV_HOST:-}" "mac:${LGTV_MAC:-}" "broadcast:${LGTV_BROADCAST:-}"; do
        key="${pair%%:*}"; value="${pair#*:}"
        [[ -n "$value" ]] || continue
        sed -i "0,/^${key} =.*/s||${key} = ${value}|" "$CONFIG_FILE"
      done )
    info "seeded host, MAC and broadcast from $LEGACY_ENV"
  fi

  if ! grep -qE '^mac = .+' "$CONFIG_FILE"; then
    warn "no MAC address set — the widget will be able to switch the TV off but not on"
    warn "add it to $CONFIG_FILE under [tv]"
  fi
fi
chmod 600 "$CONFIG_FILE"
mkdir -p "$STATE_DIR"

# --- 3. rozszerzenie ----------------------------------------------------------
bold "GNOME Shell extension"

mkdir -p "$(dirname "$EXT_DIR")"
if [[ -e "$EXT_DIR" && ! -L "$EXT_DIR" ]]; then
  die "$EXT_DIR exists and is not a symlink — remove it by hand first"
fi
# Dowiązanie, a nie kopia: zmiana w repozytorium jest od razu tym, co ładuje
# Shell, bez powtarzania instalacji.
ln -sfn "$REPO/extension" "$EXT_DIR"
info "linked $EXT_DIR -> $REPO/extension"

# --- 4. usługa ----------------------------------------------------------------
bold "Background service"

mkdir -p "$(dirname "$UNIT_FILE")"
sed -e "s|@REPO@|$REPO|g" \
    -e "s|@STATE@|$STATE_DIR|g" \
    -e "s|@RUNTIME@|$RUNTIME_HOME/lgtv-remote|g" \
    "$REPO/systemd/$SERVICE.in" > "$UNIT_FILE"
info "wrote $UNIT_FILE"

# Zaczepienie usługi przeniosło się z default.target na graphical-session.target.
# `systemctl disable` czyta bieżący plik unitu, więc starego dowiązania samo nie
# usunie — zostałoby po nim martwe "wants" i ostrzeżenie przy każdym starcie.
STALE_WANT="$CONFIG_HOME/systemd/user/default.target.wants/$SERVICE"
if [[ -L "$STALE_WANT" ]]; then
  rm -f "$STALE_WANT"
  info "removed the stale default.target link (the service now follows the login session)"
fi

systemctl --user daemon-reload

if [[ "$ENABLE" -eq 1 ]]; then
  systemctl --user enable --now "$SERVICE"
  sleep 2
  if systemctl --user is-active --quiet "$SERVICE"; then
    info "service running"
  else
    warn "the service did not start — see: journalctl --user -u $SERVICE -n 30"
  fi
else
  info "skipped starting the service (--no-enable)"
fi

if command -v gnome-extensions >/dev/null; then
  gnome-extensions enable "$UUID" 2>/dev/null \
    && info "extension enabled" \
    || warn "could not enable the extension yet — it is registered after the next login"
fi

# --- 5. co dalej --------------------------------------------------------------
bold "Done"
cat <<EOF

  Settings   $CONFIG_FILE
  Logs       $STATE_DIR/actions.log
             $STATE_DIR/errors.log
  Service    systemctl --user status $SERVICE

  Log out and back in to load the widget. Wayland cannot reload GNOME Shell
  in place, so there is no way around it.

  To try it without logging out:
      dbus-run-session -- gnome-shell --nested --wayland

EOF
