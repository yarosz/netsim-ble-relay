# netsim-ble-relay

Give the Android emulator on a Mac a **real** Bluetooth LE peripheral, using the Mac's **built-in** radio. No USB dongle, no Raspberry Pi, SIP stays on.

```
Android app in the emulator
  -> netsim (the emulator's virtual Bluetooth controller)
  -> Bumble peripheral run by this script   (a mirror of the real device)
  -> CoreBluetooth central (bleak)
  -> the Mac's built-in Bluetooth
  -> the real BLE peripheral
```

The script connects to the real peripheral with CoreBluetooth, copies its GATT table, and publishes a mirror on netsim. Reads, writes, notifications and indications go both ways. The app under test uses the normal Android Bluetooth APIs. You don't change the app.

It was built to run a car's phone-key app in the emulator, and it works for that (see [Phone-key apps](#phone-key-apps)). Nothing in it is car-specific.

## Why this works when "real Bluetooth in the emulator" usually doesn't

The usual route is to hand the emulator a raw HCI controller: a USB dongle through [Bumble](https://github.com/google/bumble)'s `hci-bridge`, or a Linux box over TCP. A Mac's built-in radio can't do that: on current macOS the raw-HCI paths are stubbed out or gated by Apple-only entitlements ([details](docs/macos-raw-hci.md)).

This tool goes around HCI. CoreBluetooth, the supported API, talks to the real device. The emulator gets a virtual peripheral on netsim that forwards everything at the GATT layer.

Two details make it work with real apps:

1. **The mirror can take the real device's public address.** Many apps never scan. They auto-connect to a cached address through the controller's filter accept list, so a mirror on any other address is silently ignored. Netsim accepts a chip address when a device registers. Bumble doesn't set it yet, so this script fills it in at runtime. `--address auto` reads the cached address from the emulator's logcat.
2. **Indications are forwarded as indications.** Apps that subscribe with CCCD `0x0002` (indicate only) never see values sent as notifications.

## Requirements

- macOS on Apple silicon (tested on macOS 26.7, M3 Pro), Python 3.11+
- Android emulator with netsim (any current emulator), Bluetooth on in the AVD
- Bluetooth permission for your terminal app (System Settings > Privacy & Security > Bluetooth)
- A BLE peripheral in range that does **not** require link-layer pairing (see Limits)

## Use

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Start the emulator on netsim (the default; -packet-streamer-endpoint default makes it explicit)
emulator -avd MyAvd -packet-streamer-endpoint default

# Open your app once so Android tries to connect, then:
.venv/bin/python netsim_ble_relay.py --name "MyDevice" --address auto --serial emulator-5554
```

| Flag | |
|---|---|
| `--name` | Advertised local name of the real peripheral. Required. |
| `--address` | Public address for the mirror. `auto` takes the latest `clientConnect() - address=..., addressType=0` from `adb logcat`. Omit it for a random address (fine for apps that scan). |
| `--netsim-port` | netsim gRPC port. Default: read from `netsim.ini` (only ports that are listening). |
| `--serial` | adb serial for `--address auto`. |

What a working run looks like:

```
[device] connected, mtu=247
[device] subscribed 00000213-...
[netsim] advertising 'MyDevice' as XX:XX:XX:XX:XX:XX/P
[netsim] app connected from ...
[app->device] 00000212 101B ok
[device->app] 00000213 85B
```

When the app disconnects, the relay drops and re-opens its connection to the real device, so every app session starts clean.

## Use cases

Anything that talks to a BLE peripheral without link-layer pairing:

- **Android-only companion apps on a Mac.** Lights, scales, printers, e-bike or scooter settings, controllers whose only app is on Android.
- **BLE app development without a phone.** Iterate on the Android side against your real ESP32/nRF52/Pico W firmware.
- **Hardware-in-the-loop CI on Mac runners.** UI tests against real devices with no phone farm.
- **Standard sensor profiles.** Heart rate, cycling power/speed/cadence, smart trainers (FTMS).
- **Debugging your own devices.** Every write and indication passes through one Python file. Log it, delay it, drop or replay it.
- **Keeping old apps alive** after the phone they ran on is gone.

Not a fit: devices that need bonding/encryption, and beacons whose advertisement data changes over time (the mirror copies the advertisement once, at start).

## Phone-key apps

Tested with a car's phone-key app (Tesla). The protocol is plain GATT with all security in the app's own end-to-end cryptography, so the relay forwards bytes it can neither read nor forge. The app sees the same responses it would get on a phone, and the car authenticates the app's key, not the radio.

- The app auto-connected to the car's cached public address, which is why `--address auto` exists.
- The phone key must already be enrolled. This tool doesn't add keys and sends nothing of its own.
- Walk-up passive entry is ranged from the Mac's position, not the emulator's. Cars that range with UWB can't do passive entry through any emulator. App-initiated BLE actions are unaffected.
- A relay adds a few milliseconds. Tesla has said BLE relaying is a known limitation of passive entry ([NCC Group, 2022](https://www.nccgroup.com/us/research-blog/technical-advisory-tesla-ble-phone-as-a-key-passive-entry-vulnerable-to-relay-attacks/)). This tool relays your own app to your own car on one desk.

## Limits

- **No link-layer pairing or encryption.** The mirror sits above the link layer, so devices that need bonding (or characteristics that return *Insufficient Encryption*) won't work through it.
- BLE only. macOS gives apps no Bluetooth Classic access.
- One real device and one app connection at a time.
- macOS hides peripheral addresses from CoreBluetooth, so the public address has to come from the Android side (`--address auto`) or from you.

## Run it in the background (optional)

[`contrib/netsim-ble-relay.plist`](contrib/netsim-ble-relay.plist) is a launchd agent template. Fill in the paths and arguments, copy it to `~/Library/LaunchAgents/`, then `launchctl bootstrap gui/$(id -u) <file>`. The process that launchd starts needs Bluetooth permission. If it doesn't get it, run the script from a terminal that has it.

## Tests

```bash
.venv/bin/pip install pytest && .venv/bin/python -m pytest -q
```

## Credits

- [Bumble](https://github.com/google/bumble) (Apache-2.0) does the Bluetooth host side and talks to netsim.
- [bleak](https://github.com/hbldh/bleak) (MIT) drives CoreBluetooth.
- [MacPhone](https://github.com/jx-grxf/MacPhone) showed the CoreBluetooth-to-netsim mirror idea. This is a single-process take that adds the public-address and indication handling.

## License

MIT
