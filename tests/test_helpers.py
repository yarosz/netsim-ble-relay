import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from netsim_ble_relay import addresses_from_logcat, build_advertising, pick_public_address  # noqa: E402

LOGCAT = """\
11-15 10:16:19.761 793 1393 D BtGatt.GattService: clientConnect() - address=AA:BB:CC:00:11:22, addressType=1, isDirect=true, opportunistic=false, phy=1
11-15 10:16:19.761 793 1393 D BtGatt.GattService: clientConnect() - address=12:34:56:78:9a:bc, addressType=0, isDirect=false, opportunistic=false, phy=1
11-15 10:17:00.000 793 1393 I bt_stack: unrelated line
"""


def test_addresses_from_logcat():
    assert addresses_from_logcat(LOGCAT) == [("AA:BB:CC:00:11:22", 1), ("12:34:56:78:9A:BC", 0)]


def test_pick_public_address_ignores_random():
    assert pick_public_address(LOGCAT) == "12:34:56:78:9A:BC"
    assert pick_public_address("nothing here") is None


def test_build_advertising_fits_and_moves_name_to_scan_response():
    beacon = bytes.fromhex("0215") + bytes(21)          # 23-byte iBeacon payload
    adv, scan = build_advertising("S0123456789abcdefC", {0x004C: beacon})
    assert len(adv) <= 31 and len(scan) <= 31
    assert adv[:3] == b"\x02\x01\x06"
    assert adv[3:7] == bytes([1 + 2 + len(beacon), 0xFF, 0x4C, 0x00])
    assert scan == bytes([19, 0x09]) + b"S0123456789abcdefC"


def test_build_advertising_drops_maker_data_that_does_not_fit():
    adv, _ = build_advertising("x", {0x004C: bytes(40)})
    assert adv == b"\x02\x01\x06"
