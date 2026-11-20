"""Message framing on report 4. No hardware required.

Every message on report 4 starts in a report of its own with a uint32 length and then
runs across as many reports as it needs; only the rest of the last report is padding.
Measured on firmware 1.7.3 from a capture of all 637 reports of one connection: the
state tree was a single message of 160,701 bytes.
"""
import struct

from rodey import protocol as p
from rodey.device import Rodecaster

PAYLOAD = 255  # bytes per report after the report ID


def reports_for(body: bytes, report_id: int = p.REPORT_PROP_IN) -> list[bytes]:
    """Split one message into reports the way the device does."""
    message = struct.pack("<I", len(body)) + body
    chunks = [message[i:i + PAYLOAD] for i in range(0, len(message), PAYLOAD)]
    return [bytes([report_id]) + c.ljust(PAYLOAD, b"\x00") for c in chunks]


def notification(obj_id: int, name: str, value_bytes: bytes) -> bytes:
    return p.ADDR_PREFIX + bytes([obj_id]) + name.encode() + b"\x00" + value_bytes


def feed_all(reports):
    r = p.Reassembler()
    out = []
    for rep in reports:
        out += r.feed(rep)
    return out


# A tree whose first report ends in four zero bytes that belong to the data:
# 4 length bytes + 12 root bytes + 235 filler + 4 zeros fill the first report exactly.
TREE = p.TREE_ROOT + b"x" * 235 + b"\x00\x00\x00\x00" + b"channelPan\x00\x01\x01\x03"


def test_message_in_one_report():
    body = notification(0x0B, "recordingMultitrackMode", b"\x01\x05\x01\x02\x00\x00\x00")
    assert feed_all(reports_for(body)) == [body]


def test_message_spanning_reports_is_joined():
    body = p.TREE_ROOT + bytes(range(1, 251)) * 4
    assert len(reports_for(body)) > 1
    assert feed_all(reports_for(body)) == [body]


def test_zero_bytes_at_a_report_boundary_survive():
    """Stripping the zeros of every report loses these four; the framing keeps them."""
    reports = reports_for(TREE)
    assert reports[0].endswith(b"\x00\x00\x00\x00")
    assert feed_all(reports) == [TREE]


def test_padding_after_a_message_is_not_part_of_it():
    body = notification(0x10, "channelOutputMute", b"\x01\x01\x02")
    (report,) = reports_for(body)
    assert len(report) == 256 and report.endswith(b"\x00")
    assert feed_all([report]) == [body]


def test_messages_follow_each_other():
    a = notification(0x04, "encoderColour", b"\x01\x05\x01\x07\x00\x00\x00")
    assert feed_all(reports_for(a) + reports_for(TREE) + reports_for(a)) == [a, TREE, a]


def test_other_report_ids_are_ignored():
    """The reply to the mode command arrives on report 2 and is not part of the state."""
    ack = bytes([p.REPORT_MODE_IN]) + b"AR\xc3\x98DECaster Pro II".ljust(63, b"\x00")
    assert feed_all([ack] + reports_for(TREE)) == [TREE]


def test_empty_and_all_zero_reports_are_ignored():
    r = p.Reassembler()
    assert r.feed(b"") == []
    assert r.feed(bytes([p.REPORT_PROP_IN]) + bytes(PAYLOAD)) == []


def test_state_tree_is_recognised_by_its_root():
    assert p.is_state_tree(TREE)
    assert not p.is_state_tree(notification(0x10, "channelOutputMute", b"\x01\x01\x02"))


class FakeHid:
    def __init__(self, reports):
        self._reports = list(reports)

    def read(self, size):
        return list(self._reports.pop(0)) if self._reports else []


def connected(reports) -> Rodecaster:
    rc = Rodecaster(b"fake")
    rc._h = FakeHid(reports)
    return rc


def test_read_dump_returns_the_complete_tree():
    note = notification(0x04, "encoderColour", b"\x01\x05\x01\x07\x00\x00\x00")
    rc = connected(reports_for(note) + reports_for(TREE) + reports_for(note))
    assert rc.read_dump(seconds=1.0) == TREE


def test_read_dump_values_keep_their_position():
    """A lost zero after a property name used to drop that entry from the list."""
    name_at_boundary = b"x" * (PAYLOAD - 4 - len(p.TREE_ROOT) - len(b"compressorOn"))
    tree = (p.TREE_ROOT + name_at_boundary + b"compressorOn" + b"\x00\x01\x01\x03"
            + b"compressorOn\x00\x01\x01\x02")
    reports = reports_for(tree)
    assert reports[0].endswith(b"compressorOn")       # the 00 opens the next report
    rc = connected(reports)
    assert p.dump_values(rc.read_dump(seconds=1.0), "compressorOn") == [True, False]


def test_read_dump_without_a_tree_is_empty():
    rc = connected([])
    assert rc.read_dump(seconds=0.05, idle_ms=10) == b""


def test_watch_decodes_values_that_end_in_zero_bytes():
    """uint32 2 is 01 02 00 00 00: its zeros are data, not padding."""
    body = notification(0x0B, "recordingMultitrackMode", b"\x01\x05\x01\x02\x00\x00\x00")
    rc = connected(reports_for(body))
    assert list(rc.watch(seconds=0.05)) == [p.Property(0x0B, "recordingMultitrackMode", 2)]


def test_watch_skips_the_state_tree():
    body = notification(0x10, "channelOutputMute", b"\x01\x01\x02")
    rc = connected(reports_for(TREE) + reports_for(body))
    assert list(rc.watch(seconds=0.05)) == [p.Property(0x10, "channelOutputMute", False)]
