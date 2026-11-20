"""Finding the control interface. No hardware required."""
import pytest

from rodey import device
from rodey import protocol as p
from rodey.device import DeviceNotFound, Rodecaster


def entry(product_id, usage_page=p.USAGE_PAGE, vendor_id=p.VENDOR_ID, path=None):
    return {
        "vendor_id": vendor_id,
        "product_id": product_id,
        "usage_page": usage_page,
        "path": path or f"hid-{product_id:04x}-{usage_page:04x}".encode(),
    }


@pytest.fixture
def connected(monkeypatch):
    """Pretend these HID interfaces are present."""
    def install(*entries):
        def enumerate(vendor_id=0, product_id=0):
            return [
                e for e in entries
                if vendor_id in (0, e["vendor_id"]) and product_id in (0, e["product_id"])
            ]
        monkeypatch.setattr(device.hid, "enumerate", enumerate)
    return install


def test_finds_the_board_without_multitrack(connected):
    connected(entry(0x0037))
    assert Rodecaster.find() == b"hid-0037-ff00"


@pytest.mark.parametrize("product_id", [0x0078, 0x0094])
def test_finds_the_board_in_the_usb_multitrack_modes(connected, product_id):
    """USB 1 re-enumerates under another product ID when multitrack is switched on."""
    connected(entry(product_id))
    assert Rodecaster.find() == entry(product_id)["path"]


def test_takes_the_vendor_interface_not_the_other_hid_interfaces(connected):
    connected(entry(0x0094, usage_page=0x000C, path=b"consumer"), entry(0x0094, path=b"vendor"))
    assert Rodecaster.find() == b"vendor"


def test_ignores_the_second_usb_port(connected):
    """USB 2 (0x0026) also has a vendor-page HID interface; it is not the control port."""
    connected(entry(0x0026))
    with pytest.raises(DeviceNotFound):
        Rodecaster.find()


def test_ignores_other_devices_of_the_vendor(connected):
    connected(entry(0x1234))
    with pytest.raises(DeviceNotFound):
        Rodecaster.find()


def test_the_original_product_id_constant_is_still_exported():
    assert p.PRODUCT_ID == 0x37
    assert p.PRODUCT_ID in p.PRODUCT_IDS
