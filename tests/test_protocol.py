"""Protocol encode/decode tests. No hardware required."""
import struct

import pytest

from rodey import protocol as p


def test_mode_refuses_firmware_update():
    """0x4D enters firmware update mode - it must never be sendable."""
    with pytest.raises(p.UnsafeCommand, match="update mode"):
        p.encode_mode(0x4D)


def test_mode_refuses_flash():
    """0x55 triggers a firmware flash. A public project mislabels it 'ping'."""
    with pytest.raises(p.UnsafeCommand, match="flash"):
        p.encode_mode(0x55)


def test_mode_normal_matches_captured_app_frame():
    buf = p.encode_mode()
    assert buf[:2] == bytes([0x01, 0x4E])
    assert len(buf) == p.REPORT_MODE_SIZE
    assert set(buf[2:]) == {0}


def test_session_open_matches_capture():
    buf = p.encode_session_open()
    assert buf[:9] == bytes([0x03, 0x04, 0x00, 0x00, 0x00, 0xAD, 0x10, 0xA7, 0xB0])


def test_encode_write_bool_matches_captured_frame():
    """Byte-for-byte against a frame captured from RODE's app."""
    captured = bytes.fromhex(
        "0314000000010101011c6e6f6973654761746"
        "54f6e00010103"
    )
    buf = p.encode_write(0x1C, "noiseGateOn", True)
    assert buf[:len(captured)] == captured


def test_encode_write_float_matches_captured_frame():
    # body = addr(4) + objID(1) + name(18) + NUL(1) + tag(2) + payload(9) = 35 = 0x23
    buf = p.encode_write(0x1C, "noiseGateThreshold", 0.5)
    assert buf[1:5] == struct.pack("<I", 0x23)          # body length
    assert buf[5:10] == bytes([1, 1, 1, 1, 0x1C])       # address
    assert buf[29:32] == bytes([0x01, 0x09, 0x04])      # tag: float64
    assert struct.unpack("<d", buf[32:40])[0] == 0.5
    assert len(buf) == p.REPORT_PROP_SIZE


@pytest.mark.parametrize("value", [True, False])
def test_bool_roundtrip(value):
    """A write frame decodes back to the same property via the read path."""
    buf = p.encode_write(0x1C, "noiseGateOn", value)
    prop = p.decode_notification(buf[1:].rstrip(b"\x00"))
    assert prop is not None
    assert prop.obj_id == 0x1C
    assert prop.name == "noiseGateOn"
    assert prop.value is value


def test_decode_value_types():
    assert p.decode_value(bytes([0x01, 0x01, 0x03])) is True
    assert p.decode_value(bytes([0x01, 0x01, 0x02])) is False
    f = bytes([0x01, 0x09, 0x04]) + struct.pack("<d", 0.25)
    assert p.decode_value(f) == 0.25
    s = bytes([0x01, 0x06, 0x05]) + b"hi\x00"
    assert p.decode_value(s) == "hi"


def test_decode_notification_rejects_garbage():
    assert p.decode_notification(b"") is None
    assert p.decode_notification(b"\x00" * 12) is None


def test_dump_values_reads_positionally():
    """Channel identity in the dump is positional - there are no object IDs."""
    rec = lambda v: b"noiseGateOn\x00" + bytes([0x01, 0x01, 0x03 if v else 0x02])
    blob = rec(False) + b"junk" + rec(True) + rec(False)
    assert p.dump_values(blob, "noiseGateOn") == [False, True, False]


def test_obj_id_range_validated():
    with pytest.raises(ValueError):
        p.encode_write(0x1FF, "noiseGateOn", True)


def test_int_and_float_encode_differently():
    """Faders are uint32 0..127; processing params are float64 0..1.
    Passing the wrong one yields a valid frame the device ignores."""
    as_int = p.encode_value(1)
    as_float = p.encode_value(1.0)
    assert as_int[2] == p.T_UINT32 and len(as_int) == 7
    assert as_float[2] == p.T_FLOAT64 and len(as_float) == 11
    assert as_int != as_float


def test_fader_properties_are_flagged_int_ranged():
    assert "faderLevel" in p.INT_RANGED_PROPERTIES
    assert "potLevel" in p.INT_RANGED_PROPERTIES
    assert "noiseGateThreshold" not in p.INT_RANGED_PROPERTIES


def test_uint32_roundtrip_at_fader_bounds():
    for v in (0, 64, p.INT_RANGE_MAX):
        assert p.decode_value(p.encode_value(v)) == v


def test_mute_polarity_is_inverted():
    """Hardware-confirmed: muting Bluetooth on the board took
    channelOutputMute from True -> False. The name lies; False means muted."""
    assert p.is_muted(False) is True
    assert p.is_muted(True) is False
    assert p.mute_value(muted=True) is False
    assert p.mute_value(muted=False) is True


def test_mute_helpers_roundtrip():
    for muted in (True, False):
        assert p.is_muted(p.mute_value(muted)) is muted


def test_inverted_properties_are_declared():
    assert "channelOutputMute" in p.INVERTED_MUTE_PROPERTIES
    assert "mixMute" in p.INVERTED_MUTE_PROPERTIES


def test_faders_declared_read_only():
    """Not an undiscovered command: the faders are physical and not motorised,
    so a written value would disagree with the slider's actual position."""
    assert "faderLevel" in p.READ_ONLY_PROPERTIES
    # encoders have no absolute position and are writable
    assert "outputMonLevel" not in p.READ_ONLY_PROPERTIES
    assert "noiseGateThreshold" not in p.READ_ONLY_PROPERTIES


@pytest.mark.parametrize("name", [
    "updateResetDeviceRequested", "updateInitiateRequested", "storageVolumeErase",
])
def test_destructive_writes_refused(name):
    """These reach the same class of harm as the firmware mode bytes, but through
    the ordinary property channel."""
    with pytest.raises(p.UnsafeCommand, match="resets, reformats or re-flashes"):
        p.encode_write(0x0F, name, True)


def test_read_only_writes_refused():
    with pytest.raises(p.UnsafeCommand, match="read-only"):
        p.encode_write(0x10, "faderLevel", 64)


def test_ordinary_writes_still_allowed():
    assert p.encode_write(0x1C, "noiseGateOn", True)
    assert p.encode_write(0x1C, "noiseGateThreshold", 0.5)


def test_decode_value_rejects_truncated_float():
    """A float64 tag with too few payload bytes must return None, not garbage."""
    assert p.decode_value(bytes([0x01, 0x09, 0x04, 0x00, 0x00])) is None


def test_parse_dump_groups_and_positions():
    blob = (b"CHANNEL\x00\x01\x02"
            b"channelOutputMute\x00\x01\x01\x03"
            b"channelOutputMute\x00\x01\x01\x02"
            b"SYSTEM\x00\x01\x02"
            b"systemSerialNumber\x00\x01\x0b\x05GV1\x00")
    g = p.parse_dump(blob)
    assert g["CHANNEL"]["channelOutputMute"] == [True, False]
    assert g["SYSTEM"]["systemSerialNumber"] == ["GV1"]


def test_parse_dump_ignores_ascii_value_bytes_as_names():
    """A colour hex value must not be mistaken for a property name."""
    blob = (b"HEADPHONE\x00\x01\x02"
            b"headphoneColour\x00\x01\x06\x05 abcd\x00")
    g = p.parse_dump(blob)
    assert list(g["HEADPHONE"].keys()) == ["headphoneColour"]
