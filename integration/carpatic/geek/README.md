# Carpatic geek tools

The keyboard-driven, hackable, themeable side of Carpatic OS, for people who came from Omarchy, ricers and developers. One front door
(`carpatic`), one keyboard menu, one searchable shortcut sheet, one-command dev environments, web apps, hooks, theme packs and dotfiles.
Credit and what was adapted from Omarchy (MIT): see `NOTICE`. The code is new, for Alpine (musl, OpenRC), dwm, X11 and rofi, in the
Carpatic design system.

Users: read `docs/USER-GUIDE-geek.md`. This file is for people who work on the tools.

## What is in here
| Piece | Files | What it does |
|---|---|---|
| `carpatic` router | `bin/carpatic`, `share/commands.tsv`, `share/completions/`, `share/man/carpatic.1`, `tools/gen-man.sh` | `carpatic <area> <verb>` maps onto the existing `carpatic-*` tools. The command table is plain data: add a line to add a command. Help, bash/zsh/fish completion (`carpatic --complete`) and the man page are all derived from it. Exit codes: 0 done, 1 the tool failed, 2 not understood (with a did-you-mean), 3 not available here. |
| Menu | `bin/carpatic-menu`, `lib/carpatic_menu.py`, `share/menu.toml` | Super+Alt+Space. Tree as data (TOML), context guards (laptop, Bluetooth, Btrfs snapshots, hibernate ...), live providers (themes, wallpapers, installed apps, snapshots ...), rofi with the active palette and font, Esc = back, type to filter, "Find anything" searches every entry, your own entries in `~/.config/carpatic/menu.d/*.toml`. Backends: rofi, and a scripted one for tests (`CARPATIC_MENU_BACKEND=script`). |
| Shortcut sheet | `bin/carpatic-cheatsheet`, `lib/carpatic_keys.py` | Reads the real `hotkeys.toml` (and the macOS Cmd rules) of the active profile, or of any profile merged from the profile files. Popup (Super+K tiling, Super+F1 everywhere), `list`, `search`, `json`, printable `html` and `pdf` (PangoCairo, Inter + JetBrains Mono). Enter in the popup tries the shortcut. Printable sheets for every profile: `docs/cheatsheets/`. |
| Dev environments | `bin/carpatic-dev`, `lib/carpatic_dev.py`, `share/devenvs.toml`, `share/nvim/init.lua` | `carpatic install dev node` etc. Alpine packages (musl-native) through `carpatic-store`, every environment verified by compiling or running a small real program. Databases in containers. Neovim starter without plugins, colours generated from the active theme. |
| Web apps, terminal apps | `bin/carpatic-webapp`, `bin/carpatic-tui`, `lib/carpatic_apps.py`, `share/presets/*.tsv` | Launcher entries with their own window class, profile (Chromium `--app` or a stripped Firefox profile) and icon (fetched from the site, or an offline letter badge in the design colours). Curated presets. |
| Hooks | `bin/carpatic-hook`, `share/hooks.tsv` | `~/.config/carpatic/hooks/<point>` and `<point>.d/*`. Called by theme change, update, screenshot, recording, wallpaper, profile, fonts, webapp/dev install, login, dotfiles sync. A failing hook never breaks the tool. |
| Theme packs | `bin/carpatic-themepack`, `lib/carpatic_themepack.py` | export / import / convert / share / remove, next theme, next wallpaper. Packs are tarballs with SHA256SUMS and an optional ssh signature. Omarchy theme folders are converted with a report (all 22 upstream themes are tested). Imported themes live in `~/.config/carpatic/themes` and are known to `carpatic-theme`, the Settings app and `carpatic-apply` (configurator change). |
| Capture and share | `bin/carpatic-trigger`, `bin/carpatic-clipd`, `src/clipwatch.c`, `lib/serve_once.py`, `lib/pixel.py` | Screenshot (+ annotate with satty or flameshot), screen recording (ffmpeg x11grab), colour picker, clipboard history (memory only), one-time LAN share, night light, idle-lock toggle. |
| Dotfiles | `bin/carpatic-dotfiles` | git in `~/.config/carpatic` with a secret scanner, ignore list for machine-made files, pull on a new computer. |
| Tour | `bin/carpatic-tour` | One GTK card from the menu (Learn). Shortcuts are read from the profile. Never opens by itself. |
| System info | `bin/carpatic-sysinfo` | `carpatic system info` (logo follows the accent), `doctor`, `version`. |

