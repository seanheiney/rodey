#!/usr/bin/env bash
#
#  rodey installer / updater / uninstaller
#  curl -fsSL https://raw.githubusercontent.com/seanheiney/rodey/main/install.sh | bash
#
#  Subcommands (default: install):
#    install     install or upgrade rodey into an isolated environment
#    update      pull the latest rodey into the existing environment
#    uninstall   remove rodey, its PATH entry, and (Linux) its udev rule
#
#  After install, these are also available as:
#    rodey-update       rodey-uninstall
#
set -euo pipefail

# Resolve our own path BEFORE cd'ing away, so install_self can copy this file.
# When piped (curl | bash) BASH_SOURCE isn't a real file — leave SCRIPT_FILE empty
# and install_self will fetch a fresh copy from SELF_URL instead.
_src="${BASH_SOURCE[0]:-}"
case "$_src" in
  ""|bash|*/bash|main) SCRIPT_FILE="" ;;
  *) SCRIPT_FILE="$(cd "$(dirname "$_src")" 2>/dev/null && pwd)/$(basename "$_src")"
     [ -f "$SCRIPT_FILE" ] || SCRIPT_FILE="" ;;
esac

# run from a guaranteed-readable dir; never depend on the caller's CWD
# (e.g. brew refuses to run if the CWD is unreadable)
cd "${TMPDIR:-/tmp}" 2>/dev/null || cd /

REPO="seanheiney/rodey"
BRANCH="${RODEY_BRANCH:-main}"
PREFIX="${RODEY_PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/rodey"
BIN_DIR="$PREFIX/bin"
VENV="$APP_DIR/venv"
TARBALL="https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz"

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

MIN="3.10"                       # target: Python 3.10+ (also what the MCP server needs)

find_python() {                  # sets PYTHON if a >=3.10 interpreter exists
  local py
  for py in python3.13 python3.12 python3.11 python3.10 python3; do
    command -v "$py" >/dev/null 2>&1 || continue
    if "$py" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
      PYTHON="$py"; return 0
    fi
  done
  return 1
}

install_python() {               # install a modern Python via the OS package manager
  step "installing Python 3.10+ …"
  if [ "$OS" = mac ]; then
    command -v brew >/dev/null 2>&1 || die "Homebrew is required to install Python on macOS: https://brew.sh"
    brew install python@3.12 >/dev/null 2>&1 || brew install python >/dev/null
    # make sure the freshly-installed python is on PATH for this run
    local pfx; pfx="$(brew --prefix 2>/dev/null)"; [ -n "$pfx" ] && export PATH="$pfx/bin:$PATH"
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-venv python3-pip \
      || sudo apt-get install -y -qq python3.12 python3.12-venv \
      || sudo apt-get install -y -qq python3.11 python3.11-venv
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y -q python3 python3-pip || sudo dnf install -y -q python3.12
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --noconfirm --needed python
  else
    die "no supported package manager to install Python. Install Python 3.10+ and re-run."
  fi
}

