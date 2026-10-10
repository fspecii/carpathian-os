# carpatic-panel: taskbars, docks, menu bars and flyouts

One small GTK3 + cairo application that draws every panel-like surface of the desktop from the design tokens:

* **carpatic-panel** (daemon): the bar or dock of the chosen *design*, a window list from EWMH, pinned launchers, tray, clock, indicators.
* **carpatic-flyout** `quick | calendar | start`: Quick Settings, Calendar + notification centre, Start menu (the old script from
  `configurator/bin/carpatic-flyout` is replaced; same CLI).

Everything is drawn by us (cairo + Pango, one glyph set, one spacing grid), so light/dark, accent, radii and fonts always come from the
palette and look identical on every machine. Research and measurements: [RESEARCH.md](RESEARCH.md).

## Designs

Select with `carpatic-panel set design <name>` (applies live) or in Settings. Every option below can be changed per design.

| design | surfaces | notes |
|---|---|---|
| `windows11` | bottom bar 48, centred or left icons, Start, Search, Task view, tray, quick pill, two-line clock, bell with count, show-desktop strip | running indicator: 16x3 accent pill when focused, 6x3 dot otherwise |
| `classic` | bottom bar 40, labelled buttons (160 px), line indicator | Windows 10 feel |
| `macos` | top menu bar 28 (logo, focused app name, status items, clock) + a centred floating dock (radius 18, icons 48, dot indicators) | dock reserves its strip with a strut, menu bar is the dwm bar |
| `ubuntu` | top bar 30 (Activities, centred clock, system pill with power) + left dock 62 (indicator dots, Show applications) | |
| `zorin` | bottom bar 48, Start, grouped apps, focused "ciliora" bar / unfocused dots (zorin-taskbar defaults), thin show-desktop strip | |
| `kylin` | bottom bar 48 (UKUI classic): Start, Search, Task view, divider, apps with 4 px pill indicator (width 8/16), tray, two-line clock | metrics from `upstream-linpad/themes/kylin/DESIGN-SPEC.md` |
| `floating` | one rounded floating bar (radius 16, margin 10): Start, centred apps, quick, clock | elementary / Zorin floating look |
| `minimal` | 30 px top bar: workspace (tag) numbers, focused title, labelled windows, status | tiling users |

Options (`carpatic-panel options`; stored in `~/.config/carpatic/panel.conf`): `design position size icon_size align autohide margin radius
labels grouping clock_format clock_24h date_in_clock show_search show_taskview show_widgets show_desktop tags tray monitors previews indicator
pinned theme`. `auto` / `0` / `-1` mean "the design's default". Invalid values are refused with a plain message and never reach the file.

## Behaviour

* Window list from `_NET_CLIENT_LIST`, matched to desktop entries (StartupWMClass, id, executable), grouped per app or one button per window.
  Click = focus / restore, click on the focused single window = minimise, click on a group cycles, middle click = new window,
  right click = menu (new window, desktop actions, pin/unpin, minimise, maximise, close). Pinned launchers can be dragged to reorder.
  Too many windows: buttons shrink, then a "+N" button lists the rest.
* Hover: tooltip (window title) or a preview card per window with a live screenshot (grabbed from the screen, so only windows currently visible
  have a picture, the others show their icon), click to focus, x or middle click to close.
* Tray: our own XEmbed manager (`_NET_SYSTEM_TRAY_S0`), icons docked into Gtk.Sockets over the bar. dwm releases its tray when a
  panel bar maps; we take it within 20 s at start-up.
* Struts: the main bar is a wide dock-type window named `carpatic-panel` (dwm treats it as the bar and retires its own). Docks are named
  `carpatic-dock-*` and set `_NET_WM_STRUT_PARTIAL` (dwm reserves the strip, desktop/PATCHES.md "secondary docks"). Floating margins are cut away with XShape
  (click-through), anti-aliased only when a compositor exists.
* Published geometry: `$XDG_RUNTIME_DIR/carpatic-panel.json` (surfaces and item rectangles) so flyouts open next to the right button.
* Autohide (`autohide=on`): the bar slides to a 2 px edge strip 0.7 s after the pointer leaves and returns on touch; no strut while on.

## Flyouts

