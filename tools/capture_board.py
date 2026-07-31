#!/usr/bin/env python3
"""
Harvest object IDs by listening while you operate the board's physical controls.

Complements ``harvest_objids.py``. That one parses writes made by RØDE's app; this
one listens to the notifications the board emits when you touch it directly. Use
this for anything the app does not expose - notably mutes and faders.

Both are observation, never probing: object IDs are read from traffic the device
itself produces.

    ./capture_board.py [seconds]

The vendor app must be quit first - hidapi seizes the HID interface, so only one
of them can hold it.
"""
import re
import sys
import time
from collections import OrderedDict

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from rodey import Rodecaster                      # noqa: E402
from rodey import protocol as p                   # noqa: E402

# streams constantly; would drown out real control changes
NOISE = re.compile(r"mixLevel|meterLevel|meterPeak")

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0


def main() -> int:
    seen: "OrderedDict[tuple[int, str], list]" = OrderedDict()
    print(f"listening {SECONDS:.0f}s — operate the board now\n")

    with Rodecaster().connect(capture=False) as rc:
        end = time.time() + SECONDS
        last_report = 0.0
        while time.time() < end:
            for prop in rc.watch(seconds=1.0):
                if NOISE.search(prop.name):
                    continue
                key = (prop.obj_id, prop.name)
                if key not in seen:
                    seen[key] = []
                    print(f"  + 0x{prop.obj_id:02x}  {prop.name} = {prop.value!r}")
                seen[key].append(prop.value)
            now = time.time()
            if now - last_report > 15:
                last_report = now
                print(f"    ... {len(seen)} distinct so far, "
                      f"{end - now:.0f}s left", flush=True)

    print(f"\n=== {len(seen)} distinct (objID, property) pairs ===")
    by_obj: dict[int, list[str]] = {}
    for (obj, name), values in seen.items():
        by_obj.setdefault(obj, []).append(name)
        uniq = sorted({repr(v) for v in values})[:4]
        print(f"  0x{obj:02x}  {name:<28} {', '.join(uniq)}")

    print("\n=== objID summary ===")
    for obj in sorted(by_obj):
        strip = obj - p.CHANNEL_OBJ_BASE
        where = (f"channel strip {strip}"
                 if 0 <= strip < p.CHANNEL_COUNT else "non-channel object")
        print(f"  0x{obj:02x}  {where:<22} {', '.join(sorted(by_obj[obj]))}")

    import json
    out = {f"0x{o:02x}": sorted(set(n)) for o, n in by_obj.items()}
    json.dump(out, open("board_objid_map.json", "w"), indent=2)
    print(f"\nwrote board_objid_map.json ({len(out)} objects)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
