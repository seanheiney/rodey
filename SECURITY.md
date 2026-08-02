# Security

## Reporting

Found a security issue in **rodey** (this tool)? Please open a
[private security advisory](https://github.com/seanheiney/rodey/security/advisories/new)
rather than a public issue.

## Scope

rodey talks to a RØDECaster Pro II over its local USB HID interface. It has no
network surface of its own. The interesting risks are physical/local and are
enforced in code — see the safety notes in the README and `docs/PROTOCOL.md`:

- **Firmware-mode bytes are refused.** Report 1 accepts only `0x4E`; the update
  (`0x4D`) and flash (`0x55`) bytes are never sent.
- **Destructive and read-only properties are refused** by `encode_write`.
- **Object IDs are never probed** — writing to a guessed ID mutates the device.

## Notes about the device itself (not rodey)

These are properties of the RØDECaster Pro II, documented here so users can make
informed choices. They are **not** vulnerabilities in this project and rodey does
not exploit them:

- The board runs Linux with **SSH enabled by default**; only the vendor's *public*
  keys ship in firmware. This has been publicly reported to RØDE by others.
- The state dump readable over USB HID contains configuration in the clear,
  including **`wifiPSK` and `sipAccountPassword`** when those are set. Any local
  process that can open the HID interface can read them. rodey reads device state
  but never transmits it anywhere.

If you configure WiFi or SIP on the board, treat the USB connection as trusted and
don't leave the device on an untrusted network.
