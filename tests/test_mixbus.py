"""Mix-bus mute addressing. Values captured from hardware."""
import pytest

from rodey import protocol as p

# Block bases observed by muting each channel on the board and watching which
# 13-object run emitted. Keyed by channelInputSource, not strip position.
OBSERVED_BASES = {
    0: 0x4C,    # Mic 1
    1: 0x59,    # Mic 2
    7: 0xA7,    # USB 1
    8: 0xB4,    # Chat
    9: 0xC1,    # USB 2
    10: 0xCE,   # Bluetooth
    11: 0xDB,   # SMART Pads
}


@pytest.mark.parametrize("source,base", sorted(OBSERVED_BASES.items()))
def test_block_base_matches_hardware(source, base):
    assert p.mix_mute_object_id(source, 0) == base


@pytest.mark.parametrize("source,base", sorted(OBSERVED_BASES.items()))
def test_blocks_are_thirteen_contiguous(source, base):
    block = list(p.mix_mute_block(source))
    assert block == list(range(base, base + 13))


def test_blocks_do_not_overlap():
    seen: set[int] = set()
    for source in OBSERVED_BASES:
        block = set(p.mix_mute_block(source))
        assert not (block & seen), f"source {source} overlaps another block"
        seen |= block


def test_bus_index_validated():
    with pytest.raises(ValueError):
        p.mix_mute_object_id(0, 13)
    with pytest.raises(ValueError):
        p.mix_mute_object_id(0, -1)


def test_chat_bus_is_addressable():
    """The Chat send is the mix-minus path; every source must be scopeable on it."""
    for source in OBSERVED_BASES:
        ids = list(p.mix_mute_block(source))
        assert len(set(ids)) == 13
