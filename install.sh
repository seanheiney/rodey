#!/usr/bin/env bash
#
#  rodey installer  —  curl -fsSL https://rodey.sh | bash
#  (or: curl -fsSL https://raw.githubusercontent.com/seanheiney/rodey/main/install.sh | bash)
#
#  Installs the `rodey` CLI + MCP server for the RØDECaster Pro II into an
#  isolated environment. Safe to re-run; it upgrades in place.
#
set -euo pipefail

REPO="seanheiney/rodey"
BRANCH="${RODEY_BRANCH:-main}"
PREFIX="${RODEY_PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/rodey"
BIN_DIR="$PREFIX/bin"
VENV="$APP_DIR/venv"

# ── pretty output ─────────────────────────────────────────────────────────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; X=$'\033[0m'
else B=; DIM=; G=; Y=; R=; C=; X=; fi
step() { printf "${C}▸${X} %s\n" "$1"; }
ok()   { printf "${G}✓${X} %s\n" "$1"; }
warn() { printf "${Y}!${X} %s\n" "$1"; }
die()  { printf "${R}✗ %s${X}\n" "$1" >&2; exit 1; }

banner() {
  printf "\n${B}  rodey${X} ${DIM}— control your RØDECaster Pro II from the CLI${X}\n"
  printf "${DIM}  like a roadie who runs the gear${X}\n\n"
}

# ── platform + prerequisites ──────────────────────────────────────────────────
detect_os() {
  case "$(uname -s)" in
    Darwin) OS=mac ;;
    Linux)  OS=linux ;;
    *) die "unsupported OS: $(uname -s). rodey supports macOS and Linux." ;;
  esac
}

need_python() {
  # find a python >= 3.10
  for py in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$py" >/dev/null 2>&1; then
      if "$py" -c 'import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)' 2>/dev/null; then
        PYTHON="$py"; return 0
      fi
    fi
  done
  return 1
}

install_hidapi() {
  # the native library the `hid` python module binds to
  if [ "$OS" = mac ]; then
    if ! brew list hidapi >/dev/null 2>&1; then
      command -v brew >/dev/null 2>&1 || die "Homebrew is required on macOS: https://brew.sh"
      step "installing hidapi (Homebrew)…"; brew install hidapi >/dev/null
    fi
  else
    if command -v apt-get >/dev/null 2>&1; then
      step "installing libhidapi (apt, may prompt for sudo)…"
      sudo apt-get update -qq && sudo apt-get install -y -qq libhidapi-hidraw0 libhidapi-dev python3-venv
    elif command -v dnf >/dev/null 2>&1; then
      step "installing hidapi (dnf)…"; sudo dnf install -y -q hidapi hidapi-devel python3-virtualenv
    elif command -v pacman >/dev/null 2>&1; then
      step "installing hidapi (pacman)…"; sudo pacman -S --noconfirm --needed hidapi
    else
      warn "couldn't detect a package manager — install 'hidapi' manually if the next step fails"
    fi
  fi
}

install_udev_rule() {
  # Linux only: let non-root users open the RØDECaster HID interface
  [ "$OS" = linux ] || return 0
  local rule=/etc/udev/rules.d/70-rodecaster.rules
  [ -f "$rule" ] && return 0
  step "adding udev rule for non-root HID access…"
  echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="19f7", MODE="0660", TAG+="uaccess"' \
    | sudo tee "$rule" >/dev/null
  sudo udevadm control --reload-rules && sudo udevadm trigger 2>/dev/null || true
  warn "unplug and replug the RØDECaster once so the new permission takes effect"
}

# ── install ───────────────────────────────────────────────────────────────────
install_rodey() {
  step "creating isolated environment in ${DIM}$VENV${X}"
  mkdir -p "$APP_DIR" "$BIN_DIR"
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  step "installing rodey from github.com/$REPO@$BRANCH …"
  "$VENV/bin/pip" install --quiet --upgrade "git+https://github.com/$REPO@$BRANCH"

  step "linking the ${B}rodey${X} command into ${DIM}$BIN_DIR${X}"
  ln -sf "$VENV/bin/rodey" "$BIN_DIR/rodey"
  ln -sf "$VENV/bin/rodey-mcp" "$BIN_DIR/rodey-mcp"
}

check_path() {
  case ":$PATH:" in
    *":$BIN_DIR:"*) : ;;
    *)
      warn "$BIN_DIR is not on your PATH"
      local rc; rc="$HOME/.zshrc"; [ -n "${BASH_VERSION:-}" ] && rc="$HOME/.bashrc"
      printf '  add it with:\n    ${B}echo '\''export PATH="%s:$PATH"'\'' >> %s && source %s${X}\n' \
        "$BIN_DIR" "$rc" "$rc"
      ;;
  esac
}

verify() {
  if "$VENV/bin/rodey" --help >/dev/null 2>&1 || "$VENV/bin/python" -c 'import rodey' 2>/dev/null; then
    ok "rodey installed"
  else
    die "install completed but rodey failed to run — please open an issue"
  fi
}

main() {
  banner
  detect_os
  need_python || die "Python 3.9+ is required. Install it, then re-run this."
  ok "python: $($PYTHON --version 2>&1)"
  install_hidapi
  install_udev_rule
  install_rodey
  verify
  check_path
  printf "\n${G}${B}done.${X} try it:\n"
  printf "    ${B}rodey channels${X}      ${DIM}# what's patched to each strip${X}\n"
  printf "    ${B}rodey get noiseGateOn${X}\n"
  printf "    ${B}rodey --help${X}\n\n"
  printf "${DIM}  MCP server: add {\"command\":\"rodey-mcp\"} to your client config.${X}\n"
  printf "${DIM}  Unofficial; not affiliated with RØDE. Firmware 1.7.x.${X}\n\n"
}

main "$@"
