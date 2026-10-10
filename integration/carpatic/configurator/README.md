# Carpathian configurator: Welcome + Appearance / Theme Manager

First-run wizard that makes the dwm desktop feel familiar: pick where you come from (profile), pick a look (theme), optionally pick apps.
Re-runnable any time as **Carpathian Settings** (launcher entry / `Super+F2`).

![wizard](../docs/screenshots/configurator-wizard-1-profile.png)


## Design system (phase 3)
Default themes are `carpatic` (dark) and `carpatic-light` from `design/tokens/out/configurator-theme/` (Spruce accent `#5cc8a8` / `#16806a`; accent picker offers Spruce, Glacier, Dusk, Rose, Ember, Moss in the value for the current mode; `accent_fg` is `#08241d` on dark accents and `#ffffff` on light ones).
The 16 design wallpapers (8 Carpathian scenes x dark/light, ~6.6 MB) live in `share/wallpapers/`; `themes/carpatic*/wallpaper*.jpg` use Bucegi/Retezat (dark) and Bucegi/Tatra (light). GTK CSS uses the token colour names + widget polish (radius 6/10/14, 1 px borders), the dwm title bar is a tint of the surface with the accent only on the focused border, rofi shows no prompt and the placeholder "Search apps, files, commands".
Settings: the Style page marks the active style with an accent border plus an "In use" badge (hover is only a faint tint); pages are built when first opened, icon and wallpaper thumbnails fill in from idle callbacks and are cached in `~/.cache/carpatic/thumbs`, so the window maps in about 1 s (was 7-8 s) on the VM.


## One palette for everything (carpatic-retint)
`carpatic-apply` colours the shell (dwm, tint2, rofi, dunst, GTK, st/alacritty/Xresources, open terminals by OSC 4/10/11/12/17/19) in the foreground and returns in about 0.5 s; `carpatic-retint` then colours the apps in parallel, in the background:

| Category | Targets | How it is applied | Where the files go |
|---|---|---|---|
| terminal | kitty, foot, ghostty (+ alacritty, st, xterm by apply) | 16 ANSI + cursor + selection + fonts; kitty reloads on SIGUSR1; every open pty gets the OSC sequences at once | `~/.config/kitty/current-theme.conf` (+ `include`), `~/.config/foot/carpatic.ini`, `~/.config/ghostty/carpatic.conf` |
| editors | VSCodium / Code - OSS / VS Code (native, compat box, Flatpak), Helix; Neovim via the geek hook `carpatic-dev nvim-theme` | full workbench + semantic-token theme (Omarchy template, 1300 lines) installed as extension `carpatic.carpatic-theme` AND copied into `workbench.colorCustomizations["[Carpathian]"]`, which running windows watch | `~/.config/VSCodium/User` + `~/.vscode-oss/extensions`; `~/.config/Code - OSS/User`; `~/.config/Code/User` + `~/.vscode/extensions` (the Ubuntu compat box shares `$HOME`); Flatpak `~/.var/app/com.vscodium.codium/config/VSCodium/User` + `.../data/codium/extensions` (same pattern for `com.visualstudio.code-oss`, `com.visualstudio.code`) |
| browser | Chromium/Chrome/Brave/Edge, Firefox (and Flatpak/LibreWolf profiles) | Chromium: seed colour + scheme written into each profile's `Preferences` while the browser is closed; `chromium-policy.json` (BrowserThemeColor) is ready for `carpatic-browser-theme --install-policy` (root, live). Firefox: `chrome/userChrome.css` + `userContent.css` + a marked block in `user.js` (`toolkit.legacyUserProfileCustomizations.stylesheets`), takes effect at the next start | profile dirs |
| qt | Qt5/Qt6 apps via Kvantum | theme "CarpaticA/B" generated from KvFlat/KvFlatLight (greys remapped between background and foreground, blues -> accent); the name alternates so a running app that polls Kvantum can notice; `QT_STYLE_OVERRIDE=kvantum` from `env.sh`; Kate gets Breeze Dark/Light | `~/.config/Kvantum` |
| cli | btop, tmux (live `source-file`), starship, bat, lazygit, fzf, eza/ls, gum | files + `~/.config/carpatic/env.sh`, sourced by new shells (`/etc/profile.d/carpatic-theme.sh`, `carpatic-term`, `carpatic-launch`) | `~/.config/btop/themes/carpatic.theme`, `~/.config/tmux/carpatic.conf`, `~/.config/carpatic/starship.toml`, `~/.config/bat/themes/carpatic.tmTheme`, ... |

