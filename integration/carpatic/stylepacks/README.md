# Style packs: Zen and Kylin

Two complete desktop looks on top of the configurator's profile/theme registry. A **style pack** is data plus two small programs, no fork of anything:

| | Zen (`zen`) | Kylin (`kylin`) |
|---|---|---|
| Inspired by | Zorin OS (default Windows-like layout) | the UKUI 4 desktop of Kylin / openKylin (the author's LinPad design spec) |
| Themes | `zen-light`, `zen-dark` (Zorin-blue palette, Inter) | `kylin-light`, `kylin-dark` (KGray ramp, daybreak blue, Noto Sans) |
| Taskbar | tint2 `zen-bottom`: 48 px, icon-only tasks, rounded hover tiles, accent line under running apps, tray, two-line clock, show-desktop strip | tint2 `kylin-bottom`: 48 px, start / search / task-view tiles, grey indicator, accent indicator on the focused app, `HH:mm Weekday` + `yyyy/MM/dd` clock, 17 px show-desktop strip |
| Start menu | `carpatic-startmenu --skin zen`: search, Pinned / All apps / Recent, category menu, Places, Settings, Software, Lock / Sleep / Power | `--skin kylin`: 312 px app list with search + category grouping, Favorites / Recent grid (88x100 tiles), 56 px side bar (user, computer, settings, lock, power) |
| Notifications / quick settings | dunst top-right, 360 px, radius 15; clock opens `carpatic-flyout calendar` | dunst top-right, 374 px, radius 8; `carpatic-sidebar` (Super+A, clock): 4-column toggle grid, sliders, notification history |
| Windows | dwm radius 15, circular `gnome` buttons on the right | dwm radius 12, flat `windows` buttons (red close), a `kylin` style is requested in NEEDS.md |
| Optional data packs | `zorin-gtk` (all 8 accents x light/dark), `zorin-icons`, `zorin-icons-more` | `ukui-gtk`, `ukui-icons` (icons + `dark-sense` cursor) |
| Keys | Super opens the menu, Super+A all apps, Super+E/D/L, Alt+Tab, snap with Super+arrows | Super opens the menu, Super+A sidebar, Super+S search, Super+I settings, Super+Tab task view, Super+E/D/L |

## Use it
```
carpatic-stylepack apply zen            # or: kylin ; light/dark: `apply zen dark`; --packs also downloads the optional GTK/icon packages
carpatic-stylepack mode toggle          # light <-> dark inside the pack
carpatic-stylepack accent purple        # Zen: blue green grey orange purple red yellow brown | default
carpatic-profile set zen                # the registry way (also what Settings > Style does); carpatic-theme set zen-dark picks the palette
carpatic-pack install zorin-gtk zorin-icons   # optional data packs, pinned + sha256, ~/.local/share, no root
carpatic-stylepack list | status zen
```
Settings > Style shows both packs next to the built-in styles (glyph, name, one-line description, live preview with a rounded icon taskbar).
Without the optional packs the packs still look right: adw-gtk3 is recoloured with the pack's palette and Papirus icons are used.

## How it plugs in (the registry contract)
`stylepacks/install.sh` copies, per pack: `profile/<id>.conf` + `.keys` -> `configurator/profiles/`, `themes/<id>-{light,dark}/` -> `configurator/themes/`, `tint2/*.tpl` ->
`configurator/templates/tint2/` (rendered by `carpatic-apply`'s glob), the catalogue `packs.list` -> `configurator/packs.d/stylepacks.list` and the helpers to `/usr/local/bin`.
The profile marks itself with `STYLEPACK=<id>`; `LAUNCHER=<id>` makes `carpatic-launch` run the pack's start menu; `PACKS="..."` lists the optional data packages (`carpatic-pack style <id>`);
`CORNER_RADIUS INNER_GAP OUTER_GAP NOTIFY_* TITLEBAR_STYLE` are the window-look defaults the desktop/configurator agents already read. See NEEDS.md for the three small hooks added to configurator/.

## Files
`zen/ kylin/` (profile, themes, tint2 template, assets, tokens) | `bin/carpatic-startmenu` | `bin/carpatic-sidebar` | `bin/carpatic-taskpreview` | `bin/carpatic-stylepack` | `lib/carpatic_stylekit.py`
| `share/make-wallpapers.py` (original procedural wallpapers) | `packs.list` | `RESEARCH.md` (what exists upstream, licence table) | `NEEDS.md` | `tests/`.

## Checklist: what matches the original, what cannot (no compositor, no GNOME / KDE shell)
VERIFIED = run in the VM (golden-full clone, `tests/vm-e2e.sh`: 28 checks pass; screenshots `docs/screenshots/stylepack-*.png`, side-by-side `ref-stylepack-kylin.png`, `ref-stylepack-zen.png`) and looked at. HOST = rendered / tested on the host only. NO = cannot on dwm + X without a compositor. OPEN = possible, not built.

### Zen vs Zorin OS
| Attribute | Zorin | Carpathian | Status |
|---|---|---|---|
| Taskbar | 48 px bottom panel, grouped icons, pinned, indicator, previews, show-desktop strip | tint2 48 px, icon-only tasks (one per window), pinned launchers, accent line under tasks, tray, two-line clock | VERIFIED; grouping NO; show-desktop strip: tint2's `button` item does NOT render in the VM (same as the configurator saw), so it is not shown (the `button` lines stay in the template, harmless) |
| Window previews on hover | live thumbnails | card (rounded, title, icon, thumbnail of the last time the window had focus, click raises, cross closes); starts from an invisible tint2 `execp` item | VERIFIED (thumbnail of a terminal seen); covered windows cannot be captured live: NO |
| Start menu | Zorin Menu: list + categories left, user / places / settings / power right | same structure, original GTK, Pinned / All / Recent, categories, search, keyboard (Super, Esc, arrows, Enter, Tab), pin/unpin by right click | VERIFIED (open, Esc closes) |
| GTK theme / icons | Zorin GTK 8 accents, Zorin icons | real themes as optional packs, installed in the VM with `apply zen --packs` (fetch + sha256 OK), Thunar and the whole bar picked them up | VERIFIED; `carpatic-stylepack accent` host-tested only |
| Window look | 15 px radius, circular buttons, soft shadow, 1 px outline | dwm radius 15 live, `gnome` circular buttons; shadow and outline NO | VERIFIED (radius/buttons), shadow NO |
| Fonts | Inter | Inter 10 | VERIFIED |
| Notifications | GNOME banners top-centre | dunst top-right radius 15; compact bubble (dunst `width` is a maximum; a fixed width needs a template option, see NEEDS) | VERIFIED; differs in size/position |
| Calendar / quick settings | GNOME popovers | the configurator's `carpatic-flyout calendar|quick` | not run by me |
| Layout variants (macOS-like, GNOME-like) | Zorin Appearance | not built | OPEN |
| Blur, translucency, shadows, animations | yes | NO without a compositor | NO |

### Kylin vs UKUI 4 (reference: LinPad's native Kylin style, `ref-stylepack-kylin.png`)
Differences read off the sheet: reference panel is frosted with a rounded tile behind every task and a pill indicator, windows have shadows and a native-looking file manager; ours is a solid panel, a 3 px line indicator, Thunar, no shadows. The start glyph (7 dots), search and task-view icons now follow the reference; wallpaper is original on purpose.
| Attribute | UKUI | Carpathian | Status |
|---|---|---|---|
| Panel | 48 px, frosted, start / search / task view, tasks, tray, clock, show-desktop | solid 48 px, same items (separator omitted), two-line clock `HH:mm Thu` / `yyyy/MM/dd` | VERIFIED; blur NO; show-desktop strip not rendered (tint2 `button`) |
| Task indicator | pill 8 / 16 px | 3 px bottom line | PARTLY |
| Start menu | 766x688, 312 / ~396 / 56, radius 12 | same geometry, categories toggle, favourites / recent grid, side bar (user, computer, settings, lock, power) | VERIFIED (light and dark) |
| Sidebar | quick settings 396 + notification centre | one 396 px column: toggles (Dark mode switches the pack to dark and back), brightness / volume sliders only when hardware tools exist, notification history, `Clear all` | VERIFIED (light and dark); Wi-Fi / Bluetooth tiles hidden in the VM (no hardware), merged surfaces, no slide animation |
| Notification | 374 px card, radius 8 | dunst top-right 374 px max, radius 8 | VERIFIED |
| Window decoration | 12 px radius, 30 px buttons, red close | radius 12, `windows` buttons; `kylin` style requested from the desktop agent | VERIFIED; shadow NO |
| GTK / icons / cursor | ukui-white/black, ukui icons, dark-sense | optional packs, installed and used in the VM (icons visible everywhere) | VERIFIED; cursor only when the pack is present |
| Qt apps | UKUI Qt style | Kvantum via the configurator | not checked |
| Task view | KWin multitask effect | the tile starts the Alt+Tab switcher | NO |
| Fonts | FounderType | Noto Sans | stand-in |
| Widgets | UKUI sidebar widgets | tokens for the widgets agent (`kylin/tokens.toml`) | OPEN (widgets agent) |

### Known issues found in the VM (not caused by the packs)
* Switching dark <-> light while Thunar is open leaves Thunar half dark (running GTK apps do not repaint fully): configurator/GTK theme owners. The e2e restarts apps after each switch.
* The configurator's Settings page and the new settings app both list the packs; the new app uses `profiles/<id>.preview-<mode>.png` thumbnails (ours are made from the VM screenshots by `share/make-previews.py`).

## Tests
`sh stylepacks/tests/test-stylepacks.sh` (host, about 5 s): registry, profiles, palettes and contrast, wallpapers, templates, GTK-program logic, licence rules, end-to-end apply into a fake HOME.
`stylepacks/tests/vm-e2e.sh` (VM): deploy, switch to every pack in light and dark, start menu, sidebar, notification, hover, screenshots, back to Windows.
