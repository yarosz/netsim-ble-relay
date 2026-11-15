# netsim-ble-relay

`netsim_ble_relay.py` lets an app in the Android emulator talk to a real Bluetooth LE device through your Mac's built-in Bluetooth. You don't need a USB dongle or a second computer, and System Integrity Protection stays on.

The script connects to the real device with CoreBluetooth and copies its GATT table. It then publishes a mirror of the device on netsim, the emulator's virtual Bluetooth controller. A mirror is a virtual device with the same GATT table, name, and maker data. The relay forwards reads, writes, notifications, and indications in both directions. The app uses the normal Android Bluetooth APIs, so you don't change the app.

```
app in the emulator
	-> netsim
	-> Bumble peripheral (netsim_ble_relay.py)
	-> CoreBluetooth (bleak)
	-> the Mac's built-in Bluetooth
	-> the real device
```

The relay works only with devices that don't require Bluetooth pairing. To learn why, and what the relay is useful for, read [How the relay works](docs/how-it-works.md).

## Requirements

- A Mac with Apple silicon and Python 3.11 or later. The relay was tested on macOS 26.7 with an M3 Pro.
- An Android emulator with Bluetooth turned on in the AVD. Every current emulator includes netsim.
- Bluetooth permission for your terminal app, in **System Settings > Privacy & Security > Bluetooth**.
- A Bluetooth LE device in range that doesn't require pairing.

## Run the relay

1. Install the dependencies:

	```bash
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt
	```

2. Start the emulator on netsim. Netsim is the default, and `-packet-streamer-endpoint default` makes that explicit:

	```bash
	emulator -avd MyAvd -packet-streamer-endpoint default
	```

3. Open your app in the emulator once, so that Android tries to connect to the device and logs its address.

4. Start the relay. Replace `MyDevice` with the name that the device advertises:

	```bash
	.venv/bin/python netsim_ble_relay.py --name "MyDevice" --address auto --serial emulator-5554
	```

	When the app connects, the log shows lines like these:

	```
	[device] connected, mtu=247
	[netsim] advertising 'MyDevice' as XX:XX:XX:XX:XX:XX/P
	[netsim] app connected from ...
	[app->device] 00000212 101B ok
	[device->app] 00000213 85B
	```

If your app scans for the device instead of connecting to a saved address, leave out `--address`. The mirror then advertises from a random address.

When the app disconnects, the relay closes its connection to the real device and opens a new one. Each app session starts from a fresh connection.

## Flags

| Flag | Meaning |
|---|---|
| `--name` | The local name that the real device advertises. Required. |
| `--address` | The public address for the mirror, as `XX:XX:XX:XX:XX:XX`. `auto` reads the most recent `clientConnect() - address=..., addressType=0` line from `adb logcat`. Without this flag, the mirror uses a random address. |
| `--netsim-port` | The netsim gRPC port. Default: the port in `netsim.ini` that accepts connections. |
| `--serial` | The adb serial of the emulator, used by `--address auto`. |

## Run the relay in the background

[`contrib/netsim-ble-relay.plist`](contrib/netsim-ble-relay.plist) is a launchd agent template.

1. Replace the paths and arguments in the file.
2. Copy the file to `~/Library/LaunchAgents/`.
3. Run `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/netsim-ble-relay.plist`.

The process that launchd starts needs Bluetooth permission. If it doesn't get the permission, run the relay from a terminal that has it.

## Run the tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Credits

- [Bumble](https://github.com/google/bumble) (Apache-2.0) runs the Bluetooth host stack and connects to netsim.
- [bleak](https://github.com/hbldh/bleak) (MIT) drives CoreBluetooth.
- [MacPhone](https://github.com/jx-grxf/MacPhone) first mirrored CoreBluetooth devices onto netsim. This project does the same in one process and adds the public-address and indication handling that some apps need.

## License

MIT
