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


Settings routes nearby-device setup to the installed `blueman-manager` GUI.
Choose the device there and use Pair; its native agent handles PINs, passkeys,
confirmation and cancellation. Pairing and Trust remain separate user actions.
Settings no longer chains noninteractive pair/trust/connect commands. Desktop
packaging requires `blueman`, `blueman-manager` and `blueman-applet`; the existing
hardware-dependent applet lifecycle remains responsible for session ownership.

This integration still needs installed Alpine GUI acceptance and a real pairing
journey. Verify one agent in the ordinary session, actionable confirmation
notifications, cancellation and keyboard passkey entry before claiming pairing
works. Package and launch fixtures do not prove radio or authentication behavior.


Blueman 2.4.6 numeric input uses GtkEditable's insert-text signal. On the tested
Alpine binding stack, both direct text injection and actual keyboard input
trigger a GObject critical in its in/out position marshaling. The distribution
compatibility installer replaces only the known numeric filter with validated
changed handling, accepting ASCII digits and retaining alphanumeric PIN behavior.
Unknown, partial or duplicated source shapes fail installation for review. The
adaptation retains GPL-2.0-or-later licensing and does not suppress diagnostics.

A strict native ordinary-user private-Xvfb probe passed typed input, backspace,
replacement, invalid text and Unicode rejection, maximum length, accept/cancel
and alphanumeric PIN behavior after patching. Its requester and notification
transport were fixtures; it does not establish BlueZ registration, notification
actions or over-the-air pairing. The APK post-commit hook reapplies the adaptation after package replacement.
A persistent repair marker makes Software Update show compatibility failures,
including when no newer packages are available. Native APK lifecycle and actual
installed-session pairing remain release gates for this candidate.
