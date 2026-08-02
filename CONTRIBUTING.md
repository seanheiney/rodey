# Contributing to rodey

Thanks for helping map the RØDECaster Pro II. The most valuable contributions are
**more object IDs** and **confirmation on other firmware versions** — see below.

## Setup

```sh
git clone https://github.com/seanheiney/rodey && cd rodey
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest            # 56 tests, no hardware required
```

The test suite is deliberately hardware-free: it exercises the protocol
encode/decode and the addressing formulas, with values captured from real hardware
baked in as fixtures. If you change the wire format, the tests should fail loudly.

## Ground rules (these keep hardware safe)

Read [`docs/PROTOCOL.md`](docs/PROTOCOL.md) first. Two things are non-negotiable:

1. **Never send anything but `0x4E` to report 1.** `0x4D` and `0x55` are firmware
   update/flash and have blanked boards. `encode_mode()` enforces this — don't
   route around it.
2. **Never probe object IDs.** Writing an unknown property to a guessed ID
   permanently adds that property to the object. IDs come from *observed traffic*
   only. Use the capture tools; there is deliberately no scanner.

Also: don't verify writes by listening — a condenser's noise floor drifts several
dB. Verify with a state-dump diff (the library's `set_verified` does this).

## Contributing object IDs

The map in `src/rodey/data/objid_map.json` is sparse. To extend it safely:

- **From the vendor app:** build the interposer and capture what the app sends —
  see [`tools/README.md`](tools/README.md), then `tools/harvest_objids.py`.
- **From physical controls:** run `tools/capture_board.py` and operate the board;
  it logs the object IDs the device broadcasts.

Open a PR with the new entries and a note on how you captured them and which
firmware you're on. Please don't hand-guess IDs.

## Confirming the addressing formulas

`channel_object_id` and `mix_mute_object_id` were verified on one board (firmware
1.7.3). Confirmation — or corrections — on other firmware and on the RØDECaster
Duo would be very welcome. If a formula is off, add a failing test with your
observed values and we'll adjust.

## Style

Match the surrounding code. Keep the "why" comments — this codebase documents hard-
won findings (the mute-polarity inversion, the drain-immediately race, the two
value conventions) precisely so nobody re-derives them.