* **Quick Settings** (4 looks: win, mac, ubuntu, kylin): tiles with icon, title, subtitle (network name, connected device) and accent fill when on;
  Wi-Fi, Bluetooth and Power mode drill down (network list with signal bars, password field, saved networks connect directly; Bluetooth device list
  with connect/disconnect; power profile choice; sound output list); volume and brightness sliders (mute button, value, output switch);
  Now Playing (MPRIS, cover art, transport, progress); battery text; settings, lock, power. Controls whose hardware or tool is missing are hidden.
* **Calendar + notification centre** (4 looks): month grid with day-name row, locale first weekday (`LC_TIME`/`LANG`, override in config), optional
  week numbers, today in the accent, selected day, dimmed neighbours, event dots; Prev / Next / Today; agenda for the selected day from
  `~/.local/share/carpatic/calendar/*.ics`, the widgets calendar file and khal/vdirsyncer folders (`~/.calendars`), with simple recurrence;
  quick entry (`Lunch with Ana tomorrow 13:00`, shows what it understood before Enter); notifications from `dunstctl history` grouped by app,
  swipe or x to dismiss, clear all, collapse stacks, Focus (do not disturb).
* **Start menu**: `win` (search, pinned grid, recommended apps and files, All apps A-Z, user/settings/lock/power), `twopane` (Zen and Kylin:
  app list + favourites + side buttons), `launchpad` (macOS and Ubuntu Activities: full-screen grid). Search ranks prefix, word, substring; Enter launches
  the best match or runs the text as a command.
* All flyouts: keyboard (arrows, Tab, Enter, Esc, Backspace for back), one pointer+keyboard grab, close on outside click, toggle by calling again.

## Layout of the code

`lib/carpatic_panel/`: `theme` (palette -> colours), `gfx` (cairo/Pango helpers + 70 glyphs), `kit` (retained-mode nodes, hover/press/focus, scroll groups,
offscreen render), `barview` (bars for all designs), `designs`/`config` (surfaces, options, validation), `tasks` (pure window-list model), `xlib`/`ewmh`
(ctypes X11), `tray`, `preview`, `menu`, `popup`, `panel_app` (daemon), `flyout_quick|cal|start`, `system`/`quickmodel`/`media`/`notes`/`events`/`calmath`
(backends and models without GTK), `placement`, `guard`. `bin/`: the two commands. Run on a host: `panel/tests/xrun.sh panel/bin/carpatic-panel run`.

## Safety

`carpatic-panel run` and `carpatic-flyout` exit immediately outside a Carpathian session (`CARPATIC_SESSION=1`, or the install marker and no Wayland;
`CARPATIC_FORCE=1` overrides). All host tests run on a private Xvfb with a throwaway HOME (`tests/xrun.sh`).

## Verification (see docs/STATUS.md for the board)

* `sh panel/tests/run.sh`: 57 logic checks (calendar maths incl. leap years / month boundaries / locale first weekday, ics + recurrence + quick entry,
  dunst history, nmcli/wpctl/bluetoothctl parsers, quick-settings tile model on fakes, task-list model, config, designs, placement, contrast), 22 GUI-model checks (every
  look x mode x pane builds, nothing overflows, clicks, drag reorder, password flow, swipe dismiss, overflow menu), and an Xvfb end-to-end (fake WM, tray icons, flyouts
  by xdotool click, live design switching, struts, idle CPU). Wired as suite `panel-logic` in `tests/run.sh`.
* Screenshots: `docs/screenshots/panel-<design>-<dark|light>.png`, `flyout-<quick|calendar|start>-<design>-<mode>.png`, reference sheets `ref-panel-*.png`.
  Regenerate: `panel/tests/xrun.sh sh panel/tests/make-screens.sh docs/screenshots`.
* Measured on the host (Xvfb, python 3.14, GTK 3.24): idle CPU 0.05 % (no timers except the 1 s clock check), memory PSS 24 MB / RSS 56 MB (RSS counts shared
  GTK libraries; budget was 40 MB), see "Honest gaps".

## VM verification (golden-full clone, QEMU, 1280x800, real dwm, nm-applet, Python 3.12/musl)
Screenshots: `docs/screenshots/vm-panel-*.png` (8 designs, flyouts for windows11/macos/ubuntu/kylin, hover preview, maximised window under the macOS strips, minimised task),
`vm-tint2-fallback-macos.png`.
* `BAR=panel` + `PANEL_DESIGN=windows11` in the profile: `carpatic-session start` launches the panel after boot, dwm retires its own bar, nm-applet re-docks into our tray.
  Switching the profile to a tint2 style stops the panel and starts tint2, switching back restores the panel (checked both ways).
