# Why the Mac's built-in radio can't be a raw HCI controller

Tested on macOS 26.7 (25G220), Apple M3 Pro, built-in Broadcom BCM4388 over PCIe, SIP enabled.

The usual way to give the Android emulator real Bluetooth is to hand it a raw HCI controller. On a Mac's built-in radio every route to that is closed.

| Route | Result | Evidence |
|---|---|---|
| Bumble `usb:` transport | Dead | The radio is on PCIe, not USB. `bumble-controller-info usb:0` says device not found. |
| Bumble `hci-socket` | Dead | Linux-only (`BTPROTO_HCI`). |
| Private IOBluetooth `BluetoothHCISendRawCommand` / `BluetoothHCISendRawACLData` / `BluetoothHCIRequestCreate` (used by [sendhci](https://github.com/unixb0y/sendhci) and InternalBlue's macOS port up to Catalina) | Dead | The symbols still exist, but in a running process each disassembles to `mov w0, #0; ret`. They return success and do nothing. |
| Open the kernel's `IOBluetoothHCIUserClient` directly (`IOServiceOpen` on `IOBluetoothHCIController`, type 0, as IOBluetooth's surviving `BluetoothHCIDispatchUserClientRoutine` does) | Dead with SIP/AMFI on | Returns `0xe00002c7` (kIOReturnUnsupported) for a normal process. Only `bluetoothd` holds this client, and it has the `com.apple.bluetooth.iokit-user-access` entitlement. A self-signed binary claiming that entitlement is SIGKILLed at launch by AMFI. |
| Disable SIP and AMFI, stop `bluetoothd`, reverse-engineer the user client | Not attempted | Weakens security on the whole machine and takes away the Mac's own Bluetooth while it runs. The private interface is undocumented. |

Also, since macOS 26 IOBluetooth logs "Loading Shim Coordinator" and talks to `bluetoothd` over XPC, rather than to the kernel driver as described in the 2020 research ([Toldo, Classen, Hollick, WiSec 2020](https://arxiv.org/abs/2005.14606)).

Even if a raw channel existed, `bluetoothd` keeps owning the controller (your mouse, keyboard and AirPods), and Android's host stack expects sole control (HCI Reset, event masks, scan and connection state). The two would conflict.

So this project works at the GATT layer through CoreBluetooth, the supported API, and leaves HCI alone.
