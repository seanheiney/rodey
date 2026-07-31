"""Device connection and high-level API for the RØDECaster Pro II."""
from __future__ import annotations

import time
from typing import Any, Iterator

import hid

from . import protocol as p

#: Upper bound on collecting one full pass of the state tree. The tree cycles
#: continuously, so this caps the wait rather than fixing the read duration.
DUMP_SECONDS = 25.0

#: Start-of-tree marker. The device name opens each cycle; matched as raw bytes
#: because it is UTF-8 ("RØDECaster" -> ``c3 98`` for the Ø).
DUMP_START_MARKER = b"DECaster Pro II"


class DeviceNotFound(RuntimeError):
    pass


class Rodecaster:
    """A connected RØDECaster Pro II.

    The handshake is mandatory: without it, property writes are silently ignored
    and no notifications arrive. :meth:`connect` performs it.

    Note that ``hidapi`` *seizes* the device, so only one instance can be open at
    a time. RØDE's own app opens non-exclusively and can run alongside this.

        with Rodecaster() as rc:
            print(rc.get("noiseGateOn"))
            rc.set(0x1C, "noiseGateOn", True)
    """

    def __init__(self, path: bytes | None = None):
        self._path = path
        self._h: hid.device | None = None
        self._state: bytes = b""

    # ---------------------------------------------------------------- lifecycle

    @staticmethod
    def find() -> bytes:
        for d in hid.enumerate(p.VENDOR_ID, p.PRODUCT_ID):
            if d.get("usage_page") == p.USAGE_PAGE:
                return d["path"]
        raise DeviceNotFound(
            "no RØDECaster Pro II vendor HID interface "
            f"(expected VID 0x{p.VENDOR_ID:04x} / PID 0x{p.PRODUCT_ID:02x})"
        )

    def connect(self, capture: bool = True) -> "Rodecaster":
        """Open the device, handshake, and capture the state dump.

        The dump is captured here rather than on demand because the device starts
        transmitting the instant it is subscribed, and hidapi's queue is shallow.
        Any delay between the session-open and the first read - even 300 ms -
        silently loses the head of the tree, which is where every channel,
        fader and meter property lives. Callers must not be able to introduce
        that gap, so connecting and draining are one operation.
        """
        self._h = hid.device()
        self._h.open_path(self._path or self.find())
        self._h.set_nonblocking(True)
        self._handshake()
        self._state = self.read_dump() if capture else b""
        return self

    def close(self) -> None:
        if self._h:
            self._h.close()
            self._h = None

    def __enter__(self) -> "Rodecaster":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def _dev(self) -> hid.device:
        if self._h is None:
            raise RuntimeError("not connected - call connect() first")
        return self._h

    def _handshake(self) -> None:
        self._dev.write(p.encode_mode())
        time.sleep(0.2)
        self._dev.write(p.encode_session_open())
        # No sleep here on purpose - see connect(). The dump starts immediately.

    # -------------------------------------------------------------------- reads

    def read_raw(self, seconds: float) -> bytes:
        """Concatenate report-4 payloads for a fixed window."""
        blob, end = bytearray(), time.time() + seconds
        while time.time() < end:
            data = self._dev.read(256)
            if not data:
                time.sleep(0.002)
                continue
            blob += bytes(data[1:]).rstrip(b"\x00")
        return bytes(blob)

    def read_dump(self, seconds: float = DUMP_SECONDS,
                  idle_ms: float = 400.0) -> bytes:
        """Collect the state dump the handshake triggers.

        The dump arrives as one burst, then the device goes quiet. Two things
        matter for getting all of it:

        * **Drain aggressively.** hidapi queues a limited number of reports; if
          the reader sleeps during the burst, reports are dropped silently. That
          is why fixed-interval reads returned wildly different sizes (138 KB one
          run, 27 KB the next) with whole sections missing. Never sleep while
          data is flowing.
        * **Stop on idle, not on a timer.** The burst ends when reports stop
          arriving for ``idle_ms``; ``seconds`` is only a safety cap.
        """
        deadline = time.time() + seconds
        idle = idle_ms / 1000.0
        chunks: list[bytes] = []
        last_data = None

        while time.time() < deadline:
            data = self._dev.read(256)
            if data:
                payload = bytes(data[1:]).rstrip(b"\x00")
                if payload:
                    chunks.append(payload)
                last_data = time.time()
                continue                        # no sleep - keep draining
            if last_data is None:
                time.sleep(0.002)               # nothing yet; wait for the burst
            elif time.time() - last_data > idle:
                break                           # burst finished
        return b"".join(chunks)

    @property
    def state(self) -> bytes:
        """The state dump captured at connect."""
        return self._state

    def refresh(self) -> bytes:
        """Re-subscribe and re-capture state. Needed after any write."""
        self._handshake()
        self._state = self.read_dump()
        return self._state

    def get(self, name: str, refresh: bool = False) -> list[Any]:
        """Values for ``name`` across all objects, in dump order.

        Index corresponds to channel order - use ``channelInputSource`` to tell
        which strip is which. The dump carries no object IDs, so this cannot tell
        you the objID needed to write back; use the harvested map for that.
        """
        if refresh or not self._state:
            self.refresh()
        return p.dump_values(self._state, name)

    def watch(self, seconds: float = 10.0) -> Iterator[p.Property]:
        """Yield live change notifications.

        Changes made through *this* handle are not echoed back to it - only
        changes made on the board or by another client appear here.
        """
        end = time.time() + seconds
        while time.time() < end:
            data = self._dev.read(256)
            if not data:
                time.sleep(0.002)
                continue
            prop = p.decode_notification(bytes(data[1:]).rstrip(b"\x00"))
            if prop is not None:
                yield prop

    # ------------------------------------------------------------------- writes

    def muted(self, refresh: bool = False) -> list[bool]:
        """True where a strip is muted, per strip index.

        Translates the device's inverted convention - see
        :data:`protocol.INVERTED_MUTE_PROPERTIES` - so callers get the obvious
        meaning rather than the raw flag.
        """
        return [p.is_muted(v) for v in self.get("channelOutputMute", refresh)]

    def set_muted(self, strip: int, muted: bool) -> None:
        """Mute or unmute a strip, handling the inverted polarity."""
        self.set_channel(strip, "channelOutputMute", p.mute_value(muted))

    def set_channel(self, strip: int, name: str, value: Any) -> None:
        """Write a channel-scoped property by strip index (0-9).

        Prefer this over raw object IDs - it applies ``objID = 0x1C + strip``
        rather than making callers hard-code addresses.
        """
        self.set(p.channel_object_id(strip), name, value)

    def strip_sources(self) -> list[Any]:
        """What is patched to each strip, as raw ``channelInputSource`` codes."""
        return self.get("channelInputSource")

    def snapshot(self, refresh: bool = False) -> dict:
        """Whole device state as {GROUP: {property: [values...]}}."""
        if refresh or not self._state:
            self.refresh()
        return p.parse_dump(self._state)

    def set(self, obj_id: int, name: str, value: Any) -> None:
        """Write a property. Does not verify - see :meth:`set_verified`."""
        self._dev.write(p.encode_write(obj_id, name, value))
        time.sleep(0.3)

    def set_verified(self, obj_id: int, name: str, value: Any) -> bool:
        """Write, then confirm by diffing the state dump.

        This is the only reliable verification. The device does not echo writes
        to the writing handle, and measuring audio is unreliable - a drifting mic
        noise floor produced two opposite wrong conclusions during development.
        """
        before = self.get(name, refresh=True)
        self.set(obj_id, name, value)
        after = self.get(name, refresh=True)
        return before != after
