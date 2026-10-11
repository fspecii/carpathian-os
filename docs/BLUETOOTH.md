# Desktop Bluetooth runtime

Settings uses BlueZ through `bluetoothctl`. Desktop installation explicitly
requires `bluez` and `bluez-openrc`, including when APKs are supplied offline.
Before provisioning the desktop, installation verifies the CLI, executable
`/usr/lib/bluetooth/bluetoothd`, and `/etc/init.d/bluetooth`. Blueman is not
required by the current Settings command adapter.

These checks establish package composition, not a working adapter or pairing.
They do not start or enable services, change adapter power, replace pairing
agents, or migrate existing Bluetooth configuration. The original fresh x86
installer provisions the Bluetooth service; independent installations retain
existing service and adapter ownership.

Native acceptance remains required: cold-boot an ordinary fresh account, verify
the system D-Bus `org.bluez` owner and actual adapter status, and exercise GUI
power/error/retry behavior. Pair a keyboard requiring a genuine passkey and a
headset with the intended agent, test cancellation and failure, then verify
reconnect after reboot/resume and headset playback/capture/profile changes.
CLI and package fixtures do not qualify hardware, authentication-agent behavior,
wireless range, audio profiles, or persistence across installed-session relogin.
