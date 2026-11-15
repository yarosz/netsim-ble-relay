#!/usr/bin/env python3
"""Relay a real Bluetooth LE device into the Android emulator through the Mac's built-in radio.

    app in the emulator -> netsim -> Bumble peripheral (this script)
        -> CoreBluetooth (bleak) -> the Mac's built-in Bluetooth -> the real device

The script connects to the real device with CoreBluetooth and copies its GATT table. It
publishes a mirror of the device on netsim, the emulator's virtual Bluetooth controller,
and forwards reads, writes, notifications, and indications in both directions.

Many apps never scan. They connect to a saved public address through the controller's
filter accept list, so the mirror can take that address. `--address auto` reads it from
the emulator's logcat line `BtGatt.GattService: clientConnect() - address=...`.

The relay works above the link layer. Devices that require Bluetooth pairing or
link-layer encryption don't work through it.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import glob
import pathlib
import re
import socket
import subprocess
import sys

PROP_NAMES = ("read", "write", "write-without-response", "notify", "indicate")
CLIENT_CONNECT_RE = re.compile(
    r"clientConnect\(\) - address=([0-9A-Fa-f:]{17}), addressType=(\d+)")


def log(*args):
    print(datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3], *args, flush=True)


# ---------------------------------------------------------------- pure helpers (tested)

def addresses_from_logcat(text: str) -> list[tuple[str, int]]:
    """(address, addressType) pairs from Android GattService clientConnect lines, newest last."""
    return [(m.group(1).upper(), int(m.group(2))) for m in CLIENT_CONNECT_RE.finditer(text)]


def pick_public_address(text: str) -> str | None:
    """Most recent public (addressType=0) address an app asked Android to connect to."""
    public = [a for a, t in addresses_from_logcat(text) if t == 0]
    return public[-1] if public else None


def build_advertising(local_name: str, manufacturer_data: dict[int, bytes]) -> tuple[bytes, bytes]:
    """(advertising_data, scan_response) mirroring the real peripheral's name and maker data.

    FLAGS + manufacturer data go in the advertisement when they fit 31 bytes; the name goes in
    the scan response (it often does not fit next to e.g. an iBeacon payload)."""
    def ad(entries):
        return b"".join(bytes([len(v) + 1, t]) + v for t, v in entries)

    main = [(0x01, b"\x06")]
    for company, payload in manufacturer_data.items():
        data = company.to_bytes(2, "little") + payload
        if len(ad(main)) + 2 + len(data) <= 31:
            main.append((0xFF, data))
    scan = []
    if local_name:
        name = local_name.encode()[:29]
        scan.append((0x09 if len(local_name.encode()) <= 29 else 0x08, name))
    return ad(main), ad(scan)


def netsim_ports() -> list[int]:
    """Candidate netsim gRPC ports from netsim.ini files that something is listening on."""
    ports = []
    for ini in [*glob.glob("/var/folders/*/*/T/netsim.ini"), "/tmp/netsim.ini"]:
        try:
            for line in pathlib.Path(ini).read_text().splitlines():
                if line.startswith("grpc.port="):
                    ports.append(int(line.split("=", 1)[1]))
        except (OSError, ValueError):
            pass
    live = []
    for port in ports:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                live.append(port)
    return live


# ---------------------------------------------------------------- the relay

def patch_netsim_chip_address(address: str) -> None:
    """Make netsim give our virtual controller `address` as its public address.

    Bumble 0.0.236 sends netsim a `Chip` message but never sets its `address` field.
    This wraps the `Chip` constructor that the transport calls, so the field is set."""
    from bumble.transport import android_netsim

    original = android_netsim.Chip

    def chip_with_address(*args, **kwargs):
        kwargs.setdefault("address", address)
        return original(*args, **kwargs)

    android_netsim.Chip = chip_with_address


class RealDevice:
    """CoreBluetooth central to the real peripheral (via bleak), reconnecting as needed."""

    def __init__(self, name: str, on_value):
        self.name, self.on_value = name, on_value
        self.client = None
        self.services = []        # [(service_uuid, [(char_uuid, [props])])]
        self.local_name = name
        self.manufacturer_data: dict[int, bytes] = {}
        self.ready = asyncio.Event()
        self.writes: asyncio.Queue = asyncio.Queue()

    async def connect(self):
        from bleak import BleakClient, BleakScanner

        while True:
            log(f"[device] scanning for '{self.name}'")
            found = asyncio.get_running_loop().create_future()

            def seen(dev, adv):
                if (adv.local_name or dev.name) == self.name and not found.done():
                    found.set_result((dev, adv))

            async with BleakScanner(detection_callback=seen):
                try:
                    dev, adv = await asyncio.wait_for(found, 30.0)
                except asyncio.TimeoutError:
                    log("[device] not found yet")
                    continue
            self.manufacturer_data = dict(adv.manufacturer_data)
            log(f"[device] found, rssi={adv.rssi}")
            try:
                self.client = BleakClient(dev, disconnected_callback=self._lost)
                await self.client.connect()
                log(f"[device] connected, mtu={self.client.mtu_size}")
                self.services = [
                    (str(s.uuid), [(str(c.uuid), list(c.properties)) for c in s.characteristics])
                    for s in self.client.services]
                for _, chars in self.services:
                    for uuid, props in chars:
                        if "notify" in props or "indicate" in props:
                            await self.client.start_notify(
                                uuid, lambda c, data: self.on_value(str(c.uuid), bytes(data)))
                            log(f"[device] subscribed {uuid}")
                self.ready.set()
                return
            except Exception as e:  # noqa: BLE001
                log(f"[device] connect failed: {e}; retrying")
                await asyncio.sleep(2)

    def _lost(self, _client):
        log("[device] disconnected; reconnecting")
        self.ready.clear()
        asyncio.get_event_loop().create_task(self.connect())

    async def reset(self):
        """Fresh connection for a fresh app session."""
        self.ready.clear()
        if self.client and self.client.is_connected:
            await self.client.disconnect()   # _lost() reconnects
        else:
            await self.connect()

    async def read(self, uuid: str) -> bytes:
        await self.ready.wait()
        return bytes(await self.client.read_gatt_char(uuid))

    async def writer(self):
        while True:
            uuid, data, with_response = await self.writes.get()
            await self.ready.wait()
            try:
                await self.client.write_gatt_char(uuid, data, response=with_response)
                log(f"[app->device] {uuid[:8]} {len(data)}B ok")
            except Exception as e:  # noqa: BLE001
                log(f"[app->device] {uuid[:8]} {len(data)}B FAILED: {e}")


# Bumble's Device provides its own GAP (0x1800) and GATT (0x1801) services.
SKIP_SERVICES = {f"0000{s}-0000-1000-8000-00805f9b34fb" for s in ("1800", "1801")}


def mirror_characteristic(real: RealDevice, uuid: str, props: list[str]):
    """One Bumble characteristic whose reads/writes are forwarded to the real device."""
    from bumble.gatt import Characteristic, CharacteristicValue

    P = Characteristic.Properties
    flags = P(0)
    for name, flag in (("read", P.READ), ("write", P.WRITE),
                       ("write-without-response", P.WRITE_WITHOUT_RESPONSE),
                       ("notify", P.NOTIFY), ("indicate", P.INDICATE)):
        if name in props:
            flags |= flag
    writable = "write" in props or "write-without-response" in props
    perms = (Characteristic.READABLE if "read" in props else 0) | \
            (Characteristic.WRITEABLE if writable else 0)

    async def read(_connection):
        try:
            return await real.read(uuid)
        except Exception as e:  # noqa: BLE001
            log(f"[device] read {uuid[:8]} failed: {e}")
            return b""

    def write(_connection, value):
        real.writes.put_nowait((uuid, bytes(value), "write" in props))

    value = CharacteristicValue(read=read if "read" in props else None,
                                write=write if writable else None)
    return Characteristic(uuid, flags, perms or Characteristic.READABLE, value)


def build_mirror(real: RealDevice):
    """Bumble services mirroring real.services; returns (services, {char_uuid: Characteristic})."""
    from bumble.gatt import Service

    services, by_uuid = [], {}
    for service_uuid, chars in real.services:
        if service_uuid.lower() in SKIP_SERVICES:
            continue
        mirrored = [mirror_characteristic(real, uuid, props) for uuid, props in chars]
        by_uuid.update({uuid.lower(): c for (uuid, _), c in zip(chars, mirrored)})
        services.append(Service(service_uuid, mirrored))
    return services, by_uuid


async def run(args):
    from bumble.device import Device
    from bumble.hci import Address, OwnAddressType
    from bumble.transport import open_transport

    loop = asyncio.get_running_loop()
    values: asyncio.Queue = asyncio.Queue()
    real = RealDevice(args.name, lambda uuid, data: loop.call_soon_threadsafe(
        values.put_nowait, (uuid, data)))
    await real.connect()

    address = args.address
    if address == "auto":
        text = subprocess.run(["adb", *(["-s", args.serial] if args.serial else []),
                               "logcat", "-d"], capture_output=True, text=True).stdout
        address = pick_public_address(text)
        if not address:
            sys.exit("--address auto: no clientConnect() with a public address in logcat yet. "
                     "Open the app once, or pass --address XX:XX:XX:XX:XX:XX.")
        log(f"[netsim] cached public address from logcat: {address}")

    port = args.netsim_port
    if not port:
        ports = netsim_ports()
        if len(ports) != 1:
            sys.exit(f"Found netsim gRPC ports {ports}; pass --netsim-port.")
        port = ports[0]
    spec = f"android-netsim:127.0.0.1:{port}"
    if address:
        patch_netsim_chip_address(address)
    log(f"[netsim] transport {spec}")

    async with await open_transport(spec) as hci:
        device = Device.with_hci(real.local_name, Address("F0:F1:F2:F3:F4:F5"), hci.source, hci.sink)
        services, by_uuid = build_mirror(real)
        device.add_services(services)
        device.advertising_data, device.scan_response_data = build_advertising(
            real.local_name, real.manufacturer_data)

        async def forward_values():
            while True:
                uuid, data = await values.get()
                char = by_uuid.get(uuid.lower())
                if char is None:
                    continue
                log(f"[device->app] {uuid[:8]} {len(data)}B")
                # Each call only reaches subscribers whose CCCD enabled that mode.
                await device.notify_subscribers(char, value=data)
                await device.indicate_subscribers(char, value=data)

        @device.on("connection")
        def on_connection(connection):
            log(f"[netsim] app connected from {connection.peer_address}")

            @connection.on("disconnection")
            def on_disconnection(reason):
                log(f"[netsim] app disconnected (0x{reason:02X}); resetting device session")
                loop.create_task(real.reset())

        await device.power_on()
        await device.start_advertising(
            auto_restart=True,
            own_address_type=OwnAddressType.PUBLIC if address else OwnAddressType.RANDOM)
        log(f"[netsim] advertising '{real.local_name}' as "
            f"{device.public_address if address else device.random_address}")
        await asyncio.gather(real.writer(), forward_values())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", required=True, help="local name that the real device advertises")
    ap.add_argument("--address", help="public address for the mirror (XX:XX:XX:XX:XX:XX), or 'auto' to "
                                      "read the app's saved address from adb logcat")
    ap.add_argument("--netsim-port", type=int, help="netsim gRPC port (default: from netsim.ini)")
    ap.add_argument("--serial", help="adb serial for --address auto, such as emulator-5554")
    args = ap.parse_args(argv)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