ensure_python() {                # guarantee PYTHON points at a >=3.10 interpreter
  if find_python; then
    ok "python: $($PYTHON --version 2>&1)"
    return 0
  fi
  warn "Python $MIN+ not found"
  install_python
  find_python || die "installed Python but still can't find a $MIN+ interpreter on PATH.
  Open a new terminal and re-run, or install Python $MIN+ manually."
  ok "python: $($PYTHON --version 2>&1) (installed)"
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
HAS_MCP=0
install_rodey() {
  step "creating isolated environment in ${DIM}$VENV${X}"
  mkdir -p "$APP_DIR" "$BIN_DIR"
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip

  # Install from a source tarball, not git+https — so `git` is NOT required.
  step "installing rodey …"
  "$VENV/bin/pip" install --quiet --upgrade "$TARBALL"

  # The MCP server needs the `mcp` package, which requires Python >= 3.10.
  # Best-effort: never let it fail the core CLI install.
  if "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)'; then
    step "installing MCP server support …"
    if "$VENV/bin/pip" install --quiet "mcp>=1.0,<2" 2>/dev/null        && "$VENV/bin/python" -c 'import mcp.server.fastmcp' 2>/dev/null; then
      HAS_MCP=1
    else
      warn "MCP support unavailable (couldn't install 'mcp'); the CLI still works"
    fi
  else
    warn "MCP server needs Python 3.10+ (you have $("$VENV/bin/python" -V 2>&1 | awk '{print $2}')); installing CLI only"
  fi

  step "linking the ${B}rodey${X} command into ${DIM}$BIN_DIR${X}"
  ln -sf "$VENV/bin/rodey" "$BIN_DIR/rodey"
  [ "$HAS_MCP" = 1 ] && ln -sf "$VENV/bin/rodey-mcp" "$BIN_DIR/rodey-mcp"
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
    ok "rodey ready"
  else
    die "completed but rodey failed to run — please open an issue"
  fi
}

installed_version() {
  "$VENV/bin/python" -c 'import rodey; print(rodey.__version__)' 2>/dev/null || echo "?"
}

# Save this script + thin wrappers so update/uninstall work without the curl URL.
install_self() {
  local self="$APP_DIR/install.sh"
  if [ -n "$SCRIPT_FILE" ] && [ -f "$SCRIPT_FILE" ]; then
    cp "$SCRIPT_FILE" "$self"
  else
    curl -fsSL "$SELF_URL" -o "$self"   # piped from curl: fetch our own copy
  fi
  chmod +x "$self"
  cat > "$BIN_DIR/rodey-update"    <<EOF
#!/usr/bin/env bash
exec bash "$self" update "\$@"
EOF
  cat > "$BIN_DIR/rodey-uninstall" <<EOF
#!/usr/bin/env bash
exec bash "$self" uninstall "\$@"
EOF
  chmod +x "$BIN_DIR/rodey-update" "$BIN_DIR/rodey-uninstall"
}

# ── subcommands ───────────────────────────────────────────────────────────────
cmd_install() {
  banner
  detect_os
  ensure_python
  install_hidapi
  install_udev_rule
  install_rodey
  install_self
  verify
  configure_path
  printf "\n${G}${B}done.${X} rodey $(installed_version)\n"
  if [ "$ON_PATH_ALREADY" = 1 ]; then
    printf "try it now:\n    ${B}rodey channels${X}      ${DIM}# what's patched to each strip${X}\n\n"
  elif [ "$PATH_CONFIGURED" = 1 ]; then
    printf "added ${B}rodey${X} to your PATH. start a new terminal, or run:\n"
    printf "    ${B}export PATH=\"$BIN_DIR:\$PATH\"${X}\n"
    printf "then:\n    ${B}rodey channels${X}\n\n"
  else
    printf "run it via its full path (PATH not modified):\n    ${B}$BIN_DIR/rodey channels${X}\n\n"
  fi
  printf "${DIM}  update:     rodey-update       (or re-run this installer)${X}\n"
  printf "${DIM}  uninstall:  rodey-uninstall${X}\n"
  if [ "$HAS_MCP" = 1 ]; then
    printf "${DIM}  MCP:        add {\"command\":\"rodey-mcp\"} to your client config${X}\n"
  fi
  printf "${DIM}  unofficial; not affiliated with RØDE. firmware 1.7.x${X}\n\n"
}

cmd_update() {
  banner
  detect_os
  [ -d "$VENV" ] || die "rodey isn't installed here. Run the installer first."
  local before; before="$(installed_version)"
  ensure_python          # also upgrades to 3.10+ if the box has aged out
  step "updating rodey (was $before) …"
  "$VENV/bin/pip" install --quiet --upgrade "$TARBALL"
  if "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)'; then
    "$VENV/bin/pip" install --quiet --upgrade "mcp>=1.0,<2" 2>/dev/null \
      && "$VENV/bin/python" -c 'import mcp.server.fastmcp' 2>/dev/null && HAS_MCP=1 || true
  fi
  ln -sf "$VENV/bin/rodey" "$BIN_DIR/rodey"
  [ "$HAS_MCP" = 1 ] && [ -e "$VENV/bin/rodey-mcp" ] && ln -sf "$VENV/bin/rodey-mcp" "$BIN_DIR/rodey-mcp"
  install_self
  verify
  local after; after="$(installed_version)"
  if [ "$before" = "$after" ]; then
    printf "\n${G}${B}up to date.${X} rodey $after\n\n"
  else
    printf "\n${G}${B}updated.${X} rodey $before → $after\n\n"
  fi
}

cmd_uninstall() {
  banner
  detect_os
  step "removing commands from $BIN_DIR"
  rm -f "$BIN_DIR/rodey" "$BIN_DIR/rodey-mcp" "$BIN_DIR/rodey-update" "$BIN_DIR/rodey-uninstall"
  step "removing $APP_DIR"
  rm -rf "$APP_DIR"
  # strip the PATH line (and the blank line above it) from any rc file we touched
  local f removed=0
  for f in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"; do
    [ -f "$f" ] || continue
    if grep -Fq "added by rodey installer" "$f" 2>/dev/null; then
      # delete the marker line and an immediately-preceding blank line
      "${PYTHON:-python3}" - "$f" <<'PY' 2>/dev/null || sed -i.bak '/added by rodey installer/d' "$f"
import sys
p=sys.argv[1]; L=open(p).read().splitlines()
out=[]
for ln in L:
    if "added by rodey installer" in ln:
        if out and out[-1].strip()=="": out.pop()
        continue
    out.append(ln)
open(p,"w").write("\n".join(out)+"\n")
PY
      removed=1
    fi
  done
  [ "$removed" = 1 ] && ok "removed rodey's PATH entry (open a new terminal to refresh)"
  if [ "$OS" = linux ] && [ -f /etc/udev/rules.d/70-rodecaster.rules ]; then
    step "removing udev rule (sudo)…"
    sudo rm -f /etc/udev/rules.d/70-rodecaster.rules
    sudo udevadm control --reload-rules 2>/dev/null || true
  fi
  printf "\n${G}${B}uninstalled.${X} the hidapi library was left in place.\n\n"
}

SELF_URL="https://raw.githubusercontent.com/$REPO/$BRANCH/install.sh"

main() {
  case "${1:-install}" in
    install|"")          cmd_install ;;
    update|upgrade)      cmd_update ;;
    uninstall|remove)    cmd_uninstall ;;
    -h|--help|help)
      printf "usage: install.sh [install|update|uninstall]\n" ;;
    *) die "unknown command: $1  (use: install | update | uninstall)" ;;
  esac
}

main "$@"
