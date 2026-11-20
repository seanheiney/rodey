"""Objects beyond position 255. No hardware required.

An object's "ID" is its position among the children of the state tree's root, written as
a small integer: one length byte, then that many bytes little endian. The board has well
over 256 top-level objects (676 on firmware 1.7.3), so positions from 256 on take two
bytes. The board itself reports changes of such objects in this form.
"""
import pytest

from rodey import protocol as p

# Reported by the board when a fader carrying the USB "Game" source was muted:
# object 0x0101, a MIX object of that source.
BOARD_NOTIFICATION = bytes.fromhex("010101020101") + b"mixMute\x00" + bytes.fromhex("010102")


def body_of(frame: bytes) -> bytes:
    length = int.from_bytes(frame[1:5], "little")
    return frame[5:5 + length]


def framed(body: bytes) -> bytes:
    return len(body).to_bytes(4, "little") + body


def test_write_to_a_wide_position_matches_what_the_board_reports():
    assert body_of(p.encode_write(0x0101, "mixMute", False)) == BOARD_NOTIFICATION


def test_narrow_positions_are_encoded_as_before():
    frame = p.encode_write(0x1C, "noiseGateOn", True)
    assert body_of(frame).startswith(p.ADDR_PREFIX + b"\x1c" + b"noiseGateOn\x00")
    assert body_of(p.encode_write(0xFF, "mixMute", True))[:5] == bytes.fromhex("01010101ff")


@pytest.mark.parametrize("obj_id, address", [
    (0x0100, "010101020001"),
    (0x016D, "010101026d01"),
    (0xFFFF, "01010102ffff"),
])
def test_wide_position_encoding(obj_id, address):
    assert body_of(p.encode_write(obj_id, "mixMute", True))[:6] == bytes.fromhex(address)


def test_wide_write_is_still_one_padded_report():
    frame = p.encode_write(0x0101, "mixMute", False)
    assert frame[0] == p.REPORT_PROP_OUT
    assert len(frame) == p.REPORT_PROP_SIZE


@pytest.mark.parametrize("obj_id", [-1, 0x10000, 0x7FFFFFFF])
def test_positions_outside_two_bytes_are_refused(obj_id):
    with pytest.raises(ValueError):
        p.encode_write(obj_id, "mixMute", True)


def test_safety_refusals_apply_to_wide_positions_too():
    with pytest.raises(p.UnsafeCommand):
        p.encode_write(0x0101, "storageVolumeErase", True)
    with pytest.raises(p.UnsafeCommand):
        p.encode_write(0x0101, "faderLevel", 5)


def test_notification_from_a_wide_position_is_decoded():
    assert p.decode_notification(framed(BOARD_NOTIFICATION)) == p.Property(0x0101, "mixMute", False)


def test_narrow_notification_is_decoded_as_before():
    body = p.ADDR_PREFIX + b"\x0b" + b"recordingMultitrackMode\x00" + bytes.fromhex("01050102000000")
    assert p.decode_notification(framed(body)) == p.Property(0x0B, "recordingMultitrackMode", 2)


def test_wide_write_round_trips_through_decode():
    frame = p.encode_write(0x010E, "mixMute", True)
    assert p.decode_notification(frame[1:]) == p.Property(0x010E, "mixMute", True)


def test_nested_addresses_are_still_not_decoded_as_top_level_objects():
    """A mute button: root -> child 0 -> child 0x2b. Not a top-level object."""
    body = bytes.fromhex("01010200012b") + b"mutePressed\x00" + bytes.fromhex("010103")
    assert p.decode_notification(framed(body)) is None
