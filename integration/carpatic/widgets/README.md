# Carpatic widgets

Small cards on the desktop (clock, calendar, weather, system monitor, now playing, battery, notes, to-do, quick settings, wallpaper frame,
app shortcuts, tip of the day). **Off by default**: nothing runs, nothing is autostarted, no D-Bus name is claimed and no network request is made
until the user turns them on in Settings > Widgets or with `carpatic widgets enable`.

## Use
    carpatic widgets enable | disable | status | list
    carpatic widgets add weather L        # S, M or L (small, medium, large)
    carpatic widgets remove weather
    carpatic widgets edit                 # drag, resize, add, remove (mouse or keyboard); Esc finishes
    carpatic widgets peek                 # show above all windows until a key is pressed (Super+Alt+W)
    carpatic widgets look macos|windows|ubuntu|tiling|nothing|auto
    carpatic widgets clock analog|digital|dots
    carpatic widgets weather city Bucharest     # or: weather locate --yes (asks ipwho.is once), weather units f, weather off
    carpatic widgets todo add Buy bread | list | done 1 | clear
    carpatic widgets note "text"          # also click the Notes card to edit
    carpatic widgets arrange              # pack the cards tightly (edit mode: Auto arrange button, key r)
    carpatic widgets monitor primary|0|1  # which screen shows the cards
    carpatic widgets size|move|reset|doctor
Edit mode keys: Tab selects the next card, arrows move it one cell, `+`/`-` resize, Delete removes, `a` opens the add list, Esc or Enter finishes.
Peek: any key, or a click on the dimmed background, goes back to your windows.

## How it works
* **One process** (`carpatic-widgets run`, Python + GTK 3 + cairo/Pango), one small borderless window per card. The windows are override-redirect:
  dwm never tiles them, tint2 never lists them, they stay below every normal window and need no window-manager support. Rounded corners come
  from the X SHAPE extension without a compositor, real translucency with one.
* **Theming**: the palette comes from the active theme (`colors.toml` + `ACCENT` in `settings.conf`), the card style (macOS, Windows, Ubuntu,
  tiling, Nothing) from the theme (Nothing themes) or the desktop style (`PROFILE`). Text colours are forced to AA contrast against the card whatever
  the theme says (`look.ensure_contrast`, tested for every shipped theme). The host re-reads the settings every 15 s, so a theme change shows up by itself.
* **Grid**: one cell is 88 px at 96 dpi (76 + 12 gap), sizes S/M/L are 2x2, 4x2, 4x4 cells (some widgets differ, see `conf.CATALOG`). Columns count from the
  right edge. Positions are saved in `~/.config/carpatic/widgets/layout.json`. HiDPI: scale follows Xft.dpi / the GDK scale factor.
* **Data**: `/proc`, `/sys`, D-Bus (MPRIS, event driven, no polling), Open-Meteo for the weather (no key; the last answer is cached in
  `~/.local/share/carpatic/widgets/weather.json` and shown with its age when offline). Notes and to-do are plain files in `~/.local/share/carpatic/widgets/`.
  An optional `calendar.ics` in that folder feeds the large calendar's agenda (no recurrence rules).
* **Low overhead**: every card has its own timer (clock: once a minute unless analogue; system monitor 2 s; weather 30 min; battery 30 s; toggles 5 s; the rest
  are event driven), refresh pauses while a screen locker (slock, xsecurelock, i3lock, carpatic-lock) is running, and slows 4x when the power profile is "saver" (known while the Battery card is on) or `~/.config/carpatic/widgets/saver` exists. Choosing a power profile on the Battery card asks for the administrator password (`carpatic-sudo`).
* **Crash isolation**: drawing and refreshing each card is wrapped; after three failures a card shows "This widget stopped. Click to try again." and the host
  and the desktop carry on. Errors go to `~/.local/state/carpatic/widgets.log` (never to the screen). `SIGTERM`/`SIGINT` exit cleanly and remove the pid file.
* **Signals** (for scripts): `SIGHUP` reload the layout, `SIGUSR1` toggle peek, `SIGUSR2` toggle edit mode.

## Privacy
Weather asks `api.open-meteo.com` for a forecast of the saved coordinates; `geocoding-api.open-meteo.com` turns a city name into coordinates once.
"Use my approximate location" asks `ipwho.is` once and only when you press the button / pass `--yes`. Nothing else leaves the machine. Album art is read from local `file://` URLs only.

## Files
    bin/carpatic-widgets          CLI and `run` entry          lib/cwidgets/{conf,look,data,draw,preview,host}.py
    gui/carpatic_widgets_pages.py Settings > Widgets            install.sh   (copy-script install; the apk follows NEEDS.md)
    tests/test_widgets.py         33 host tests (fakes)         tests/xvfb-e2e.sh   real X input on a bare Xvfb
    tests/measure.sh              idle RAM/CPU table            RESEARCH.md   architecture decision with numbers
Run the tests: `widgets/tests/run.sh` and `widgets/tests/xvfb-e2e.sh` (the `widgets-logic` suite of `tests/run.sh --quick` runs both).

## Not done / honest limits
* One screen at a time (`monitor`, default primary): the layout is shared, not stored per monitor.
* Cards without hardware or data are not drawn at all: Battery on a desktop PC or VM, Quick settings when no tile works. They keep their place in the saved layout and reappear when the hardware does.
* Cards live on the desktop level (below windows) as on macOS/KDE; with a tiling layout windows cover them, `peek` is the answer.
* Night light needs `sct` or `redshift`; without them the tile says "Not available". Volume needs wireplumber or pactl.
* Calendar agenda: local `.ics` only (no CalDAV), no recurring events.
* Translucency needs a compositor (picom); without one cards are opaque with SHAPE corners and no shadow.
