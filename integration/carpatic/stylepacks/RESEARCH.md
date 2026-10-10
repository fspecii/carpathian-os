# Style packs: research and licences (Zorin-inspired "Zen", Kylin-inspired "Kylin")

Date of research: 2026-10-08. All upstream trees below are **read-only, git-ignored references** (`upstream-zorin/`, `upstream-kylin/`, existing
`upstream-linpad/`). Nothing from them is copied into the MIT tree. GPL / CC-BY-SA artwork is only ever fetched **on the user's machine, on
request**, as a pinned tarball with a sha256 (`stylepacks/packs.list`), installed to `~/.local/share/{themes,icons}` and carries its own licence
text. Look and behaviour of GNOME-Shell extensions and Qt/QML shells is **re-created as original code** (tint2 templates, a GTK launcher,
dwm window-look values).

## 1. What exists (GitHub API listing, not just the web page)

### github.com/ZorinOS (complete listing, 1 page, 26 repos)
| Repo | Licence (GitHub / debian/copyright) | Pinned commit read | Use |
|---|---|---|---|
| zorin-desktop-themes | GPL-2.0 / "GPL-2+", (c) 2015-2025 Zorin OS Technologies Ltd. | `1b4c77f4c7813ae74c1d704bf4d04211ecf91e3c` | **GTK 3/4 themes, 8 accents x light/dark** (ZorinBlue/Brown/Green/Grey/Orange/Purple/Red/Yellow -Light/-Dark). Optional pack `zorin-gtk`. |
| zorin-icon-themes | CC-BY-SA-4.0 (Sam Hewitt, Papirus team, Zorin OS Technologies) | `0d9e56a9be0bb598083cce6d98073dbb85d0e639` | Icon theme `Zorin` + 16 accent variants. Optional pack `zorin-icons`; the Zorin logo icons are stripped at install (see section 4). |
| zorin-taskbar | GPL-2.0, a Dash-to-Panel rebase | `03de1988e58319ba48c63d8a65e5f589c62abaa3` | **Cannot run on dwm** (GNOME Shell extension, 13.4k lines JS on St/Clutter). Only its *defaults* (gschema, facts) were read. |
| gnome-shell-extension-zorin-connect, zorin-connect-android | GPL-2.0 | not cloned | phone link, out of scope |
| zorin-exec-guard(-app-db) | GPL-3.0 / GPL-2.0 | not cloned | out of scope |
| org.gtk.Gtk3theme.Zorin*-{Light,Dark} (17 repos) | none | not cloned | Flatpak GTK-theme extensions, mirror of zorin-desktop-themes |

There is **no public** `zorin-menu`, `zorin-appearance`, `zorin-desktop-layouts` or wallpaper repository (all HTTP 404 on the API). The Zorin Menu is
closed/packaged only; the community fork `fishears/gnome-shell-extension-zorin-menu` (GPL-2.0, "(c) 2015 Giovanni Campagna, 2016-17 Zorin OS
Technologies Ltd", commit `2be064e3`) was read only to learn the layout (left: search + application list/categories, right: user, Places, Software /
Settings, lock / suspend / log out / power off). Zorin's layouts (Windows-like, macOS-like, GNOME-like) are in a closed "Zorin Appearance" app.

Zorin facts read from the sources (facts are not copyrightable; the implementation here is ours):
* GTK decoration radius **15 px**, soft 1 px outline `rgba(fg,0.075)`, big soft shadow `0 10px 15px 5px rgba(0,0,0,.175)`, window buttons are **circles**
  (`border-radius: 9999px`, 4 px padding), buttons/entries radius 9 px, transitions 150 ms. (`ZorinBlue-Light/gtk-3.0/gtk.css:1732,1764,189`)
* Colours (light / dark) per accent, e.g. Blue: fg `#123354` / `#bde6fb`, bg `#eaf0f6` / `#222b30`, base white / `#161c1f`, selected `#15a6f0` / `#add3e7`,
  borders `#dae2ea` / `#2d3940`. All 16 tables are in `stylepacks/zen/accents.list`.
