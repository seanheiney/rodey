"""MCP server exposing the RØDECaster Pro II to AI agents.

    rodey-mcp                 # stdio transport

Design notes for anyone extending this:

* Every write is verified by state-dump diff and reports whether it actually
  landed. The device does not echo writes to the writing handle, so an
  unverified "success" would be meaningless.
* Reads capture the whole state tree on connect (~1s), so tools return whole-device
  snapshots rather than single values.
* No tool can reach report 1. Its mode bytes include firmware-update and flash
  commands, which are not something an agent should be able to trigger.
* Object IDs are not discoverable by sweeping - doing so permanently mutates the
  device's object tree. There is deliberately no "scan objIDs" tool.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .device import DUMP_SECONDS, DeviceNotFound, Rodecaster
from .protocol import UnsafeCommand

mcp = FastMCP("rodey")

def _load_objid_map() -> dict[str, list[str]]:
    """Object IDs harvested from observed app writes.

    Ships as data rather than code so contributors can extend it from a capture
    without touching source. Never populate this by probing candidate IDs - doing
    so permanently adds properties to objects that never had them.
    """
    path = Path(__file__).parent / "data" / "objid_map.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):  # map is optional; the tools work without it
        return {}


KNOWN_OBJECTS: dict[str, list[str]] = _load_objid_map()


def _err(exc: Exception) -> str:
    if isinstance(exc, DeviceNotFound):
        return ("RØDECaster Pro II not found. Check it is connected by USB, and that "
                "no other process using hidapi has seized the HID interface.")
    if isinstance(exc, UnsafeCommand):
        return f"Refused as unsafe: {exc}"
    return f"{type(exc).__name__}: {exc}"


@mcp.tool()
def get_property(name: str) -> str:
    """Read a property's value on every channel that has it.

    Returns values in state-dump order, so index 0 is the first channel. Note the
    dump carries no object IDs, so this tells you values but not the objID needed
    to write back - use list_known_objects for that.

    Takes ~1s: the device serialises its whole state tree on connect.

    Examples: noiseGateOn, compressorOn, faderLevel, channelOutputMute.
    """
    try:
        with Rodecaster() as rc:
            values = rc.get(name)
        if not values:
            return (f"'{name}' not present in the state dump. Check spelling "
                    f"(properties are camelCase), or run list_properties.")
        return json.dumps({"property": name, "values": values, "channels": len(values)})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def set_property(obj_id: str, name: str, value: str) -> str:
    """Write a property and verify it actually changed.

    obj_id: object to address, e.g. "0x1c" (see list_known_objects).
    value:  "on"/"off" for booleans, or a float 0..1 for continuous parameters.

    Verification diffs the full state dump before and after (~3s).
    The result says explicitly whether the write landed.

    Only use object IDs that are known or harvested from observed app traffic.
    Guessing them permanently adds properties to objects that never had them.
    """
    try:
        obj = int(obj_id, 0)
        low = value.strip().lower()
        if low in ("on", "true", "1", "yes"):
            typed: Any = True
        elif low in ("off", "false", "0", "no"):
            typed = False
        else:
            typed = float(low)
            if not 0.0 <= typed <= 1.0:
                return f"Continuous values are normalised 0..1; got {typed}."
        with Rodecaster() as rc:
            before = rc.get(name)
            rc.set(obj, name, typed)
            after = rc.get(name)
        changed = before != after
        return json.dumps({
            "property": name, "obj_id": f"0x{obj:02x}", "requested": typed,
            "before": before, "after": after, "changed": changed,
            "note": "write confirmed" if changed else
                    "no change - wrong objID, or this object lacks that property",
        })
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def list_properties(filter: str = "") -> str:
    """List every property the device exposes, optionally filtered by substring.

    Reads the full state dump (~1s) and reports the property vocabulary -
    roughly 533 names across 49 groups. Useful for discovering exact spellings.
    """
    try:
        import re
        with Rodecaster() as rc:
            blob = rc.state
        names = sorted({m.group().decode() for m in re.finditer(rb"[A-Za-z][A-Za-z0-9_]{3,}", blob)})
        props = [n for n in names if not n.isupper()]
        groups = [n for n in names if n.isupper()]
        if filter:
            props = [n for n in props if filter.lower() in n.lower()]
        return json.dumps({"groups": groups, "properties": props, "count": len(props)})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def list_known_objects() -> str:
    """Object IDs known to be writable, with the properties each carries.

    Deliberately sparse. Object IDs appear only in writes, never in the state
    dump, so they must be harvested by observing the vendor app. There is no
    scan tool: sweeping candidate IDs permanently mutates the device.
    """
    return json.dumps({
        "objects": KNOWN_OBJECTS,
        "count": len(KNOWN_OBJECTS),
        "note": "sparse - one objID is a whole channel processing block, so each "
                "covers many properties. Harvested from observed app writes.",
        "how_to_extend": "capture app traffic, then run tools/harvest_objids.py",
    })


@mcp.tool()
def watch_changes(seconds: float = 10.0) -> str:
    """Watch live control changes made on the board or by the vendor app.

    Changes made through this server are NOT reported here - the device only
    echoes to other clients. Use this to discover object IDs by touching physical
    controls, which is the safe alternative to probing.
    """
    try:
        with Rodecaster() as rc:
            seen = [str(p) for p in rc.watch(min(seconds, 60.0))
                    if "mixLevel" not in p.name and "meterLevel" not in p.name]
        return json.dumps({"changes": seen[:200], "count": len(seen)})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
