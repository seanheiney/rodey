"""Unofficial control library for the RØDECaster Pro II.

RØDE publishes no host API. This talks to the board over its vendor HID interface,
using a protocol reverse-engineered by observing RØDE's own app. See docs/PROTOCOL.md.

    from rodey import Rodecaster

    with Rodecaster() as rc:
        print(rc.get("noiseGateOn"))       # per-channel, in dump order
        rc.set_verified(0x1C, "noiseGateOn", True)
"""
from __future__ import annotations

from .device import DUMP_SECONDS, DeviceNotFound, Rodecaster
from .protocol import (
    MODE_NORMAL,
    PRODUCT_ID,
    VENDOR_ID,
    Property,
    UnsafeCommand,
    decode_notification,
    dump_values,
    parse_dump,
    encode_write,
)

__version__ = "0.1.0"

__all__ = [
    "Rodecaster",
    "DeviceNotFound",
    "UnsafeCommand",
    "Property",
    "DUMP_SECONDS",
    "VENDOR_ID",
    "PRODUCT_ID",
    "MODE_NORMAL",
    "encode_write",
    "decode_notification",
    "dump_values",
    "parse_dump",
    "__version__",
]
