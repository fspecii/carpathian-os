# Quick Look

Select a file in Files, press **Space**: an instant preview opens. **Space** or **Esc** closes it. Like macOS, in a lightweight distro.

| Key in the preview | Does |
|---|---|
| Space, Esc | close |
| Left / Right | previous / next file (the selection in Files moves along) |
| Enter | open in the default app (the pill button says which) |
| Ctrl+C | copy the path (copies the text instead if you selected some) |
| K | play or pause audio and video (Space never plays: it closes). Shift+Left/Right or J/L skip 5 s |
| + - 0 1 | zoom in, out, fit, actual size (images, PDF, fonts); Ctrl+wheel and drag work too |
| Page Up / Page Down, Home / End | PDF pages; Up / Down and the mouse wheel scroll |

Drag the little file icon at the top out of the preview to drag the file somewhere.

## What it shows
Text and source code (GtkSourceView, the theme's colours, line numbers), Markdown (rendered), JSON (pretty), CSV (table), images incl. SVG with EXIF line and zoom, PDF (pages, zoom), audio (cover art, tags, waveform, play button), video (embedded mpv with controls), archives (zip, tar, 7z/rar/iso when `7z` or `bsdtar` is there), folders, fonts (specimen), Office and e-books (title, author, first lines, embedded thumbnail), everything else as a card with kind, size, dates, permissions, a hex peek and an on-demand SHA-256. It only ever **reads**: nothing is executed, extracted or opened.

## Parts
`bin/carpatic-quicklook` (client, also `carpatic quicklook`), `bin/carpatic-quicklookd` (warm daemon, started by `carpatic-session`, or on demand), `lib/ql_app.py` (window), `lib/ql_worker.py` (sandboxed decoders), `lib/ql_detect.py`, `lib/ql_logic.py` (pure logic), `lib/ql_theme.py`, `lib/ql_setup.py` (Thunar), `lib/ql_x.py` (key grab), `lib/ql_widgets.py`.
Research and numbers: `RESEARCH.md`. Needs for packagers and other owners: `NEEDS.md`. Design: `docs/DESIGN-SYSTEM.md` section 9.15.

## Settings
`carpatic quicklook --off` / `--on` (`QUICKLOOK="on|off"` in `~/.config/carpatic/settings.conf`), `--status`, `--setup` (re-install the Space key in Thunar), `--stop`. It follows the theme, accent, light/dark, window corner radius and window-button style.

## Safety
* Refuses to run outside a Carpatic X11 session (`carpatic-quicklook` and the daemon exit with a message; tests cover this). Never run it on a developer desktop.
* Decoders in a separate process, under bubblewrap when installed, rlimits and a timeout; broken PDFs, images, fonts, archives and media were tested (random bytes with those extensions, a fifo, a dangling link): a friendly card, the daemon lives.
* mpv: no config, no scripts, no youtube-dl, no playlists. Large files: only the first 512 kB of text, archive listings are capped, folder summaries are time-boxed.

## Tests
* Host: `bash quicklook/tests/test-host.sh` (35 unit tests, no GTK; wired into `tests/run.sh --quick` as suite `quicklook-logic`).
* VM: suite `quicklook` (tier full): installs it in the VM and drives Thunar with xdotool: Space opens the right file, the window is mapped, Files keeps the focus, Right/Left move through files, Space and Esc close, Enter opens and closes, Ctrl+C copies the path, type-ahead is not hijacked, malformed files keep the daemon alive (`tests/e2e-guest.sh`, 16 checks passed on the last run).

## Honest limits
* The preview is a floating popup with no title bar; it is not managed by dwm (no tag, no taskbar entry).
* Space to toggle selection in Thunar's icon view is replaced (Ctrl+Space still toggles).
* Only Thunar is wired. Other file managers, the rofi launcher, the Settings wallpaper picker: see NEEDS.md.
* HEIC and AVIF need their codecs; Office documents are shown as text excerpts, not rendered pages; video needs mpv to find a working output (verified in QEMU, with `vo=x11` fallback logic, not on real GPUs).
* Real hardware, HiDPI and multi-monitor were not tested.
