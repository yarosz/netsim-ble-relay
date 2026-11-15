# Why the Mac's built-in radio can't be a raw HCI controller

To give the Android emulator real Bluetooth, the usual tools hand it a raw HCI controller. On a Mac's built-in Bluetooth, macOS closes every route to raw HCI. The tests below ran on macOS 26.7 (build 25G220), on an Apple M3 Pro with a Broadcom BCM4388 controller on PCIe, with System Integrity Protection on.

| Route | Result | Evidence |
|---|---|---|
| Bumble's `usb:` transport | Doesn't work | The controller is on PCIe, not USB. `bumble-controller-info usb:0` reports that it finds no device. |
| Bumble's `hci-socket` transport | Doesn't work | The transport needs `BTPROTO_HCI` sockets, which only Linux has. |
| The private IOBluetooth functions `BluetoothHCISendRawCommand`, `BluetoothHCISendRawACLData`, and `BluetoothHCIRequestCreate` | Doesn't work | [sendhci](https://github.com/unixb0y/sendhci) and InternalBlue's macOS port used these functions up to macOS Catalina. The symbols still exist, but in a running process each function disassembles to `mov w0, #0; ret`. Each one returns success and does nothing. |
| `IOServiceOpen` on `IOBluetoothHCIController` with type 0, which opens the kernel's `IOBluetoothHCIUserClient` | Doesn't work with SIP and AMFI on | IOBluetooth's `BluetoothHCIDispatchUserClientRoutine` still makes this call. From a normal process, the call returns `0xe00002c7` (`kIOReturnUnsupported`). Only `bluetoothd` holds this user client, and `bluetoothd` has the `com.apple.bluetooth.iokit-user-access` entitlement. AMFI kills a self-signed binary that claims the entitlement at launch. |
| Turn off SIP and AMFI, stop `bluetoothd`, and reverse-engineer the user client | Not tried | This lowers security on the whole Mac and removes the Mac's own Bluetooth while it runs. The user client's interface is undocumented. |

The 2020 research on this interface describes IOBluetooth as a direct client of the kernel driver ([Toldo, Classen, and Hollick, WiSec 2020](https://arxiv.org/abs/2005.14606)). On macOS 26, IOBluetooth logs "Loading Shim Coordinator" and talks to `bluetoothd` over XPC instead.

A raw channel would still conflict with `bluetoothd`. The daemon keeps control of the controller for the Mac's own devices, such as a mouse, a keyboard, and AirPods. Android's host stack expects sole control of the controller, starting with an HCI reset.

For these reasons, the relay works at the GATT layer through CoreBluetooth and doesn't use HCI.
