# Carpathian theme picker

`carpatic-theme-picker` (Super+Ctrl+Shift+Space, `carpatic theme pick`, Style > Theme picker in the menu, "Browse themes" in Settings > Appearance).
A centred card with a large live preview, a strip of options and a list of rows. **Left/Right change the focused row and the real desktop follows**
(about half a second later), Up/Down move between rows, Enter keeps, Esc puts everything back exactly as it was.

![picker](../docs/screenshots/themepicker-open.png)
![preview](../docs/media/themepicker.gif)

Why it is not just Omarchy's picker: that one browses a carousel of preview pictures and applies on Enter (see `RESEARCH.md`). This one changes the desktop
while you browse, can change much more than the theme, and reverts on Esc. What was ported from Omarchy: the keys (Left/Right, Tab, Enter, Esc, type to filter),
click outside to cancel, one preview per theme, thumbnails cached by content signature, a helper that stays loaded so opening never waits.

## Keys
| Key | Does |
|---|---|
| Left / Right | previous / next value of the focused row (wraps); the desktop retints, debounced |
| Up / Down, Tab / Shift+Tab | previous / next row |
| Enter | keep. Closes at once; the full apply (editors, browsers, Qt, CLI tools) finishes in the background |
| Esc | revert everything to the settings from when the picker opened (first clears an active filter or closes a text box) |
| Del | reset the focused row to the theme / style default |
| `#` on Accent colour | type your own hex colour (six digits, applies as soon as it is complete) |
| Ctrl+S | save the current look as "my theme" (`~/.config/carpatic/themes/<name>/`, appears in the theme list) |
| any letter | type-to-filter the options of the focused row; Left/Right then walk the matches |
| Home / End | first / last option |
Mouse and touch: click a row, click its chevrons or an option in the strip, double-click the preview or press **Keep** to keep, **Revert** or a click outside the card to revert,
wheel over the strip changes the value, wheel over the rows moves rows, a touch swipe works like the arrow keys.

## Rows
| Row | settings.conf key | Notes |
|---|---|---|
| Theme | `THEME` | every theme in `configurator/themes` and `~/.config/carpatic/themes`; a new theme drops the accent, wallpaper and border-colour overrides so it shows as designed |
| Light or dark | `THEME` | the paired theme (catppuccin and catppuccin-latte...), otherwise Carpathian / Carpathian Light |
| Wallpaper | `WALLPAPER` | the theme's pictures, the Carpathian scenes of its mode, `~/.config/carpatic/backgrounds/<theme>/`, `~/Pictures/Wallpapers` |
| Accent colour | `ACCENT` | theme colour, the six design accents, the theme's own palette colours, custom hex |
| Window border, Border colour | `BORDER_WIDTH` `BORDER_ACTIVE` | width 0-8 px, colour from the palette or any hex (dwm `border_width`, `border_active`) |
| Corners | `CORNER_RADIUS` | square to 18 px (dwm rounds the windows live) |
| Gaps | `INNER_GAP` `OUTER_GAP` | None, Tight, Normal, Cosy, Roomy, Zen |
| Window buttons | `WINDOW_BUTTONS` | the ten styles of the design system (always drawn in the preview, even on a style without title bars) |
| Icons, Cursor | `ICON_THEME` `CURSOR_THEME` | the installed packs |
| Font, Font size, Code font | `UI_FONT` `UI_SIZE` `MONO_FONT` | the curated families that are installed |
| Desktop style | `PROFILE` | Windows, macOS, Ubuntu, tiling, simple. **Applies when you press Enter** (it restarts the bars), the preview shows it at once |
The rows write the same keys as Carpathian Settings and `carpatic-appearance`, so both stay truthful. Every row shows what the default is ("Default (Papirus-Light)").
A dot in front of a row means it overrides the default.

