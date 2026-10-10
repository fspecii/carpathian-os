# Carpatic Settings

The system settings app of Carpatic OS (GTK3, Python): `carpatic-settings [page]`, Super+F2. The layout follows macOS System Settings (Ventura/Sonoma/Sequoia):
a sidebar with a search field and grouped, colour-tiled rows, and a content area of titled grouped cards (label, secondary text, control on the right).
Colours, accent, fonts and radii come from the active Carpatic theme and `docs/DESIGN-SYSTEM.md` (4 px grid, radii 4/6/10/14, type 11/12/14/16/20/24/32); light and dark follow the theme live.

![Appearance](../docs/screenshots/settings-appearance-dark.png)

## Information architecture
See `docs/SETTINGS-IA.md`: Appearance = look, Desktop & Dock = behaviour, one home per setting (a test fails otherwise).

## Pages and what they really talk to
Every page is built when first opened. A row or whole page is **hidden** when the tool or hardware behind it is missing (no dead controls); pages show a plain-English banner when a service is stopped.

| Page | Backend | State |
|---|---|---|
| Wi-Fi | NetworkManager (`nmcli`): radio switch, scan, join with password dialog, disconnect, saved networks, forget | real; hidden without nmcli or a wireless interface |
| Bluetooth | bluez (`bluetoothctl`): power, paired devices, connect/disconnect/forget, scan + pair | real; hidden without an adapter |
| Network | `ip -j addr/route`, `/etc/resolv.conf`, NetworkManager VPN profiles (`nmcli con up/down`), per-interface detail page | real (VPN rows only with nmcli) |
| Sound | PipeWire (`wpctl`): output/input volume, mute, default device, per-app volumes | real; banner when no sound server |
| Notifications | `dunstctl`: Do Not Disturb, history count/clear, test notification | real; hidden without dunst |
| General | Startup and screensaver (the motion component's page, embedded), login items (`~/.config/autostart`), Welcome | real |
| Appearance | LOOK: `carpatic-theme`, `-profile`, `-appearance`, `-pack`: desktop style preset gallery, light/dark, accent, colour theme gallery with live apply (the theme picker's renderer) + Browse themes (opens the keyboard picker) + app colours, wallpaper link, fonts, icon packs, cursors, window buttons, corners/borders/gaps | real |
| Accessibility | `carpatic-a11y` | real |
| Control Centre | `carpatic-panel` keys (tray, clock, previews) + `carpatic-flyout quick|calendar` | real; hidden without carpatic-panel |
| Desktop & Dock | BEHAVIOUR: bar/dock design gallery and settings (`carpatic-panel`), window layout and drag behaviour (`carpatic-layout`, `carpatic-appearance set drag-tiled`), widgets (embedded widgets page) | real; taskbar/dock rows (design, position, size, icon size, auto-hide, labels, indicator, buttons) come from `carpatic-panel options`/`get` and are hidden without it |
| Displays | `xrandr` (resolution, refresh, rotation, primary), `carpatic-display` (extend/mirror), scale (`carpatic-appearance`), brightness (`carpatic-power`), Night Light (`carpatic-nightlight` with sct/redshift/gammastep) | real |
| Wallpaper | the wallpapers component's `WallpaperBrowser` (library, Wallhaven, colours); built-in gallery as fallback | real |
| Battery | `carpatic-power`: battery, health, charge limit, profile, sleep, hibernate readiness/setup | real; hidden without carpatic-power |
| Lock Screen | `carpatic-lockscreen` (new), `carpatic-lock` | real; persistence needs the carpatic-idle change in NEEDS.md |
| Keyboard | `carpatic-keyboard` (new: layouts, switch key, Caps Lock, repeat), shortcut list from `carpatic-keys` | real |
| Mouse / Trackpad | `carpatic-mouse` (new), `carpatic-touchpad` | real; Trackpad hidden without a touchpad, Mouse shows "No mouse found" |
| Printers & Scanners | CUPS (`lpstat`, `lpoptions`, `lpadmin`, `system-config-printer`) | real; scanners are not covered (no SANE page yet) |
| Users & Groups | `/etc/passwd`, `adduser`/`deluser`/`chpasswd`/`usermod` through polkit | real, not yet run on a VM with several users |
| Language & Region | `carpatic-input-method`; system language shown read-only | input methods real; no region/format settings (no backend) |
| Date & Time | time zone (`/etc/localtime`), NTP service (chrony/ntpd through OpenRC), manual set, month view from the widgets date maths | real; 24-hour clock has no backend and is not shown |
| Privacy & Security | OpenRC `nftables` and `sshd`, `lsblk` (encryption), SecureBoot efivar, Flatpak permissions | real |
| Software Update | `carpatic-update`, `carpatic-rollback` (restore points need Btrfs) | real |
| Default Apps | `xdg-mime` + .desktop files | real |
| Storage | `statvfs` over `/proc/mounts`, `du` of the home folders (background), Trash, caches | real |
| About | `/etc/os-release`, `/proc`, `lspci`, rename the computer (polkit) | real |

Deep links: `carpatic-settings wifi`, `... displays --anchor night` (scrolls to the row and flashes it); old names (`style`, `colours`, `fonts`, `icons`, `cursors`, `touchpad`, `display`, `access`, `startup`, `widgets`, `wallpapers`, `updates`) still work.

## Component library (`lib/cset/ui.py`, `theme.py`, `app.py`, `search.py`)
`SettingsWindow` (sidebar with user card, sticky toolbar with back and sidebar buttons, Ctrl+B, auto-hide of the sidebar for pages that cannot shrink, navigation stack, sizing from the work area: 880x620, at most 90 % of the screen, minimum 720x480, last size remembered),
`Page` (id, title, icon, colour, group, `entries` for the search), `PageBuilder`/`GroupCard`/`PageView`/`Clamp`, rows `SwitchRow PopupRow SliderRow SpinRow(Stepper) EntryRow ButtonRow NavRow InfoRow StatusRow ColorRow ProgressRow CustomRow`,
`Gallery`, `Segmented`, `PopupButton`, `icon_tile`, dialogs `confirm`/`ask_text`, `SearchIndex` (GTK-free). Every colour, radius and size is in `theme.py` (one stylesheet, generated from the theme palette). Rules: one icon per row only when every row of the card has one; secondary text in sentence case, no jargon; sub-pages (`Page.push`) for anything with its own list.

Keyboard: Ctrl+F search, Down from the search jumps to the list, typing in the sidebar starts a search, Enter opens, Alt+Left / Esc go back, Tab and arrows move with a visible 2 px focus ring everywhere, Space/Enter toggle switches. Accessible names are set on every control.
HiDPI: sizes are logical pixels, images are rendered at the monitor scale (`hidpi_image`), the `scale` setting in Displays scales apps.

## No terminals for installs and actions
Long actions run in a **progress sheet inside the app** (`ui.ProgressSheet`, runner in `runner.py`; the same sheet is available to launchers as `carpatic-progress [--title T] [--root] -- COMMAND`): heading, live status line and percentage (curl's `NN%`, apk's `(3/10) Installing x`, `progress:` lines), Cancel, a friendly error with Try again and Show details. Administrator rights: root runs directly; with a polkit agent in the session `pkexec` asks in the agent's own dialog (friendly text from `share/org.carpatic.settings.policy`); without an agent doas/sudo is used and Settings asks for the password in its own dialog (fed to a pty, never on a command line, forgotten after use).
Audit of every place that used to or could open a terminal (grep for `carpatic-term`, `st -e`, `xterm -e`, `doas`, `sudo`, `pkexec` in GUI code):

| Where | Before | Now |
|---|---|---|
| `configurator/bin/carpatic-pack install` (icon, cursor, font, GTK packs; "More to install", "Get the full look") | apk packs opened `carpatic-term -e doas apk add` behind the window | no terminal ever: root installs, in a terminal it uses doas, otherwise it fails with "needs administrator rights"; Settings runs it through the progress sheet (pkexec or own password dialog) |
| Settings > Software Update (install, restore point, restore) | toolbar text only | progress sheet (pkexec) |
| Settings > Language & Region (add a language, ~100 MB) | toolbar text only | progress sheet |
| `compat/share/carpatic-compat-open.desktop` (open an AppImage or .deb) | `st -e sh -c 'carpatic-compat install ...; read'` | `carpatic-progress ... -- carpatic-compat install %f` |
| Welcome > language (`carpatic-input-method install`) | polkit dialog, no progress, no terminal | unchanged (no terminal); progress sheet is a request in NEEDS.md (the file has another owner's uncommitted work) |
| Theme picker, panel and flyouts, Store GUI, Quick Look, widgets | no terminal | no terminal (checked by the test below) |
| `compat/share/carpatic-compat.desktop` (compatibility box shell), `carpatic-mail.desktop` (alpine), `geek/share/menu.toml` (power-user menu: nmtui, btop, `carpatic install dev ...`, updates) | terminal | intentional: the terminal IS the product there; documented in `ALLOWED` of `tests/test_noterminal.py` |

`tests/test_noterminal.py` fails when GUI code spawns a terminal (static scan of the GUI paths), and runs the real `carpatic-pack` with fake `carpatic-term`/`doas`/`xterm` to prove an apk pack without root and without a tty never starts one. `tests/test_ui.py::SheetTests` covers the sheet (progress, friendly failure + Try again, pkexec path, password dialog with a wrong then a right password, cancel). `vm-e2e.sh packs` installs an icon pack and a font pack for real in a VM through the sheet and the polkit dialog and checks no terminal window appears.

## Keeping the bar alive
Every Settings action that can touch the bar (style, theme, scale, icons, fonts, window look, panel keys, resolution) is followed 5 s later by a check (`SettingsWindow.ensure_bar`): if the bar of the current profile (panel, tint2) is not running it is restarted once with `carpatic-session restart`. Desktop & Dock also has a "Restart the bar" button. `tests/guest-bar.sh` (VM, `vm-e2e.sh bar`) runs about 100 of the commands Settings issues and checks after each that dwm and exactly one visible bar are alive.
Found while doing this: the panel's **left/right position is broken for every design except the macOS and Ubuntu menu bars** (the bar window ends up in the middle of the screen at x=626 and dwm shows its own bar too, because dwm's `isaltbar` only accepts wide docks, see panel/NEEDS.md). Settings therefore offers only Top and Bottom, hides Position for the macOS and Ubuntu designs, and shows a "Put the bar back" banner when a side position is already saved.

## Tests
`sh settings/tests/run.sh` (host, no VM): 30 logic tests (search ranking, every parser, the four helper CLIs with a temp HOME) and 17 GTK tests run on a **private Xvfb** at 1280x800 and 1024x768 against fake system tools (`tests/fakebin`):
every page builds, every search entry points at a real row, the window and every page fit the screen (no clipping, nothing wider than the window), navigation, aliases, keyboard handling, light and dark CSS.
Never run Settings on a real desktop from a script: `tests/shot.sh PAGE OUT.png dark|light [--size WxH --sub NAME --query TEXT --anchor ROW]` and `tests/render-all.sh` use `xvfb-run`, unset `WAYLAND_DISPLAY`, set `GDK_BACKEND=x11`, `CSET_DRY=1` (no command that changes the system runs; they are appended to `$CSET_DRY_LOG`) and `CARPATIC_FORCE=1`.
The app itself refuses to start outside a Carpatic session (`CARPATIC_SESSION`, `/usr/share/carpatic`, or `CARPATIC_FORCE=1`).
`tests/refsheet.py` builds the reference sheets `docs/screenshots/ref-settings-*.png` (no macOS screenshots are available offline; the sheet compares measurable attributes).

## VM end to end
`settings/tests/vm-e2e.sh [shots]` (needs a VM clone running the dwm session): open time, window fits the screen, search + keyboard, sub pages, live theme change, Users & Groups dialogs (add, make admin, delete), Night Light switch (gamma really changes with redshift), Change password dialog (mismatch and short passwords refused, valid change applied), optional screenshots.

## Install
`sh settings/install.sh` (as root) or via the packages; the launcher in `configurator/bin/carpatic-settings` picks it up. Requirements and requests to other components: `NEEDS.md`.
