"""Command-line interface for the RØDECaster Pro II."""
from __future__ import annotations

import argparse
import json
import re
import sys

from .device import DUMP_SECONDS, DeviceNotFound, Rodecaster
from .protocol import UnsafeCommand

# channelInputSource values, confirmed against the vendor app's strip layout.
# Empty strips read 0xFFFFFFFF (the field is a uint32, not a byte).
INPUT_SOURCES = {0: "Mic 1", 1: "Mic 2", 7: "USB 1", 8: "Chat",
                 9: "USB 2", 10: "Bluetooth", 11: "SMART Pads",
                 0xFFFFFFFF: "(empty)"}


def _parse_value(raw: str):
    low = raw.strip().lower()
    if low in ("on", "true", "1", "yes"):
        return True
    if low in ("off", "false", "0", "no"):
        return False
    value = float(low)
    if not 0.0 <= value <= 1.0:
        raise ValueError("continuous values are normalised 0..1")
    return value


def cmd_get(args) -> int:
    with Rodecaster() as rc:
        values = rc.get(args.property)
    if not values:
        print(f"'{args.property}' not found in the state dump "
              f"(properties are camelCase; try `rodey list`)", file=sys.stderr)
        return 1
    for i, v in enumerate(values):
        print(f"  [{i}] {v}")
    return 0


def cmd_set(args) -> int:
    value = _parse_value(args.value)
    obj = int(args.obj_id, 0)
    with Rodecaster() as rc:
        before = rc.get(args.property)
        rc.set(obj, args.property, value)
        after = rc.get(args.property)
    changed = before != after
    print(f"{args.property}[0x{obj:02x}] -> {value}")
    print(f"  before: {before}")
    print(f"  after : {after}")
    # The device never echoes writes to the writing handle, so diffing the dump
    # is the only trustworthy confirmation.
    print("  " + ("confirmed" if changed else
                  "NO CHANGE - wrong objID, or this object has no such property"))
    return 0 if changed else 1


def cmd_list(args) -> int:
    with Rodecaster() as rc:
        blob = rc.state
    names = sorted({m.group().decode() for m in re.finditer(rb"[A-Za-z][A-Za-z0-9_]{3,}", blob)})
    props = [n for n in names if not n.isupper()]
    if args.filter:
        props = [n for n in props if args.filter.lower() in n.lower()]
    if args.json:
        print(json.dumps({"groups": [n for n in names if n.isupper()], "properties": props}, indent=2))
    else:
        print(f"{len(props)} properties")
        for n in props:
            print(f"  {n}")
    return 0


def cmd_channels(args) -> int:
    with Rodecaster() as rc:
        sources = rc.get("channelInputSource")
    print("strip  source")
    for i, s in enumerate(sources):
        code = int(s) if isinstance(s, (int, float)) else -1
        print(f"  [{i}]  {INPUT_SOURCES.get(code, f'unknown ({code})')}")
    return 0


def cmd_watch(args) -> int:
    print(f"watching {args.seconds}s - changes made HERE are not echoed back, "
          f"only board/app changes appear", file=sys.stderr)
    with Rodecaster() as rc:
        for prop in rc.watch(args.seconds):
            if "mixLevel" in prop.name or "meterLevel" in prop.name:
                continue  # continuous meter stream
            print(f"  {prop}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rodey",
        description="Unofficial control for the RØDECaster Pro II. "
                    "Reads take ~1s (the device serialises its whole state tree).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="read a property across all channels")
    g.add_argument("property")
    g.set_defaults(func=cmd_get)

    s = sub.add_parser("set", help="write a property and verify it changed")
    s.add_argument("obj_id", help="object id, e.g. 0x1c")
    s.add_argument("property")
    s.add_argument("value", help="on|off or a float 0..1")
    s.set_defaults(func=cmd_set)

    l = sub.add_parser("list", help="list available properties")
    l.add_argument("-f", "--filter", default="")
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=cmd_list)

    c = sub.add_parser("channels", help="show what is patched to each strip")
    c.set_defaults(func=cmd_channels)

    w = sub.add_parser("watch", help="watch live changes from the board")
    w.set_defaults(func=cmd_watch)

    for p in (g, s, l, c, w):
        p.add_argument("--seconds", type=float, default=DUMP_SECONDS,
                       help="dump/watch duration (default %(default)s)")

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except DeviceNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except UnsafeCommand as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3
    except (ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
