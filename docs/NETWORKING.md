# Desktop networking runtime

Settings uses NetworkManager through `nmcli`. Desktop installation explicitly
requires `networkmanager`, `networkmanager-openrc`, `networkmanager-cli`,
`networkmanager-wifi`, and `network-manager-applet`, including when APKs are supplied offline. Installation
checks the CLI, GUI connection editor, executable daemon, and OpenRC service file before provisioning
the desktop. Wi-Fi backend selection remains with Alpine's `nm-wifi-backend`
dependency and any existing wpa_supplicant or iwd configuration.

These checks establish package composition, not connectivity. They do not start
services, change `/etc/network/interfaces`, or migrate custom networking. The
fresh x86 installer inherits NetworkManager service enablement and loopback-only
ifupdown configuration from its original installer provisioning. Existing wired,
static, bridge, VLAN, and remote-access configurations remain owner-managed;
activating a second DHCP or DNS manager requires a deliberate migration.

Native acceptance remains required: cold-boot a fresh disposable x86 installation,
verify NetworkManager owns wired DHCP and DNS without a competing interface
manager, reconnect through Settings as the ordinary user, and verify reboot
autoconnect. Actual wireless association requires suitable Wi-Fi hardware or a
separate simulated wireless fixture. Package checks alone do not qualify Wi-Fi,
VPN support, or custom-network migration. ARM qualification is separate.


Settings identifies saved wireless profiles by UUID and reads their actual SSID;
a renamed profile does not change the nearby network's identity. Known networks
provides exact-profile Connect, Configure and Forget actions. Configure opens
`nm-connection-editor --edit=UUID` for password, IP and other settings. When
multiple profiles share an SSID, choose the intended profile in Known networks.
Editor launch checks and status queries run outside the GTK main thread.

Profile queries and an installed editor launch passed under an ordinary account
in a disposable Alpine VM. This does not qualify authorized editing: a private
`su`/D-Bus session can lack active-session permissions and display disabled
controls. Validate Save and persistence in a genuine active local LightDM session
with the normal authentication agent, then qualify real wireless association.
Do not grant broad permissions merely to make an isolated probe succeed.