* Struts: each design's `_NET_WM_STRUT_PARTIAL` is read by dwm (macOS: menu bar 28 top + dock 78 bottom over x 391..888; Ubuntu: 62 left from y 30; minimal 30 top);
  a maximised window follows them live when the design is switched (needed dwm changes below).
* Hover preview shows a live screenshot of the real Firefox window; quick settings hides what the VM lacks (Wi-Fi, Bluetooth, battery, backlight) and shows "Network, Wired connection".
* Minimise: click on the focused single window sends WM_CHANGE_STATE, dwm minimises, `_NET_WM_STATE_HIDDEN` appears, second click restores (checked with xprop).
* dwm changes made for this (desktop/dwm/dwm.c, verified in the VM): `WM_CHANGE_STATE`, `_NET_WM_STATE_HIDDEN`, built-in bar windows are destroyed when an external bar maps
  (they used to stay painted on screen, visible with tint2 too after a bar swap), docks' `_NET_WM_STRUT_PARTIAL` changes are watched, maximised windows are refitted to the work area.
* Idle numbers in the VM (30 s, nothing happening): panel PSS **36 MB** (RSS 71 MB, anonymous 27 MB), CPU 0.07 %; tint2 (windows profile) PSS 21 MB, RSS 42 MB, anonymous 7 MB, CPU 0 %;
  dwm RSS 23 MB. So the panel costs about 15 MB more than tint2 in exchange for previews, tooltips, flyouts and designs; the 40 MB budget holds for PSS, not for RSS.
  (On the host with Python 3.14 the same panel measures PSS 24 MB.)

## Honest gaps

* **Compositor**: no translucency or blur, rounded corners are 1-bit XShape (smooth fills, 1 px border; edge not anti-aliased), no window thumbnails for
  windows on other tags or minimised (they show the icon card). With a compositor the bars and flyouts use real alpha automatically (not run in a VM: no compositor there).
* Autohide moves the bar off screen but the main bar's height is still reserved by dwm (docks drop their strut properly); fixing it needs a dwm hook for the bar window.
* Memory: see above, the floor is the Python + GTK import; a C rewrite would be ~12 MB and is not planned.
* Not built: dock magnification, per-monitor window filtering (`monitors=all` repeats the bar, windows are shown on every bar; multi-monitor not tested in a VM), StatusNotifier
  (appindicator) icons (apps without an XEmbed icon need `snixembed`, in NEEDS.md), hotspot tile, Wi-Fi enterprise networks (WPA-EAP).
* Not exercised on real hardware or with real Wi-Fi / Bluetooth / battery / audio (the VM has none), so those panes were only run against fakes and the parsers' unit tests.
* Every shipped profile now has `BAR=panel` with its `PANEL_DESIGN`; if `carpatic-panel` is missing `carpatic-session` falls back to the profile's tint2 templates (or the dwm bar for tiling). Profile -> design: windows, beginner = windows11; macos = macos; ubuntu = ubuntu; tiling = minimal; zen = zorin; kylin = kylin. `panel/tests/vm-profiles.sh` (suite `panel-vm`) checks each of them, light and dark, a profile round trip, the fallback and a reboot.

## Carpathian OS branding

Launcher and menu branding use the canonical 36 × 30 mountain geometry from
`website/dist/assets/mark.svg`. Panel drawing uses the current palette foreground
and a transparent snow notch, retaining contrast on light, dark and high-contrast
surfaces. Application, account, power and other functional glyphs remain unchanged.
All eight panel designs expose a branded launcher; Ubuntu retains its Activities
label and applications grid, and Minimal adds a compact launcher before workspaces.
The three Start flyout layouts share the same mark.

The installer stages `carpathian-os.svg` and `carpathian-os-symbolic.svg` under
`$PREFIX/share/carpatic/panel/branding`. Distribution-wide icon registration can
copy these to the chosen icon theme; the panel package does not override app icons.
Package names, commands, theme identifiers and configuration paths remain compatible.

`python3 integration/carpatic/panel/tests/test_branding.py` checks canonical asset
geometry, context restoration, all shipped palette contrasts, launcher design
coverage and a disposable DESTDIR install. These are pure checks; actual panel
and flyout window layout still needs isolated-session visual verification.