Control: `carpatic-theme apply [--only CATS] [--skip CATS]` (desktop terminal editors browser qt cli), `carpatic-theme also terminal editors ...` (the "Also colour" setting, `none` to turn all off), hook `theme-set` runs after every apply (geek's `carpatic-hook`).
Measured in the VM: `carpatic-apply` returns after 0.48 s; the app files are all written 0.1 s later.

Verified live (screenshots `configurator-retint-*.png`, dark `carpatic` and light `carpatic-light`): st, Alacritty and kitty (open windows retint instantly, switching theme from dark to light changed all three), btop, Neovim (in kitty), bat/eza/gum/fzf colours, Kate + QTerminal (Kvantum), Firefox (dark). Host tests (112 checks) cover every theme x every template, JSON validity of the VS Code theme, category switches and the install paths with a fake HOME.
Not verified: VS Code/VSCodium itself (no apk package on Alpine 3.24 musl and no Flatpak was installed in the VM; the generator, install paths and settings merge are tested, the editor was never started), Chromium's Preferences route and managed policy (file written and tested, browser not screenshotted), foot and ghostty (not installed in the VM; files are generated and rendered by tests; foot has no live reload apart from the OSC broadcast), already-running Qt apps do not restyle live (restart them), running Firefox/Chromium need a restart, helix/lazygit/starship only checked as generated files, Obsidian/Spotify not done.

## Carpathian Settings (Appearance manager) - `carpatic-settings`, Super+F2
GTK3 app, one live preview pane on the right (mini desktop with the style's bar/dock, window buttons, fonts and icons). Pages:

| Page | What |
|---|---|
| Style | the five profiles (this is the "Where are you coming from?" question, changeable any time) |
| Colours | dark/light, accent, 16 palette themes, app (GTK) theme: "Follow colours" (adw-gtk3 recoloured by the palette), Adwaita, or a native pack (WhiteSur, Yaru, Numix, Paper, Breeze) |
| Fonts | pairing presets, UI font + size, monospace font + size, hinting, subpixel order, LCD filter, antialiasing, HiDPI scale |
| Icon packs | any installed icon theme, independent of the style, with a 4-icon preview; "More to install" list |
| Cursors | theme + size |
| Wallpapers | every theme's wallpapers, ~/Pictures/Wallpapers, any file |

Everything goes through the CLI (`carpatic-appearance set ui-font Inter ui-size 10 ...`, `carpatic-theme`, `carpatic-profile`, `carpatic-pack`) so scripts and the GUI are equivalent.
Settings persist in `~/.config/carpatic/settings.conf`; `carpatic-apply` regenerates: dwm themes.toml (incl. `[titlebar]`, `default_layout`), fontconfig (`~/.config/fontconfig/fonts.conf`: rgba, hintslight, lcdfilter, sans/mono aliases),
xsettingsd (GTK theme, icons, cursor, font, DPI: **live** for running GTK apps), gtk-3.0/gtk-4.0 settings.ini + gtk.css, `~/.icons/default` (cursor), `~/.Xresources` (Xft, Xcursor), tint2/rofi/dunst (fonts, icon theme, colours),
terminal font (`carpatic-term` passes `-f`; open terminals recolour via OSC but keep their font), dwm bar font (`~/.config/carpatic/dwm-font`, read when dwm starts: next login).
The Settings window follows changes made elsewhere (it polls settings.conf), so Super+F2 stays truthful.

### Style defaults (profiles/*.conf; user choices override each one)
| Style | UI font | Mono | GTK | Icons | Cursor |
|---|---|---|---|---|---|
| windows | Noto Sans 10 | JetBrains Mono | adw-gtk3 + palette | Papirus | Adwaita 24 |
| macos | Inter 10 | JetBrains Mono | WhiteSur if installed, else adw-gtk3 + palette | Qogir if installed, else Papirus | capitaine 24 |
| ubuntu | Cantarell 11 | JetBrains Mono | Yaru if installed, else adw-gtk3 + palette | Yaru if installed, else Papirus | Adwaita 24 |
| tiling | JetBrains Mono 10 | JetBrains Mono | adw-gtk3 + palette | Papirus | Adwaita 24 |
| beginner | Noto Sans 11 | JetBrains Mono 11 | adw-gtk3 + palette | Papirus | Adwaita 32 |
Segoe UI, SF Pro and the Ubuntu font are not shipped (proprietary / not in Alpine); Noto Sans, Inter and Cantarell stand in.

### Packs (`carpatic-pack list|install|remove`, catalogue `share/packs.list`)
Downloads are pinned to a tag/commit and sha256-verified, install into `~/.local/share/{icons,themes}` (no root), and are **never fetched at ISO-build time**.
Alpine packages (fonts, Numix, Breeze, Faenza, Paper, cursors) need root: the manager opens a terminal that runs `doas apk add` so the user types their password; no passwordless-root rule is installed.
Measured in the VM (disk after install / download):

| Pack | Source (pinned) | Disk | Download | Licence |
|---|---|---|---|---|
| Tela Circle | github vinceliuice/Tela-circle-icon-theme 2026-07-07 | 83 MB | 3.7 MB | GPL-3.0 |
| Qogir | github vinceliuice/Qogir-icon-theme 2025-02-15 | 102 MB | 9.1 MB | GPL-3.0 |
| Colloid | github vinceliuice/Colloid-icon-theme 2026-08-10 | 90 MB | 5.8 MB | GPL-3.0 |
| Kora | github bikass/kora v2.0.6 | 45 MB | 6.1 MB | GPL-3.0 |
| Candy | github EliverLara/candy-icons @83512fb | 8 MB | 2.2 MB | GPL-3.0 |
| Yaru icons | Ubuntu archive yaru-theme-icon 24.04.2-0ubuntu1 | 94 MB | 26.9 MB | CC-BY-SA-4.0 / GPL-3.0 |
| Yaru GTK | Ubuntu archive yaru-theme-gtk 24.04.2-0ubuntu1 | 5 MB | 0.7 MB | GPL-3.0 / CC-BY-SA-4.0 |
| WhiteSur GTK (light+dark, prebuilt) | github vinceliuice/WhiteSur-gtk-theme 2026-09-10 release | 7 MB | 0.4 MB | MIT |
Apk packs: Papirus, Adwaita, Breeze, Numix(-Circle), Faenza, Paper icons; Numix, Paper, Breeze GTK; capitaine and breeze cursors; fonts Inter, JetBrains Mono, Noto, Cantarell, Fira, Roboto, Hack, Source Sans, Open Sans, Lato.
Shipped in the image by default (`packages.txt`): adw-gtk3, xsettingsd, Inter, JetBrains Mono, Noto (+emoji), Cantarell, capitaine cursors, Adwaita + Papirus icons.
The sha256 pins equal the ones in the author's LinPad MANIFEST (tarballs re-downloaded and compared).

## Commands
| Command | What |
|---|---|
| `carpatic-profile list\|current\|set <windows\|macos\|ubuntu\|tiling\|beginner>` | apply a profile (bars, hotkeys, launcher, default layout) |
| `carpatic-theme list\|current\|set <name> [--accent #rrggbb\|default] [--wallpaper FILE\|default]` | one palette regenerates everything |
| `carpatic-configure profile=.. theme=.. [accent=..] [wallpaper=..] [store=yes]` | non-interactive wizard (same effect, writes the first-run flag) |
| `carpatic-welcome` / `carpatic-settings` | the GTK wizard (settings falls back to a rofi flow if GTK is missing) |
| `carpatic-apply [--restart]` | regenerate + reload from `~/.config/carpatic/settings.conf` (what the others call) |
| `carpatic-launch [drun\|run\|power\|menu]`, `carpatic-keys`, `carpatic-switch`, `carpatic-snap`, `carpatic-cmd`, `carpatic-lock`, `carpatic-screenshot`, `carpatic-term` | helpers bound to hotkeys |

## How it works
```
settings.conf (PROFILE THEME ACCENT WALLPAPER)
   |  carpatic-apply
   +-- themes/<n>/colors.toml (Omarchy palette)  --carpatic-render-->  templates/*.tpl, templates/{tint2,rofi}/*.tpl
   +-- profiles/<p>.conf + <p>.keys + <p>.sxhkd  --carpatic-genkeys-->  ~/.config/dwm-titus/hotkeys.toml (merged over desktop defaults)
   outputs: dwm themes.toml + hotkeys.toml + window-rules.toml (dwm live-reloads, no recompile), tint2 bars, rofi launcher theme, dunstrc,
            ~/.Xresources, OSC escape sequence broadcast to open terminals (st/xterm/alacritty), alacritty.toml, GTK3 css/settings, wallpaper (feh), sxhkdrc
```
Profiles are declarative: `profiles/<name>.conf` (bar, launcher style, default layout, supertap, titlebar options), `<name>.keys` (dwm TOML bindings;
`unbind MODS KEY` removes a desktop default), optional `<name>.sxhkd`. Add a profile = add three files.
Themes: 10 palettes copied from upstream-omarchy/themes (MIT, credit in NOTICE): catppuccin, catppuccin-latte, everforest, flexoki-light, gruvbox, kanagawa, nord, rose-pine, tokyo-night, white, only the colour palettes come from Omarchy: every theme's two wallpapers (`wallpaper.jpg`, `wallpaper-2.jpg`, 1920x1080) are Carpathian originals, Carpathian scenes recoloured from the theme's own palette by `design/tools/theme-wallpapers.py` (deterministic, no third-party picture). `tests/test-wallpaper-provenance.sh` fails if a shipped picture is not ours.
Add one by dropping `themes/<name>/colors.toml` (+ `wallpaper.jpg`).

## Profiles
| | Bar | Launcher | Default | Notable keys |
|---|---|---|---|---|
| windows | tint2 bottom taskbar: Start icon, pinned apps, window list, tray, clock | start-menu list, bottom-left | floating | Alt+Tab, Alt+F4, Super tap/Super+R, Super+E files, Super+D show desktop, Super+L lock, Super+arrows snap, Print, Ctrl+Shift+Esc task manager |
| macos | tint2 top menu bar (logo, active window title, clock) + bottom dock | Spotlight (Super+Space) | floating | Super = Cmd (see limits), Super+Q/W close, Super+Tab, Ctrl+Super+arrows snap, Super+Shift+3/4 screenshots |
| ubuntu | tint2 top bar with centred clock + left dock | fullscreen app grid (Super tap / Super+A) | floating | Alt+Tab, Alt+F2, Ctrl+Alt+T, Super+arrows snap, Super+D, Super+L |
| tiling | dwm built-in bar | dmenu-like top bar | tiling | Super+Return, Super+W, Super+Space, Super+Shift+Space float, Super+B/E, Super+Esc power, Super+/ help |
| beginner | as windows | as windows | floating | as windows |
Window title bars/buttons: profiles write dwm's live `[titlebar]` section (enabled, button_side): on/right for windows, ubuntu, beginner; on/left for macos; off for tiling.

## UI choice
GTK3 via python3 + py3-gobject3 (~35 MB with deps; Alpine packages are in `packages.txt`). Rationale: renders real cards, swatches and live theme preview, no extra toolkit
(thunar, the file dialogs and the app store are GTK anyway), and it is themed by the same palette (generated CSS). All real work is done by the CLI tools above, so the wizard
is a thin front end; if GTK is unavailable, `carpatic-settings` falls back to a rofi flow and `carpatic-configure` is always available.

## Install / first run
`sh configurator/install.sh` after `desktop/install.sh` (idempotent). It installs packages, copies data to `/usr/local/share/carpatic/configurator`, tools to `/usr/local/bin`,
builds `carpatic-supertap`, rebuilds dwm with `patches/0001-carpatic-configurator.patch` (skipped if not applicable), and appends `carpatic-session start` to the user's dwm autostart.
On first login (no `~/.config/carpatic/welcome-done`) the session shows the wizard; the flag is written when it finishes. Step 3 calls `carpatic-store firstrun` if installed.

## The dwm patch (now merged into desktop/dwm)
Stock desktop dwm cannot do taskbars: it only marks a window urgent on `_NET_ACTIVE_WINDOW`, it replaces its bar with *any* dock window (so two docks fight), the
built-in bar window stays alive under tint2, and the default layout is compile-time. The patch (marked CARPATIC, ~150 lines): focus on `_NET_ACTIVE_WINDOW`; docks named `carpatic-dock*` only reserve strut space;
built-in bar retired/restored when an external bar appears/exits; default layout from `~/.config/carpatic/dwm-deflayout`. Proposed for merge into desktop/dwm (NEEDS.md).

## Limits (honest)
- **Cmd on macOS**: X11 has no per-app modifier remap without a daemon. Implemented: `sxhkd` binds Super+{c,v,x,a,z,s,f,t,n,o,p,r,l,b,i,u,k,d,j,y,g}, Super+Shift+Z, Super+Left/Right/Backspace, Super+Shift+[ ] and
  `carpatic-cmd` sends the Ctrl equivalent via xdotool (Ctrl+Shift+C/V inside terminals). Verified: Super+A, Super+C in a GTK entry fills the clipboard. Not covered: Cmd+key for keys not listed, Cmd+Space conflicts, Cmd+Tab hold-cycling,
  apps that grab keys, key repeat/latency, Cmd+` window cycling. A real fix is a keyd/xremap style daemon (keyd is in Alpine; per-app rules need `keyd-application-mapper`): not done.
- **Super tap** opens the launcher via `carpatic-supertap` (XInput2 raw events, tap = no other key/mouse in between). Verified. Requires an X server with XI2.
- **Alt+Tab** jumps to the previous window (MRU toggle); holding Alt does not cycle through a list. `Super+D` "show desktop" views empty tag 9 (press again to return).
- **Snap** uses xdotool on floating windows (tiled windows are re-tiled by dwm).
- Layout default is per-tag in dwm; on a profile change `carpatic-layout` loops over tags with hidden hotkeys (Super+Ctrl+Alt+f/t). Never use F-keys there: Ctrl+Alt+Fn switches VT and killed X once.
- tint2's `button` item did not render in the VM for the Windows/Ubuntu bars (macOS worked), so Start/Activities are launcher icons.
- Qt apps: no Qt app is installed in the image, so Kvantum/qt5ct settings are not generated or verified (GTK only).
- tiling bar: dwm changes its bar font and position only when it starts; after leaving a tint2 style the built-in bar can come back at the bottom (dwm's unmanagealtbar should reset `m->topbar`).
- HiDPI: `SCALE=auto|100..300` (default auto, see "Display scale" below). Verified in VMs at 1280x800, 1920x1080, 2560x1440 and 3840x2160; not on a real HiDPI laptop. Native GTK theme packs (WhiteSur, Yaru ...) get the text and cursor scale but not scaled paddings.
- Fonts: fc-cache runs on apply; open terminals keep their font.
- Systray: tint2 tray not verified with a real tray icon. picom/compositing is off, so dock/rofi have square corners and no blur.
- Light-theme accent contrast is computed (black/white by luminance) but not hand-tuned per theme. Only 10 themes were ported.
- Launcher lists whatever .desktop files exist; tool entries are hidden via user NoDisplay overrides.

## Tests
- `sh configurator/tests/test-logic.sh` : 33 pure checks (renderer, all themes x templates, profiles, key merge, generation into a fake HOME). Runs on host and in the guest (busybox).
- `configurator/tests/vm-e2e.sh` : needs the configurator VM (all profiles, bars running, theme switch). Helpers: `deploy.sh`, `shot.sh`, `profile-shot.sh`.
- Hook into `tests/run.sh`: call `sh configurator/tests/test-logic.sh` as a host test, and `configurator/tests/vm-e2e.sh` with the VM prepared via `configurator/tests/deploy.sh` (needs `GOLDEN=golden-desktop`).


## Display scale

`carpatic-scale` decides how big the desktop is: `policy W H [MMW MMH]` (pure function, table test in `tests/test-scale.sh`), `detect`, `effective` (the `SCALE` setting when it is a number, else detect), `status`,
`sync` (re-apply when the wanted scale changed; run at login by `~/.xinitrc` and the autostart, and by `carpatic-display watch` when screens or resolution change), `env` (Qt exports).
`carpatic-appearance set scale auto|100..300` stores the choice and applies it live. `carpatic-apply` turns the percent into: `Xft.dpi`/xsettingsd/GTK dpi, cursor size, `[appearance] ui_scale` for dwm,
scaled gaps/borders/radius, and (through `carpatic-render`) every `Npx` of the generated GTK CSS and rofi themes, tint2 sizes and dunst numbers. Python GTK apps use `lib/carpatic_scale.py`.
Policy and rules: `docs/DESIGN-SYSTEM.md` section 5a.
