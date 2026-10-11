# Desktop networking runtime

Settings uses NetworkManager through `nmcli`. Desktop installation explicitly
requires `networkmanager`, `networkmanager-openrc`, `networkmanager-cli`, and
`networkmanager-wifi`, including when APKs are supplied offline. Installation
checks the CLI, executable daemon, and OpenRC service file before provisioning
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