* Zorin Taskbar defaults (`schemas/...zorin-taskbar.gschema.xml`): panel size **48**, group apps by app, show favourites (pinned), window previews **on**,
  preview size **200**, middle-click closes a preview, show-desktop strip **8 px** wide with hover, no border by default, `global-border-radius 0`.
* Zorin icon theme `ZorinBlue-Light/index.theme`: `Inherits=Zorin,Adwaita,gnome,hicolor`.

### github.com/ubuntukylin (34 repos, all stale, 2020-2024)
| Repo | Licence | Use |
|---|---|---|
| ubuntukylin-theme `96ac4e2` | GPL-3 per `debian/copyright` (GitHub shows none), (c) 2014 NUDT & Kylin Ltd | 2014-era GTK / icons / Plymouth / GRUB; **older than the packaged UKUI themes**, not used. Contains logos. |
| kylin-greeter `1a45707` | GPL-3.0 | lightdm greeter (Qt/QML); read for layout only, our greeter is lightdm GTK. |
| ubuntukylin-wallpapers | **NOASSERTION** | **not cloned, not shipped.** |
| kylin-software-center, youker-assistant, kylin-* apps | mixed / none | out of scope (apps, not look). |

### github.com/ukui (the UKUI desktop; also mostly stale, 2021-2024)
| Repo | Licence | Commit read | Use |
|---|---|---|---|
| ukui-themes | GPL-3.0 | `103cb26` (2021 tree) | historic; the maintained copy is **Debian `ukui-themes` 4.0.0.1-1** (from gitee `openkylin/ukui-themes`) which LinPad already pinned. |
| ukui-panel (LGPL-2.1), ukui-menu (GPL-3.0), ukui-sidebar (GPL-3.0), ukui-theme-customizer (GPL-3.0) | | `dbbe264`, `b1eaceff`, `8c63cc5`, `5cac422` | read-only references for structure. These GitHub trees are 2022-24 Qt widgets; **the 4.x QML shell lives only on gitee.com/openkylin**, which LinPad's spec reads. |
| ukui-wallpapers, ukui-kwin, ukui-greeter | NOASSERTION | not cloned | not shipped |

Real packaged theme assets (Debian pool, **sha256 pinned in `packs.list`**):
`ukui-gtk-theme_4.0.0.1-1_all.deb` (`e4ec392e...`, 220 KB: `ukui-white`, `ukui-black`, GTK2+3, GPL-3) and
`ukui-icons-theme_4.0.0.1-1_all.deb` (`f89e0996...`, 80 MB: `ukui-icon-theme-default` "light", `dark-sense` + `blue-crystal` cursors, GPL-3;
the index says "from moka"). Both `debian/copyright` files say GPL-3, (c) Tianjin KYLIN Information Technology Co., Ltd.

### LinPad (the author's own Kylin work, reused, not re-researched)
* `upstream-linpad/themes/kylin/DESIGN-SPEC.md` (631 lines, values cited as `repo/path:line` from the gitee UKUI 4.x sources): tokens (9 accents, KGray ramp
  light/dark, alpha ramp, radii 4/6/8/12, 150/300 ms motion, translucency 0.65), panel (48 px, bottom, order start/search/task-view/separator/tasks | tray /
  clock / show-desktop), running indicator pill (8 px one window, 16 px several, accent on active), hover preview 272x192 cards r12, start menu
  **766x688, three columns 312 | ~396 | 56**, window decoration (title 38, buttons 30x30 r6, close hover `#E7202B`, pressed `#C21B24`, radius 12),
  quick settings 396 wide (4-column 80x72 toggles r8, 56 px slider rows), notification cards (374 wide, r8, 6 s timeout), Super / Super+A / Super+Tab keys.
  Its sections 1-3, 6, 7 are implemented here: `stylepacks/kylin/tokens.toml` (data for other components) + the start menu, sidebar and tint2 template.