## Install
`doas sh geek/install.sh` after `desktop/install.sh` and `configurator/install.sh` (idempotent). It installs `packages.txt`, the tools to
`/usr/local/bin`, libraries to `/usr/local/lib/carpatic-geek`, data to `/usr/local/share/carpatic/geek`, completions, the man page, two launcher
entries (Carpatic Menu, Keyboard Shortcuts) and builds `carpatic-clipwatch`. `CAPTURE=1` also installs ffmpeg, satty and redshift.
Everything also runs straight from the repository (`geek/bin/carpatic`), which is how the host tests work.

## Design rules followed
- Voice: plain sentences, say what happened and what to do next; no raw tracebacks (tests grep for them).
- Nothing destructive without a confirm row (restart, shut down, remove, rollback).
- Secrets: clipboard history in tmpfs only; the dotfiles tool refuses to commit tokens/keys; downloads need a pinned `--sha256`; packs are
  extracted as plain files only (no symlinks, no traversal, allow-listed extensions, size caps).
- No new compiled dependency except a 40-line XFixes watcher; if it is missing the clipboard history polls.

## Tests
| Test | Needs | What |
|---|---|---|
| `bash geek/tests/test-host.sh` | python3, git (optional: ssh-keygen, zsh, fish, man) | 252 checks: router, completions, man page freshness, menu tree/guards/extensions/keyboard flow, sheet for all five profiles, 22 Omarchy themes, pack round trip, hostile tarballs, hooks, web apps, dotfiles, dev environment definitions. |
| `geek/tests/vm-e2e.sh` | a VM from `golden-full`, network; `GEEK_ONLY=menu,dev` picks sections, `GEEK_HEAVY=0` skips big downloads, `GEEK_SHOTS=1` writes `docs/screenshots/geek-*.png` | deploys, installs, runs the tools for real in the dwm session (menu, sheet popup, tour, dev environments incl. rootless Podman databases, web apps, themes, capture, hooks, updates). Sets a passwordless doas rule for user `carpatic` in the disposable VM only. |
| `store/tests/test-store.sh` | store VM | has one added line for the catalog entries this component added. |
Hook into `tests/run.sh`: see `geek/NEEDS.md`.

## Known limits (honest list)
See the "Limits" section of `docs/USER-GUIDE-geek.md` and the status in `docs/STATUS.md`.

## Verified vs not (honest)
Verified in a golden-full VM (screenshots in `docs/screenshots/geek-*.png`): router, menu (all five profiles share the key; tiling, windows, ubuntu opened with the real hotkey, macOS from the Spotlight launcher), shortcut popup and search, PDF/HTML sheets for all profiles (`docs/cheatsheets/`), tour card, Omarchy theme import with webp wallpapers and live recolour, hooks, web app and terminal app windows, screenshot via the menu, recording (ffmpeg x11grab, playable file), colour picker (exact pixel), clipboard history (XFixes helper), one-time share, dotfiles push, updates through the router with the post-update hook, dev environments node python c tools helix neovim sqlite go ruby php java rust podman docker, Redis and PostgreSQL containers.
Not verified: zsh and fish completions (not installed on host or guest; the bash one is), Flatpak editors (zed, vscode, vscodium) through `carpatic install dev`: the store's Flatpak install failed in the VM with "No remote refs found" although `flatpak install` by hand worked (store issue, see NEEDS), MariaDB and MongoDB containers, annotate with satty/flameshot (host test uses stand-ins), night light, Btrfs snapshot menu path (VM is ext4), laptop entries on real batteries, real hardware, the update channel entry (no channel concept exists yet).