## How it works
```
hotkey / carpatic theme pick / menu / Settings
        |  carpatic-theme-picker (sh, writes one line to a FIFO, 2 ms)
        v
carpatic-theme-picker-ui --daemon      resident helper started at login (carpatic-session), 85-100 MB, holds the window, fonts, thumbnails
   Session (tp_model.py)   rows, candidate state, snapshot, filter, custom colour, save-as        <- unit tested on the host
   Card (tp_card.py)       draws header, preview, strip, rows, footer; hit regions               <- renders to PNG on the host
   draw_mock (tp_render.py) the mock desktop from palette + wallpaper + style + border/gaps/corners/buttons/icons/fonts
   Applier (tp_model.py)   debounce 150 ms, one apply at a time, newest request wins, a running live apply is stopped when a newer one is due
        |  settings.conf  +  carpatic-apply --skip editors,browser,qt,cli   (~0.7-1.0 s, everything you can see)
        |  window look keys: carpatic-look (30 ms, rewrites border/corner/gap lines of dwm's themes.toml; dwm reloads live)
        |  wallpaper: feh at once, the colours follow
        v  Enter: carpatic-apply (full, background)   /   carpatic-profile set X   when the desktop style changed
```
- The window is an override-redirect X window with a seat grab (like rofi): no title bar, never tiled, retried for up to a second while the window manager still holds the shortcut keys. If nothing can grab the keyboard (lock screen) it closes again and says so instead of hanging.
- Corners are cut with the X Shape extension when there is no compositor, real alpha when there is one. Everything is drawn into one cairo surface before the window is mapped, so it never shows empty.
- The preview is a mock drawn from the *candidate* state, not a screenshot, so every row shows its effect before the real desktop has finished, and it works with no theme-supplied `preview.png`. Large preview is cached per look; thumbnails are cached in memory and in `~/.cache/carpatic/themepicker/` (PNG per palette+wallpaper+look signature).
- Wallpapers around the focused theme/wallpaper are decoded in idle time, so the next key press finds them ready.
- `~/.config/carpatic/no-picker-daemon` (a file) stops the login autostart; the picker still opens, about 0.8 s on first use.
- `CARPATIC_PICKER_LOG=file` writes JSON lines with open, key-to-frame and apply timings.

## Files
`bin/carpatic-theme-picker` (launcher), `bin/carpatic-theme-picker-ui` (GTK3 window + helper), `bin/carpatic-look` (fast window-look path), `lib/tp_*.py`, `install.sh`, `packages.txt`, `share/applications/`, `tests/`, `RESEARCH.md`, `NEEDS.md`.

## Tests
| Test | What |
|---|---|
| `python3 themepicker/tests/test-model.py` | 44 checks: theme/wallpaper discovery, row models, defaults chain (look file > style conf > built-in), Left/Right wrap, filter, custom colour, reset, revert snapshot, save-as, settings.conf round trip, the debouncer on a fake clock (held key = one apply, never two at once, latest wins, abort once) |
| `sh themepicker/tests/test-look.sh` | 13 checks of `carpatic-look` on a themes.toml copy (idempotent, clamps, keeps comments and other sections) |
| `themepicker/tests/vm-e2e.sh` | 32 checks in the VM with xdotool: open, live retint, Esc revert (settings.conf byte-identical), Enter keep, border/corner/gap rows, Delete, hex colour, type-to-filter, held-down arrows (1-3 applies), mouse (row, chevron, Keep, click outside), save as my theme, desktop style on Enter, timing |
| `themepicker/tests/shots.sh` | all screenshots in `docs/screenshots/themepicker-*.png` and `docs/media/themepicker.gif` |
Wired into `tests/run.sh` as suites `themepicker-logic` (quick) and `themepicker` (standard, needs golden-full + the working-tree configurator/dwm).

## Measured (VM, 4 vCPU, 2 GB, no GPU, 1280x800)
| What | Result |
|---|---|
| Open, helper running (hotkey to a fully drawn card) | **15-35 ms** to the first frame, window visible about 50-80 ms after the command (the rest is the measuring tool) |
| Open, no helper (first use, helper crashed) | 0.8 s with cached thumbnails, 1.0 s from nothing (Python and GTK import 0.37 s, drawing 0.4 s) |
| Arrow key to new frame | 10-35 ms; thumbnails and wallpaper are prepared in idle time |
| Right pressed, real desktop retinted | wallpaper about 0.2 s, colours about 0.5-0.7 s (debounce 0.15 s + `carpatic-apply` 0.5-0.9 s); border, corner, gap rows about 0.1 s |
| Esc, real desktop back | 0.4-1.0 s |
| 12 Right presses 40 ms apart | 1 to 3 applies (never one per key) |
| Resident helper | 85-100 MB resident (Python + GTK + cached frames); `~/.config/carpatic/no-picker-daemon` opts out |
| Disk cache | about 8 KB per thumbnail, 54 files / 436 KB after a full session |

## Limits (honest)
- The overlay is not translucent and has no fade: dwm runs without a compositor on purpose (instant is a feature there).
- `carpatic-apply` is the bottleneck of the live retint (0.5-1.0 s, mostly small forks inside the shell script); see `NEEDS.md`.
- The window bar font and the `Font` row of the dwm bar take effect at the next login (dwm reads it at start): the Settings app has the same limit.
- Video wallpapers and `preview.png` files of Omarchy themes are not used: previews are drawn. The wallpaper row lists pictures only.
- Cursor size, GTK theme and the hinting options are not rows here; they live in Carpathian Settings.
- Touch: swipes work, but there is no on-screen keyboard for the custom colour / save-as boxes.
- Only the dwm on X11 desktop is supported.
