"""Channel addressing tests. No hardware required."""
import pytest

from rodey import protocol as p


@pytest.mark.parametrize("strip,expected", [
    (0, 0x1C),   # Mic 1        - confirmed by write
    (1, 0x1D),   # Mic 2        - predicted, then confirmed
    (2, 0x1E),   # Bluetooth    - predicted, then confirmed
    (3, 0x1F),   # USB 1        - confirmed by write
    (4, 0x20),   # Chat         - confirmed by write
    (6, 0x22),   # USB 2        - confirmed by write
    (9, 0x25),   # harvested from app traffic
])
def test_channel_object_ids_match_hardware(strip, expected):
    assert p.channel_object_id(strip) == expected


@pytest.mark.parametrize("bad", [-1, 10, 99])
def test_channel_object_id_rejects_out_of_range(bad):
    """Guard the formula: extrapolating past strip 9 would address unknown
    objects, and writing an unknown property to one permanently mutates it."""
    with pytest.raises(ValueError):
        p.channel_object_id(bad)


def test_channel_ids_are_contiguous():
    ids = [p.channel_object_id(s) for s in range(p.CHANNEL_COUNT)]
    assert ids == list(range(0x1C, 0x1C + p.CHANNEL_COUNT))
    assert len(set(ids)) == p.CHANNEL_COUNT


def test_write_to_channel_encodes_expected_address():
    buf = p.encode_write(p.channel_object_id(1), "noiseGateOn", True)
    assert buf[5:10] == bytes([1, 1, 1, 1, 0x1D])
