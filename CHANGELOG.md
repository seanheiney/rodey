# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Library, CLI (`rodey`) and MCP server (`rodey-mcp`) for the RØDECaster Pro II.
- One-line installer with `install` / `update` / `uninstall`; installs Python 3.10+
  and hidapi when missing, configures PATH, and (on Linux) adds a udev rule.
- Reverse-engineered protocol, documented in `docs/PROTOCOL.md`:
  - handshake, length-prefixed frame format, five value types;
  - channel addressing `objID = 0x1C + strip`;
  - mix-bus routing matrix `objID = 0x4C + 13·source + bus`;
  - `parse_dump()` structured snapshot of the full device state.
- Object-ID map of 106 objects / 51 properties (`src/rodey/data/objid_map.json`).
- Safety enforcement in `encode_write`: firmware-mode bytes, destructive
  properties, and read-only faders are refused; inverted mute polarity is wrapped
  in `is_muted()` / `mute_value()` helpers.
- Capture tooling (`tools/harvest_objids.py`, `tools/capture_board.py`) and the
  `IOHIDDeviceSetReport` interposer used to derive the protocol.
- 56 hardware-free tests.

### Known limits
- Fader **writes** are impossible (physical, non-motorised faders); reads work.
- Live metering only streams under the vendor app; meter values are still in the dump.
- Float parameters (`0.0–1.0`) are settable but not yet mapped to real units (dB/Hz/ms).

[Unreleased]: https://github.com/seanheiney/rodey/commits/main
