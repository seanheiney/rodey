# rodey

*Like a roadie who runs the gear — but for your RØDECaster.*

Unofficial Python library, CLI and **MCP server** for the RØDECaster Pro II.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/seanheiney/rodey/main/install.sh | bash
```

macOS or Linux. Installs into an isolated environment, pulls in `hidapi`, and (on
Linux) adds a udev rule for non-root access. Then:

```sh
rodey channels          # what's patched to each strip
```

RØDE ships no host API — the board is configured on its touchscreen or through their
GUI app. This talks to it directly over its vendor USB HID interface, using a protocol
reverse-engineered by **observing RØDE's own app**, not by guessing.

> **Alpha, unofficial, and not affiliated with RØDE.** Developed against firmware
> **1.7.3**. Read [docs/PROTOCOL.md](docs/PROTOCOL.md) — especially the safety section —
> before writing anything to your board.

## Why

The board exposes a rich control surface — per-channel noise gate, compressor,
de-esser, HPF, Aphex processing, faders, mutes, routing — that is otherwise only
reachable by tapping a touchscreen. This makes it scriptable, and lets an AI agent
drive it through MCP.

## Install from PyPI / source

```bash
pip install rodey          # library + CLI
pip install 'rodey[mcp]'   # plus the MCP server
```

Requires `hidapi` (`brew install hidapi` on macOS, `libhidapi-dev` on Debian/Ubuntu).
On Linux you will also need a udev rule for non-root access.

## CLI

```bash
rodey channels                       # what is patched to each strip
rodey get noiseGateOn                # value per channel
rodey list -f gate                   # discover property names
rodey set 0x1c noiseGateOn on        # write, then verify
rodey watch                          # live changes from the board
```

Reads take about 11 seconds. That isn't a bug: the handshake makes the device
serialise its entire state tree (~138 KB), and that dump *is* the read channel.

## Library

```python
from rodey import Rodecaster

with Rodecaster() as rc:
    print(rc.get("channelInputSource"))          # [0, 1, 10, 7, 8, ...]
    print(rc.get("noiseGateOn"))                 # [False, False, ...]

    if rc.set_verified(0x1C, "noiseGateOn", True):
        print("gate on")
```

`set_verified` diffs the state dump before and after. Prefer it over `set`: the device
**does not echo writes back to the handle that made them**, so nothing else confirms a
write actually landed.

## MCP server

```bash
rodey-mcp
```

```json
{
  "mcpServers": {
    "rodey": { "command": "rodey-mcp" }
  }
}
```

Tools: `get_property`, `set_property`, `list_properties`, `list_known_objects`,
`watch_changes`. Every write is verified and reports whether it landed. No tool can
reach the mode-command channel, and there is deliberately no objID scanner.

## Safety

Two things will damage or disrupt a board. Both are enforced in code, not left to
documentation:

**Report 1 carries firmware commands.** `0x4D` (`'M'`) enters firmware update mode and
`0x55` (`'U'`) triggers a flash. This library refuses every byte there except `0x4E`.
Note that a widely-linked open-source project probes `0x55` as a "ping" — it is not a
ping.

**Never sweep object IDs.** Writing `noiseGateOn` across `0x1c`–`0x33` permanently added
that property to objects that never had it (24 occurrences afterwards, versus 10 for an
untouched control). Object IDs must be harvested from observed writes — see
`tools/harvest_objids.py`.

Also: **don't verify writes by measuring audio.** A condenser's noise floor drifts
several dB on its own, which produced two opposite wrong conclusions during
development. Diff the state dump instead.

## Status

| | |
|---|---|
| Handshake | ✅ solved |
| Read (state dump, 534 properties / 49 groups) | ✅ solved |
| Writes | ✅ verified by dump diff |
| Object-ID map | ✅ channels + mix-bus matrix solved; 104 objects mapped |
| Parameter semantics (0..1 → dB) | 🚧 unknown |
| Fader writes | ⛔ not possible — faders are physical and not motorised |

Two addressing formulas cover most of the device:

```python
channel_object_id(strip)            # 0x1C + strip        - all channel processing
mix_mute_object_id(source, bus)     # 0x4C + 13*source+bus - the routing matrix
```

Contributions of harvested object IDs are welcome — see
[docs/PROTOCOL.md](docs/PROTOCOL.md) and `tools/`.

## License

MIT
