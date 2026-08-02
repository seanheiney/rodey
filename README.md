# rodey

*Like a roadie who runs the gear — but for your RØDECaster.*

[![CI](https://github.com/seanheiney/rodey/actions/workflows/ci.yml/badge.svg)](https://github.com/seanheiney/rodey/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) ![Python](https://img.shields.io/badge/python-3.9%2B-blue)

Unofficial Python library, CLI and **MCP server** for the **RØDECaster Pro II**.
Control the board from code — mutes, routing, per-channel processing, full state
reads — over its USB HID interface. RØDE publishes no host API; this protocol was
reverse-engineered by observing RØDE's own app and the device's own notifications,
then verified against hardware. See [docs/PROTOCOL.md](docs/PROTOCOL.md).

> **Picking this back up to make changes?** Start with [docs/RESUME.md](docs/RESUME.md) — setup, code map, safety rules, and mod recipes.

> ⚠️ **Unofficial and not affiliated with RØDE.** Developed against firmware **1.7.3**.
> A firmware update may change the protocol. Read the safety notes below before writing.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/seanheiney/rodey/main/install.sh | bash
```

macOS or Linux. One paste, no other setup. The installer handles every dependency:

- finds a suitable **Python** (3.9+); it does not install Python — if none is found it
  tells you and stops
- installs the **hidapi** native library via your package manager (Homebrew / apt / dnf /
  pacman) and the Python `hidapi` binding
- creates an **isolated venv** under `~/.local/share/rodey` (nothing touches system Python)
- adds `rodey` to your **PATH** and, on **Linux**, installs a **udev rule** for non-root
  HID access
- installs the **MCP server** too when Python is **3.10+** (the `mcp` package requires it);
  on 3.9 the CLI still installs and MCP is skipped

No `git` required — it installs from a source tarball. Re-runnable; upgrades in place.

```sh
rodey channels                 # what's patched to each strip
rodey get noiseGateOn          # a value across all channels
rodey set 0x1c noiseGateOn on  # write, then auto-verify
```

## What you can do

| Area | Status | Notes |
|------|--------|-------|
| **Read all device state** | ✅ | 139 KB snapshot, 49 groups, 533 properties, in ~1 s |
| **Channel mutes** | ✅ | per strip; inverted polarity handled for you |
| **Mix-bus routing matrix** | ✅ | mute any source on any of 13 buses — this is mix-minus scoping |
| **Per-channel processing** | ✅ | noise gate, HPF, compressor, de-esser, Aphex, EQ, pan |
| **Master channel** | ✅ | Compellor, delay |
| **Outputs / monitor / headphones** | ✅ | levels and mutes |
| **Enable MIDI control** | ✅ | flips the board's documented MIDI surface on over HID |
| **Verified writes** | ✅ | every write is confirmed by a state-dump diff |
| **MCP server** | ✅ | drive the board from an AI agent |

### What we figured out (the protocol)

All of this is documented in [docs/PROTOCOL.md](docs/PROTOCOL.md) and encoded in the library:

- **Handshake** — `'N'` on report 1 + a session-open on report 3. Nothing works without
  it; it also triggers the full state dump.
- **Frame format** — a length-prefixed, name-addressed record with five value types
  (bool, uint32, float64, string), shared by reads and writes.
- **Reads** — the dump must be drained *immediately* after subscribing; any pause drops
  the head of the tree (this cost hours and produced several wrong theories).
- **Channel addressing** — `objID = 0x1C + strip`. One object is a whole channel's
  processing block. Verified on 7 of 10 strips, then predicted and confirmed.
- **Mix-bus matrix** — `objID = 0x4C + 13·source + bus`, keyed by input source, not
  strip position. 106 objects mapped.
- **Two value conventions** — faders/pots are `uint32` 0–127 (and publish their own
  bounds); everything else is `float64` 0–1.
- **Inverted mute polarity** — `channelOutputMute = False` means *muted*. The library
  wraps this so you never have to remember it.

### What is **not** possible

Documented so nobody re-derives them the hard way:

- **Writing fader levels.** The faders are physical and **not motorised** — a written
  value would disagree with the slider position, so the device refuses it. RØDE's own app
  can't do it either, and MIDI CC doesn't reach them. Faders are **read-only**; drive gain
  through channel processing instead.
- **Live metering over our subscription.** Real-time meters only stream when RØDE's app
  drives the board; our session-open yields the state dump but not the meter feed. Meter
  *values* are still readable from the dump.
- **Float parameters in real units.** `noiseGateThreshold = 0.5` writes and reads back
  reliably, but the 0–1 → dB/Hz/ms mapping is unknown — these properties publish no
  bounds. Values are settable; their engineering meaning is not yet decoded.
- **SSH without flashing firmware.** The board runs Linux with SSH enabled, but only the
  vendor's *public* keys ship in the firmware. Getting a shell requires building and
  flashing custom firmware (high brick risk); not something this tool does.

## Safety

The library refuses dangerous writes rather than trusting the caller:

- **Firmware mode bytes.** Report 1 accepts only `0x4E` (`'N'`). `0x4D` (`'M'`) enters
  firmware update mode and `0x55` (`'U'`) triggers a flash — both have blanked a board.
  Anything but `0x4E` is refused. (A popular third-party project probes `0x55` as a
  "ping" — it is not.)
- **Destructive properties** — device reset, SD erase, firmware flash, show delete — are
  refused by `encode_write`.
- **Never sweep object IDs.** Writing an unknown property to a guessed ID permanently adds
  that property to the object. IDs are harvested from observed traffic, never probed;
  there is deliberately no scanner.
- **Don't verify writes by ear.** A condenser's noise floor drifts several dB; verify with
  the state dump instead (the library does this for you).

## Library

```python
from rodey import Rodecaster

with Rodecaster() as rc:
    print(rc.strip_sources())          # [0, 1, 10, 7, 8, ...] channelInputSource codes
    print(rc.muted())                  # [False, True, ...] per strip, polarity handled

    rc.set_muted(3, True)              # mute strip 3
    rc.set_channel(0, "noiseGateOn", True)     # objID resolved from strip index

    if rc.set_verified(0x1C, "hpfOn", True):   # write, confirmed by dump diff
        print("high-pass on")

    snap = rc.snapshot()               # {GROUP: {property: [per-strip values]}}
```

## MCP server

```sh
rodey-mcp
```

```json
{ "mcpServers": { "rodey": { "command": "rodey-mcp" } } }
```

Tools: `get_property`, `set_property` (verified), `list_properties`, `list_known_objects`,
`watch_changes`. No tool can reach the firmware-mode channel; there is no objID scanner.

## Extending the object map

`docs/PROTOCOL.md` explains the capture procedure. `tools/harvest_objids.py` parses
writes made by RØDE's app; `tools/capture_board.py` listens while you operate physical
controls. Both are pure observation — contributions of harvested IDs are welcome.

## Development

```sh
git clone https://github.com/seanheiney/rodey && cd rodey
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest            # 56 tests, no hardware required
```

## License

MIT
