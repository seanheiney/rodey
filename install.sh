#!/usr/bin/env bash
#
#  rodey installer  —  curl -fsSL https://rodey.sh | bash
#  (or: curl -fsSL https://raw.githubusercontent.com/seanheiney/rodey/main/install.sh | bash)
#
#  Installs the `rodey` CLI + MCP server for the RØDECaster Pro II into an
#  isolated environment. Safe to re-run; it upgrades in place.
#
set -euo pipefail

# run from a guaranteed-readable dir; never depend on the caller's CWD
# (e.g. brew refuses to run if the CWD is unreadable)
cd "${TMPDIR:-/tmp}" 2>/dev/null || cd /

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

# Which shell rc files exist / are relevant for this user.
rc_files() {
  local files=()
  case "$(basename "${SHELL:-/bin/zsh}")" in
    zsh) files+=("$HOME/.zshrc") ;;
    bash) files+=("$HOME/.bashrc" "$HOME/.bash_profile") ;;
    *) files+=("$HOME/.profile") ;;
  esac
  # also update whatever already exists, so PATH is set regardless of login shell
  for extra in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
    [ -f "$extra" ] && case " ${files[*]} " in *" $extra "*) ;; *) files+=("$extra");; esac
  done
  printf '%s\n' "${files[@]}"
}

ON_PATH_ALREADY=0
PATH_CONFIGURED=0

configure_path() {
  case ":$PATH:" in *":$BIN_DIR:"*) ON_PATH_ALREADY=1; return 0 ;; esac
  [ -n "${RODEY_NO_MODIFY_PATH:-}" ] && return 0
  local line="export PATH=\"$BIN_DIR:\$PATH\"  # added by rodey installer"
  local wrote=0 f
  while IFS= read -r f; do
    [ -e "$f" ] || : > "$f"
    grep -Fq "added by rodey installer" "$f" 2>/dev/null && { wrote=1; continue; }
    printf '\n%s\n' "$line" >> "$f" && wrote=1
  done < <(rc_files)
  [ "$wrote" = 1 ] && PATH_CONFIGURED=1
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
  configure_path
  printf "\n${G}${B}done.${X}\n"
  if [ "$ON_PATH_ALREADY" = 1 ]; then
    printf "try it now:\n"
    printf "    ${B}rodey channels${X}      ${DIM}# what's patched to each strip${X}\n\n"
  elif [ "$PATH_CONFIGURED" = 1 ]; then
    printf "added ${B}rodey${X} to your PATH. start a new terminal, or run:\n"
    printf "    ${B}export PATH=\"$BIN_DIR:\$PATH\"${X}\n"
    printf "then:\n"
    printf "    ${B}rodey channels${X}      ${DIM}# what's patched to each strip${X}\n\n"
  else
    printf "run it via its full path (PATH not modified):\n"
    printf "    ${B}$BIN_DIR/rodey channels${X}\n\n"
  fi
  printf "${DIM}  more:  rodey --help   |   MCP: add {\"command\":\"rodey-mcp\"} to your client config${X}\n"
  printf "${DIM}  unofficial; not affiliated with RØDE. firmware 1.7.x${X}\n\n"
}

main "$@"
