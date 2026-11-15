# How the relay works

The usual way to give the Android emulator real Bluetooth is to hand it a raw HCI controller. You plug in a USB dongle and connect it with Bumble's `hci-bridge`, or you forward a Linux machine's controller over TCP. A Mac's built-in Bluetooth can't do that, because current macOS blocks raw HCI access to it. [Why the Mac's built-in radio can't be a raw HCI controller](macos-raw-hci.md) has the evidence.

The relay avoids HCI. CoreBluetooth, the API that Apple supports, talks to the real device. The emulator talks to a mirror of the device on netsim: a virtual device with the same GATT table. Between the two, the relay forwards GATT operations: reads, writes, notifications, and indications. Android's Bluetooth stack runs unchanged on netsim's virtual controller, and macOS keeps its own Bluetooth devices, such as your mouse and keyboard.

## The mirror has to use the real device's address

Many apps never scan for their device. They save the device's public address and ask Android to connect to it automatically. Android then adds the address to the controller's filter accept list and connects when that address advertises. A mirror that advertises from any other address never gets a connection, and the app shows no error.

When a client registers a virtual controller, netsim accepts a public address for it in the `address` field of the `Chip` message. Bumble 0.0.236 doesn't fill in that field, so `patch_netsim_chip_address()` sets it before the relay connects. The relay then advertises with the public address.

macOS hides device addresses from CoreBluetooth apps, so the relay can't read the address from the real device. Android logs it instead. When an app connects, the Bluetooth service writes a line such as `clientConnect() - address=XX:XX:XX:XX:XX:XX, addressType=0`, and `--address auto` takes the most recent public address from those lines.

## Indications are forwarded as indications

A client chooses between notifications and indications when it writes the CCCD descriptor. Bumble sends a value only in the mode that the client chose. An app that writes `0x0002` (indications only) never receives a value that the relay sends as a notification. The relay therefore sends every value from the real device both ways, and Bumble delivers it in the mode that each subscriber chose.

## Phone-key apps

The relay was built to run a car's phone-key app in the emulator, and it works with Tesla's app. The protocol is plain GATT. All of its security is in the app's own end-to-end cryptography, so the relay forwards bytes that it can't read or forge. The car checks the app's key, not the radio that carries the messages.

In testing, Tesla's app connected to the car's saved public address without scanning, which is why `--address auto` exists. The phone key was already enrolled. The relay doesn't add keys and sends no messages of its own.

Walk-up unlocking measures the distance to the Mac, not to the emulator. A car that measures distance with UWB can't unlock on approach through any emulator. Actions that the app starts over Bluetooth still work.

Relaying adds a few milliseconds. In 2022, NCC Group showed that Tesla's phone key works through a Bluetooth relay, and Tesla replied that relaying is a known limitation of passive entry ([NCC Group advisory](https://www.nccgroup.com/us/research-blog/technical-advisory-tesla-ble-phone-as-a-key-passive-entry-vulnerable-to-relay-attacks/)). This tool relays your own app to your own car, on one desk.

## Good uses

The relay works with any device that doesn't require Bluetooth pairing. Some uses:

- Run an Android-only companion app on a Mac. Examples include apps for lights, scales, printers, e-bikes, and scooters.
- Develop the Android side of a Bluetooth project against your real ESP32, nRF52, or Pico W firmware, without a phone.
- Run UI tests against real devices on a Mac CI machine instead of a phone farm.
- Use apps for the standard sensor profiles, such as heart rate, cycling power, speed and cadence, and smart trainers that use FTMS.
- Debug your own devices. Every write and indication passes through one Python file, where you can log, delay, drop, or replay it.
- Keep an old app working with its device after the phone that ran it is gone.

## Limits

- The relay works above the link layer, so it can't carry Bluetooth pairing or link-layer encryption. A device that requires bonding doesn't work. A characteristic that returns *Insufficient Encryption* stays unreadable through the relay.
- The relay supports Bluetooth LE only. macOS gives apps no access to Bluetooth Classic.
- The relay serves one real device and one app connection at a time.
- The mirror repeats the device's advertisement as it was at startup. Beacons whose advertisement data changes over time, such as temperature tags, show stale values.
