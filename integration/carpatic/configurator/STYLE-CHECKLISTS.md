# "Looks like the real one": checklists for the three flagship styles

Rules: original artwork only (no Apple/Microsoft/Canonical imagery, logos, wallpapers or proprietary fonts: SF Pro, Segoe UI and
SF Symbols are not shipped). Open stand-ins are named below. dwm on X11 runs here WITHOUT a compositor, so blur, drop shadows, animations,
translucency and real rounded dock/menu corners are not available (marked **no-compositor**). Status column: DONE (verified in the VM, see
docs/screenshots/style-*.png), PARTLY, NO (cannot be done here), OPEN (possible, not built).

## Verification status (VM run 2026-10-08, golden-desktop2 clone, VM_RAM 2048)
VERIFIED on screen or by command in the VM (screenshots in docs/screenshots/style-*-{before,after}-{dark,light}-*.png, 18 before / 30 after; read: macOS dark desktop/launcher/notification, Ubuntu dark desktop/quick, Windows dark desktop/start/quick/calendar, Windows light notification):
- Per-style defaults apply: macOS blue accent + dock + top bar, Ubuntu orange accent (window border, selection, dock icon), Windows blue accent and 48 px taskbar; notification card per style (macOS top-right, Windows bottom-right with app name, summary and body, Ubuntu top-centre in config).
- `carpatic-flyout start`: keyboard grab (typing filters apps), Esc, click outside and a second call all close it; `quick`: DND + dark-mode tiles, Wi-Fi/Bluetooth/volume/brightness hidden because the VM has none of the tools; `calendar`: month + empty notification list.
- Settings > Colours "Also colour" checkboxes: five boxes, unchecking Terminal and Qt wrote `ALSO="editors browser cli"` and a following theme change skipped kitty but wrote btop.
- Nothing / Nothing Light: Noto Sans Mono body, Doto bar clock (dot-matrix, visible in the taskbar), kora-pgrey icons, neutral grey title bar (#e7e7e7) with the red accent only on the border (docs/screenshots/configurator-nothing-light-desktop.png).
- Packs on the VM: font-doto, font-ubuntu, font-selawik, kora, fluent-icons install with sha256 checks (2-8 s each); fluent-icons initially "installed" nothing because of a wrong case label, now fixed and `carpatic-pack` refuses to report success when no theme appeared.
- Window look controls: `carpatic-appearance look zen` -> corner_radius 14, gaps 20/24; `set corners 12 border-width 3` reloaded by dwm.
- `carpatic-apply --live`: full apply 970 ms, `carpatic-theme set` (now --live) 150-380 ms for a theme change, 100-130 ms for an accent change in the VM (target was < 250 ms: met for accent and most theme changes; the slowest sample was 380 ms).
- stylepacks host tests: 97 checks pass.
NOT verified: Launchpad grid on F4, dock running-indicator dots with real running apps, Ubuntu dock "Show applications" button (never built, see NEEDS), the Ubuntu/macOS light after-shots and the remaining unopened after-shots, Windows Start pinned apps launching, `carpatic-pack style` as one command (the individual packs were installed), Fluent GTK theme (not built), Selawik/Ubuntu font actually used by the UI (installed, not screenshotted), WhiteSur/Yaru/Qogir installs on this run, quick-settings tiles with real hardware.

## macOS
| Attribute | The real thing | Carpathian | Status |
|---|---|---|---|
| Top bar | 24-28 px, light, translucent, app name bold, menus, status icons + clock right | 28 px light bar (`surface`), logo + bold active-app name left, tray + "Thu 8 Oct  10:59" right | DONE (opaque: **no-compositor**) |
| Global menu | File Edit View ... of the focused app | not possible without per-app D-Bus menu export (dead labels would be worse than none) | NO |
| Dock | centred, 14 px rounded, 52-64 px icons, running dots | centred 14 px dock, 52 px Qogir icons, running indicator under open apps, no magnification | DONE / magnification NO |
| Fonts | SF Pro (UI), SF Mono | Inter 10 / JetBrains Mono | DONE (stand-in) |
| GTK / icons / cursor | macOS controls, folder-blue icons | WhiteSur GTK (0.4 MB, MIT) + Qogir icons + capitaine cursors, one click via `carpatic-pack style macos` | DONE |
| Window | traffic lights left, 10-12 px corners, soft shadow, title centred | `macos` button style, corner_radius 10, centred title; shadow **no-compositor** | DONE / shadow NO |
| Gaps | windows float, no tiling gaps | float layout; zen gaps when tiling (outer 12 / inner 10) | DONE |
| Launcher | Spotlight: centred search field, results below, rounded | rofi Spotlight (top third, 640 px, radius 14) | DONE |
| Launchpad | full-screen icon grid | fullscreen rofi grid on F4 / Super+Shift+Space | DONE (no blur) |
| Mission Control | window overview | not feasible in dwm without window thumbnails | NO |
| Notifications | top-right rounded card, app icon, bold title | dunst top-right, 340 px, icon left, bold summary | DONE |
| Lock screen | wallpaper + clock + avatar | design agent's lock screen (not owned here) | n/a |
| Wallpaper | gradient landscape | original design wallpapers (light/dark) | DONE |
| Accent | blue (user can pick) | Glacier blue default for this style | DONE |
| Keys | Cmd = Super, Cmd+Space, Cmd+Q/W/Tab, Cmd+C/V (emulated) | as before | PARTLY (limits in README) |

## Windows 11
| Attribute | The real thing | Carpathian | Status |
|---|---|---|---|
| Taskbar | 48 px, icons centred, Start in the middle group, tray + clock right | 48 px bar, Start + pinned + tasks centred, tray + two-line clock right, 8 px rounded task plates | DONE |
| Fonts | Segoe UI Variable | Selawik (OFL, metric-compatible, pinned 3 files) via pack, Noto Sans fallback | DONE |
| GTK / icons / cursor | Fluent controls, Fluent icons | Fluent icons pack (pinned) + palette-recoloured adw-gtk3 (Fluent GTK needs a sass build: OPEN); Adwaita cursors | PARTLY |
| Window | flat, 8 px corners, buttons right (minimise, maximise, close with red hover) | `windows` button style, corner_radius 8, title left | DONE |
| Start menu | centred popup: search, Pinned grid, Recommended list, user + power | `carpatic-flyout start`: search field, 6x3 pinned grid, Recommended (recent files), power button | DONE (no acrylic blur) |
| Quick settings | Wi-Fi, Bluetooth, volume, brightness tiles | `carpatic-flyout quick` (Win+A, right-click clock): volume and brightness sliders, Wi-Fi/Bluetooth tiles only when NetworkManager / bluez are present | DONE where hardware tools exist |
| Calendar flyout | clock click: month calendar + notifications | `carpatic-flyout calendar` (click clock): month + notification history | DONE |
| Notifications | bottom-right toast with app name | dunst bottom-right, 360 px, app name small above the title | DONE |
| Shortcuts | Win+E/D/L/R/A, Alt+Tab, Alt+F4 | all bound | DONE |
| Wallpaper | bloom | original abstract design wallpapers | DONE |
| Accent | blue | Glacier blue default for this style | DONE |
| Mica / acrylic / snap layouts flyout | translucency, snap bar | **no-compositor**; snap keys (Super+arrows) exist | NO |

## Ubuntu (GNOME)
| Attribute | The real thing | Carpathian | Status |
|---|---|---|---|
| Top panel | 28-32 px dark, Activities left, clock centre, system menu right | 28 px bar, Activities, centred clock, tray + system-menu icon that opens the quick settings | DONE |
| Dock | left, 48-56 px, rounded, active-app dot, running apps | left dock 56 px, 40 px icons, running indicator dot on the left edge, orange | DONE |
| Fonts | Ubuntu | Ubuntu font (UFL 1.0, redistributable, pinned pack) with Cantarell fallback | DONE |
| GTK / icons / cursor | Yaru (orange accent, rounded) | Yaru GTK + Yaru icons (packs, 0.7 + 27 MB) + Adwaita cursors; orange `#e95420` accent default for this style | DONE |
| Window | rounded 8-12 px top, buttons right, headerbar | `gnome` button style, corner_radius 10 | DONE |
| Launcher | Activities: full-screen app grid with search | fullscreen rofi grid | DONE (no blur) |
| System menu | quick-settings pills (Wi-Fi, Bluetooth, volume, brightness, power) | `carpatic-flyout quick` in Yaru dark panel | DONE |
| Notifications | top-centre banner | dunst top-centre, 380 px | DONE |
| Workspaces | dynamic, overview | dwm tags; overview NO | NO |
| Wallpaper | warm gradients | original design wallpapers (warm scene) | DONE |

## What cannot be done without a compositor
Blur/translucency (macOS bar, Win11 Mica, GNOME overview), drop shadows, animations (dock bounce, window open/close, workspace slide),
anti-aliased rounded corners on popups/docks (square mask only; windows get XShape corners from dwm), live window previews.
A compositor (picom) is an opt-in (`~/.config/carpatic/compositor`) and was disabled in the VM because of virtio-gpu artefacts; a future
bare-metal test could enable shadows, blur and real translucency without changing these files.