* `themes/guest/styles/kylin.conf` (GTK `ukui-white/black`, icons `ukui-icon-theme-default`, cursor `dark-sense`, Kvantum KvUKUI, Noto Sans 10).
* `desktop/DesktopKit/.../KylinShell.swift` (372 lines SwiftUI): the shell composition we follow (panel -> start menu -> sidebar).
* LinPad is GPL-3.0 only because it is built on iSH; the spec is the author's own text. No Swift or iSH code is copied. Values in the spec are facts of the
  UKUI sources.

## 2. What can run on dwm and what cannot
| Upstream piece | Runs on dwm? | What we do |
|---|---|---|
| zorin-desktop-themes GTK CSS | yes (plain GTK3/4 CSS) | optional pack, recolour-free native theme; fallback: adw-gtk3 recoloured with the Zen palette |
| zorin-icon-themes | yes | optional pack |
| zorin-taskbar / Dash to Panel | **no** (St/Clutter, mutter) | original tint2 templates `zen-bottom` (icon-only, indicator line) + `carpatic-taskpreview` helper |
| Zorin Menu | **no** (St) | original GTK3 `carpatic-startmenu --skin zen` |
| Zorin Appearance / layouts | closed, n/a | one layout built: `zen` (Windows-like bottom taskbar, Zorin's default). The macOS-like and GNOME-like variants were NOT built (they would only re-skin the existing macOS / Ubuntu bars; the existing styles can already take the Zen palette, fonts and icons). |
| GNOME Shell theme (`gnome-shell.css`) | no | not used; notification style via dunst, panel via tint2 |
| ukui-panel / ukui-menu / ukui-sidebar (Qt, QML, KWin) | no (needs ukui-quick, kwin) | original tint2 templates + GTK start menu + GTK sidebar |
| ukui-gtk-theme, ukui-icon-theme, dark-sense | yes | optional packs (Debian pool, GPL-3) |
| KWin UKUI decoration | no | dwm `corner_radius=12`, `border` values and the `kylin` button style (NEEDS) |
| blur / 0.65 translucency | **needs a compositor** | documented gap: solid tint2/launcher backgrounds that mix the surface colour |

## 3. Licensing decisions
| Asset | Licence | Where it lives | Rule applied |
|---|---|---|---|
| Our code, templates, procedural wallpapers, palettes | MIT (repo) | `stylepacks/` | original; palettes are colour *facts* |
| Zorin GTK themes | GPL-2.0-or-later | `~/.local/share/themes/Zorin*` after `carpatic-pack install zorin-gtk` | separate data package, own `COPYING` placed next to it, never in the MIT tree |
| Zorin icons | CC-BY-SA-4.0 | `~/.local/share/icons/Zorin*` | separate data package; logo icons removed at install (modified copy is marked in `CARPATIC-MODIFIED.txt`) |
| UKUI GTK + icons + cursors | GPL-3 | `~/.local/share/{themes,icons}/ukui-*`, `dark-sense` | separate data package, copyright file kept; Kylin start-menu glyph (`kylin-startmenu*`) removed |
| Zorin / Kylin / openKylin logos, names in UI strings, Zorin "Z" and Kylin hexagon start glyphs | trademarks | never shipped | we draw an original start glyph; UI strings say "Zen" and "Kylin" in the style gallery |
| ubuntukylin-wallpapers, ukui-wallpapers, openkylin default wallpaper, Zorin wallpapers | NOASSERTION / unclear | never shipped | procedural wallpapers generated by `stylepacks/share/make-wallpapers.py` (pycairo, original) |
| FounderType system font , Zorin fonts | proprietary / n.a. | never shipped | Noto Sans (Kylin), Inter ; both OFL |

## 4. Names
`Zen` (profile id `zen`) and `Kylin` (profile id `kylin`, ships a dark variant as well). Both are neutral names that describe the look, the
inspiration is credited in the NOTICE text in `stylepacks/NEEDS.md`. If the lead prefers other labels only `LABEL=` in the two profile files changes.
