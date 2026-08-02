# Resume / hacking guide

Everything you need to pick **rodey** back up and make changes safely. Start here.

## Where things are

| | |
|---|---|
| **GitHub** | https://github.com/seanheiney/rodey (public, MIT, CI green) |
| **Working copy** | `/Volumes/DataSSD1/rode` — full clone, tracks `origin/main` |
| **Dev venv (this machine)** | `~/.local/share/rode/venv` (has `hidapi` + `pytest`) |
| **Installed CLI venv** | `~/.local/share/rodey/venv` (what the installer creates) |
| **Device** | RØDECaster Pro II, USB VID `0x19F7` / PID `0x37`, firmware **1.7.3** |

## 30-second setup

```sh
cd /Volumes/DataSSD1/rode
git pull

# run the tests (hardware-free, 56 of them)
PYTHONPATH=src ~/.local/share/rode/venv/bin/python -m pytest tests/ -q

# talk to the board (needs it plugged in)
PYTHONPATH=src ~/.local/share/rode/venv/bin/python -m rodey.cli channels
```

If the venv is gone: `python3 -m venv ~/.local/share/rode/venv && ~/.local/share/rode/venv/bin/pip install -e '.[dev]'`
(needs `brew install hidapi` for the native lib).

## Map of the code

```
src/rodey/
  protocol.py    ← pure wire codec + addressing formulas + SAFETY guards. No I/O.
  device.py      ← Rodecaster class: connect/handshake/read_dump/set/set_verified/snapshot
  cli.py         ← the `rodey` command (get/set/list/channels/watch)
  mcp_server.py  ← the `rodey-mcp` MCP server (5 tools)
  data/objid_map.json  ← harvested object IDs (106 objects)
tools/
  hidlog.c            ← IOHIDDeviceSetReport interposer (build script in tools/README.md)
  harvest_objids.py   ← parse vendor-app writes into an objID map
  capture_board.py    ← listen while you operate physical controls
docs/PROTOCOL.md      ← the full reverse-engineered spec (read before touching the wire)
install.sh            ← installer / updater / uninstaller (one script, 3 subcommands)
```

## The rules that keep hardware safe (do not break these)

1. **Report 1 takes only `0x4E`.** `0x4D`='M' (firmware update mode) and `0x55`='U'
   (flash) have blanked boards. `encode_mode()` enforces it.
2. **Never probe object IDs.** Writing an unknown property to a guessed ID *permanently*
   adds it to the object. Harvest IDs from observed traffic; there is no scanner.
3. **Verify writes by state-dump diff, never by ear** (`set_verified` does this). A
   condenser's noise floor drifts several dB and will lie to you.
4. `encode_write` already refuses destructive props and read-only faders — don't route
   around it.

## Gotchas that cost hours (all fixed, but know them)

- **Drain immediately after the handshake.** Any pause (even 300 ms) drops the head of
  the state dump — you get a plausible ~28 KB tail and think the device is hiding state.
  `connect()` captures the dump inline for this reason.
- **Inverted mute polarity.** `channelOutputMute = False` means *muted*. Use
  `is_muted()`/`mute_value()`/`rc.muted()`/`rc.set_muted()`, not raw bools.
- **Two value conventions.** Faders/pots are `uint32` 0–127 (bounds in the dump);
  everything else is `float64` 0–1. `1` and `1.0` are not interchangeable.
- **git on `/Volumes`.** macOS TCC can intermittently block the sandboxed `git` binary
  on the external volume ("Operation not permitted" on `.git/config`) while `cp`/`ls`
  work. If it recurs: grant the terminal removable-volume access, or publish from an
  internal-disk copy. It has cleared on its own before.

## Common mods — recipes

### Add / extend object IDs
Never guess them. Capture, then merge:
```sh
# from the vendor app (see tools/README.md to build the interposer first)
DYLD_INSERT_LIBRARIES="$PWD/tools/hidlog.dylib" \
  ./tools/RODECaster-instrumented.app/Contents/MacOS/"RODECaster App"   # exercise controls, quit
python3 tools/harvest_objids.py /tmp/rode-hidlog.txt --json

# OR from physical controls
~/.local/share/rode/venv/bin/python tools/capture_board.py 120          # operate the board
```
Merge the result into `src/rodey/data/objid_map.json`. If it's a channel or mix-bus
object, confirm it fits the existing formula rather than hard-coding.

### Add a CLI subcommand
Add a `cmd_*` function + subparser in `src/rodey/cli.py`. Reads go through
`rc.get()`/`rc.snapshot()`; writes through `rc.set_verified()`.

### Add an MCP tool
Add an `@mcp.tool()` function in `src/rodey/mcp_server.py`. Keep every write verified and
never expose report-1 or an objID scanner.

### Change the wire format / decoder
Edit `src/rodey/protocol.py`. The tests in `tests/test_protocol.py` check encode/decode
against **real captured frames** — if you change framing, they should fail. Add captured
bytes as fixtures, don't invent them.

### Cut a release
1. Bump `version` in `pyproject.toml` and add a `CHANGELOG.md` section.
2. `python -m build && twine check dist/*`
3. Tag: `git tag vX.Y.Z && git push --tags`
4. PyPI (name `rodey` is free): `twine upload dist/*` — needs a PyPI token you create.

## What's left (ideas for next time)

**High value, low risk**
- Shows backup/restore (`showControlExport/Import`, `currentShowName/UUID`) — full config
  backup, would've made this whole project safer.
- Recording control (`recordState`, `requestRecordState`, `recordTimeMs`).

**Interesting**
- The 8-byte pad address form (pads/soundpads) — the last structural unknown.
- Float `0.0–1.0` → real units (dB/Hz/ms). Needs the app's displayed value next to a
  known stored value (screenshot cross-ref); no bounds are in the dump.

**Don't bother** — proven impossible
- Writing fader levels (physical, non-motorised faders; the device refuses it).
- Live metering without the vendor app (needs a meter subscription we haven't captured).
- SSH without flashing custom firmware (only vendor *public* keys ship).

## Related notes

`docs/PROTOCOL.md` is the authoritative spec. This machine also has session memory at
`~/.claude/.../memory/` covering the audio-routing findings, the HID protocol, and this
project's location.
