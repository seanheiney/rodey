"""Wire protocol for the RØDECaster Pro II vendor HID interface.

Pure encoding/decoding - no I/O, so it is testable without hardware.
See docs/PROTOCOL.md for how this was derived and what is still unknown.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Any, Iterator

VENDOR_ID = 0x19F7
PRODUCT_ID = 0x37
USAGE_PAGE = 0xFF00

# Report IDs (from the HID report descriptor)
REPORT_MODE_OUT = 1      # host -> device, 63 B, single-ASCII mode commands
REPORT_MODE_IN = 2       # device -> host, 63 B
REPORT_PROP_OUT = 3      # host -> device, 255 B, property writes
REPORT_PROP_IN = 4       # device -> host, 255 B, notifications + state dump

REPORT_MODE_SIZE = 24    # the app uses a 24-byte buffer, not the full 63
REPORT_PROP_SIZE = 256

#: The ONLY byte that may be sent to :data:`REPORT_MODE_OUT`.
#:
#: 0x4D ('M') enters firmware update mode and 0x55 ('U') triggers a flash - both
#: have blanked a board during this work. Anything but 0x4E must be refused.
MODE_NORMAL = 0x4E
_FORBIDDEN_MODES = {0x4D: "enters firmware update mode", 0x55: "triggers a firmware flash"}

SESSION_OPEN = bytes([0xAD, 0x10, 0xA7, 0xB0])
ADDR_PREFIX = bytes([0x01, 0x01, 0x01, 0x01])

#: Channel objects are contiguous from this base: ``objID = 0x1C + strip``.
#:
#: Established by toggling ``channelBypassProcessing`` - a property the harvested
#: objects were already known to carry, so no new properties could be created -
#: and observing which strip moved in the state dump. Confirmed on strips
#: 0, 1, 2, 3, 4, 6 and 9.
CHANNEL_OBJ_BASE = 0x1C
CHANNEL_COUNT = 10


#: ⚠️ INVERTED POLARITY. Despite the name, these properties are "output enabled":
#:
#:     channelOutputMute = False  ->  channel IS muted
#:     channelOutputMute = True   ->  channel passes audio
#:
#: Established by muting Bluetooth on the board and watching that strip go
#: True -> False. `mixMute` follows the same convention (mixMute[bus 0] tracks
#: channelOutputMute exactly).
#:
#: This is a trap worth guarding: writing True to "mute" a channel UNMUTES it, and
#: nothing in the property name hints at it. Use is_muted()/mute_value() rather
#: than passing raw booleans around.
INVERTED_MUTE_PROPERTIES = frozenset({"channelOutputMute", "mixMute"})


def is_muted(raw_value: bool) -> bool:
    """Interpret a raw mute-property value. See INVERTED_MUTE_PROPERTIES."""
    return raw_value is False


def mute_value(muted: bool) -> bool:
    """Raw value to write for a desired mute state. See INVERTED_MUTE_PROPERTIES."""
    return not muted


#: Mix-bus mute objects are blocked per *input source*, 13 buses each:
#: ``0x4C + 13 * source + bus``.
#:
#: Confirmed for sources 0, 1, 7, 8, 9, 10 and 11 by muting each channel on the
#: board and observing which block emitted. Note the index is the
#: ``channelInputSource`` value, NOT the strip position - strips are
#: user-assignable, these blocks are not.
MIXMUTE_BASE = 0x4C
MIXMUTE_BUSES = 13


def mix_mute_object_id(source: int, bus: int) -> int:
    """Object ID for one channel's mute on one mix bus.

    ``source`` is a ``channelInputSource`` code (0 = Mic 1, 8 = Chat, ...), read
    from a state dump - not the strip index.

    This is the routing matrix: muting a source on a given bus removes it from
    that send. Muting the Chat send for a source is how mix-minus is scoped.
    """
    if source < 0:
        raise ValueError(f"source must be >= 0, got {source}")
    if not 0 <= bus < MIXMUTE_BUSES:
        raise ValueError(f"bus must be 0..{MIXMUTE_BUSES - 1}, got {bus}")
    return MIXMUTE_BASE + MIXMUTE_BUSES * source + bus


def mix_mute_block(source: int) -> range:
    """All 13 mix-bus mute object IDs for an input source."""
    start = mix_mute_object_id(source, 0)
    return range(start, start + MIXMUTE_BUSES)


def channel_object_id(strip: int) -> int:
    """Object ID for a channel strip (0-9).

    One object carries that channel's whole processing block - gate, HPF,
    compressor, de-esser, Aphex, bypass - so this is the address for nearly
    everything channel-scoped.

    Use ``channelInputSource`` from a state dump to map a strip index to what is
    actually patched to it (Mic 1, Chat, USB 1, ...); strip order is fixed but
    the assignment is user-configurable.
    """
    if not 0 <= strip < CHANNEL_COUNT:
        raise ValueError(f"strip must be 0..{CHANNEL_COUNT - 1}, got {strip}")
    return CHANNEL_OBJ_BASE + strip

# payload type tags
T_UINT32, T_FALSE, T_TRUE, T_FLOAT64, T_STRING = 0x01, 0x02, 0x03, 0x04, 0x05


class UnsafeCommand(RuntimeError):
    """Raised when a caller tries to send a destructive mode byte."""


@dataclass(frozen=True)
class Property:
    """One decoded property record."""
    obj_id: int
    name: str
    value: Any

    def __str__(self) -> str:
        return f"0x{self.obj_id:02x}.{self.name} = {self.value!r}"


def encode_mode(byte: int = MODE_NORMAL) -> bytes:
    """Buffer for report 1. Refuses every byte except :data:`MODE_NORMAL`."""
    if byte != MODE_NORMAL:
        why = _FORBIDDEN_MODES.get(byte, "is not a known-safe mode byte")
        raise UnsafeCommand(f"refusing to send 0x{byte:02x} to report 1: it {why}")
    return bytes([REPORT_MODE_OUT, byte]).ljust(REPORT_MODE_SIZE, b"\x00")


def _wrap(body: bytes) -> bytes:
    return bytes([REPORT_PROP_OUT]) + struct.pack("<I", len(body)) + body


def encode_session_open() -> bytes:
    """Second half of the handshake; also triggers the full state dump."""
    return _wrap(SESSION_OPEN).ljust(REPORT_PROP_SIZE, b"\x00")


#: Properties that reset, reformat, or re-flash the device. Writing any of these
#: could destroy recordings, wipe configuration, or start a firmware update - the
#: same class of harm as the 'M'/'U' mode bytes on report 1, just reachable through
#: the ordinary property channel. encode_write() refuses them; callers who really
#: mean it must go around this module deliberately.
DESTRUCTIVE_PROPERTIES = frozenset({
    "updateInitiateRequested", "updateRebootRequested", "updateResetAppRequested",
    "updateResetDeviceRequested", "updateResetAfterFWURequested",
    "storageVolumeErase", "storageVolumeEject", "storageVolumeFormatted",
    "showControlDelete", "padRecordClear",
})

#: Read-only by hardware design, not by omission. The faders are physical and not
#: motorised, so a remotely-set value would disagree with where the slider actually
#: sits - the device refuses it. RØDE's own app exposes no fader control either, and
#: MIDI CC does not reach them. Read these for metering/state; do not try to write.
#: (Encoders such as ``outputMonLevel`` have no absolute position and DO write.)
READ_ONLY_PROPERTIES = frozenset({"faderLevel", "faderMin", "faderMax"})

#: Properties carried as uint32 0..127 rather than float64 0..1. Passing a float
#: for these produces a well-formed frame that the device ignores, so the
#: distinction matters. Faders and pots publish their own bounds in the state
#: dump (``faderMin``/``faderMax``, ``potMin``/``potMax``).
INT_RANGED_PROPERTIES = frozenset({
    "faderLevel", "faderMin", "faderMax",
    "potLevel", "potMin", "potMax",
})
INT_RANGE_MAX = 127


def encode_value(value: Any) -> bytes:
    """Encode a payload as ``01 <len> <payload>``.

    ``bool`` -> bool tag, ``int`` -> uint32, ``float`` -> float64. The int/float
    split is significant: faders and pots are uint32 0..127 while processing
    parameters are float64 0..1, so ``1`` and ``1.0`` are not interchangeable.
    """
    if isinstance(value, bool):                      # before int - bool subclasses it
        payload = bytes([T_TRUE if value else T_FALSE])
    elif isinstance(value, int):
        payload = bytes([T_UINT32]) + struct.pack("<I", value)
    elif isinstance(value, float):
        payload = bytes([T_FLOAT64]) + struct.pack("<d", value)
    elif isinstance(value, str):
        payload = bytes([T_STRING]) + value.encode("ascii") + b"\x00"
    else:
        raise TypeError(f"cannot encode {type(value).__name__}")
    return bytes([0x01, len(payload)]) + payload


def encode_write(obj_id: int, name: str, value: Any) -> bytes:
    """A property-write buffer for report 3."""
    if not 0 <= obj_id <= 0xFF:
        raise ValueError(f"obj_id out of range: {obj_id}")
    if name in DESTRUCTIVE_PROPERTIES:
        raise UnsafeCommand(
            f"refusing to write {name!r}: it resets, reformats or re-flashes the "
            f"device. See DESTRUCTIVE_PROPERTIES."
        )
    if name in READ_ONLY_PROPERTIES:
        raise UnsafeCommand(
            f"{name!r} is read-only: the faders are physical and not motorised, so a "
            f"written value would disagree with the slider position."
        )
    body = ADDR_PREFIX + bytes([obj_id]) + name.encode("ascii") + b"\x00" + encode_value(value)
    return _wrap(body).ljust(REPORT_PROP_SIZE, b"\x00")


def decode_value(tail: bytes) -> Any:
    """Decode ``01 <len> <payload>``; ``None`` if unrecognised or truncated.

    Length is validated against the declared ``len`` field: a fixed-width type
    whose payload is short is rejected rather than read past its end, which would
    otherwise surface as garbage (e.g. a float64 read across a record boundary
    coming back as 1e+60).
    """
    if len(tail) < 3 or tail[0] != 0x01:
        return None
    payload = tail[2:]
    kind = payload[0]
    if kind in (T_FALSE, T_TRUE):
        return kind == T_TRUE
    # Fixed-width numerics: require the full width to be present, else the read
    # would run past the record and return garbage (a float64 crossing a record
    # boundary decodes as ~1e60). Strings are null-terminated, so self-delimiting.
    if kind == T_UINT32:
        return struct.unpack("<I", payload[1:5])[0] if len(payload) >= 5 else None
    if kind == T_FLOAT64:
        return struct.unpack("<d", payload[1:9])[0] if len(payload) >= 9 else None
    if kind == T_STRING:
        return payload[1:].split(b"\x00")[0].decode("ascii", "replace")
    return None


def decode_notification(raw: bytes) -> Property | None:
    """Decode one report-4 frame (report ID already stripped)."""
    if len(raw) < 10:
        return None
    length = struct.unpack_from("<I", raw, 0)[0]
    body = raw[4:4 + length] if length <= len(raw) - 4 else raw[4:]
    if len(body) < 6 or not body.startswith(ADDR_PREFIX):
        return None
    end = body.find(b"\x00", 5)
    if end < 0:
        return None
    try:
        name = body[5:end].decode("ascii")
    except UnicodeDecodeError:
        return None
    if not name or not name[0].islower():
        return None
    return Property(body[4], name, decode_value(body[end + 1:]))


_TOKEN = re.compile(rb"[A-Za-z][A-Za-z0-9_]{3,}")


def iter_dump_properties(blob: bytes) -> Iterator[tuple[str, Any]]:
    """Walk a state dump, yielding ``(name, value)`` in serialisation order.

    The dump is a nested tree - ``00 GROUPNAME 00 01 02`` followed by
    ``propName 00 01 <len> <payload>`` records - and carries **no object IDs**.
    Hierarchy is implied by nesting and order, so positional index is the only
    way to tell channels apart here. Object IDs come from writes instead.
    """
    for m in _TOKEN.finditer(blob):
        name = m.group().decode()
        if name.isupper():
            continue
        end = m.end()
        if end < len(blob) and blob[end] == 0x00:
            yield name, decode_value(blob[end + 1:end + 16])


def parse_dump(blob: bytes) -> dict[str, dict[str, list[Any]]]:
    """Parse a state dump into ``{GROUP: {property: [values...]}}``.

    The dump is a flat record stream - ``name 00 01 <len> <payload>`` - where
    UPPERCASE names open a group and camelCase names are properties within the
    current group. Repeated groups (10x CHANNEL, etc.) accumulate their
    properties positionally, so ``result["CHANNEL"]["channelOutputMute"][i]`` is
    strip ``i``.

    A record is only accepted when its name is followed by ``00 01`` and a valid
    typed value, which prevents value bytes that happen to be ASCII (colour hex,
    strings) from being mis-read as property names.
    """
    groups: dict[str, dict[str, list[Any]]] = {}
    current: str | None = None
    i, n = 0, len(blob)
    name_chars = set(range(48, 58)) | set(range(65, 91)) | set(range(97, 123)) | {95}

    while i < n:
        if blob[i] not in name_chars:
            i += 1
            continue
        j = i
        while j < n and blob[j] in name_chars:
            j += 1
        # require  name 00 01  to accept this as a real record
        if j - i < 3 or j + 1 >= n or blob[j] != 0x00 or blob[j + 1] != 0x01:
            i = j
            continue
        name = blob[i:j].decode("ascii", "replace")
        if name.isupper():
            current = name
            groups.setdefault(current, {})
        elif current and name[0].islower():
            value = decode_value(blob[j + 1:j + 17])
            groups[current].setdefault(name, []).append(value)
        i = j + 1
    return groups


def dump_values(blob: bytes, name: str) -> list[Any]:
    """Every value recorded for ``name``, in dump order (index == channel)."""
    key = name.encode() + b"\x00"
    out, i = [], 0
    while (i := blob.find(key, i)) >= 0:
        out.append(decode_value(blob[i + len(key):i + len(key) + 16]))
        i += 1
    return out
