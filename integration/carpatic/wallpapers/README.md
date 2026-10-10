# Carpathian wallpapers

A wallpaper library, a CLI and a GTK3 widget. Sources: the Carpathian scenes (first and prominent), your own pictures, Wallhaven (safe for work only), generated colours.

![carpatic](../docs/screenshots/wallpapers-carpatic-dark.png)
![wallhaven](../docs/screenshots/wallpapers-wallhaven-live-light.png)
![detail](../docs/screenshots/wallpapers-wallhaven-live-detail-dark.png)

| Piece | What |
|---|---|
| `lib/carpatic_wallpapers/` | the Python module (standard library + GTK3/GdkPixbuf/cairo that the image already has; no `requests`, no Pillow) |
| `bin/carpatic-wallpaper` | CLI, routed as `carpatic wallpaper ...` (geek `commands.tsv`) |
| `bin/carpatic-wallpapers` | the window (`--tab carpatic|mine|wallhaven|colours`, `--mode dark|light`, `--shot FILE`) |
| `ui.WallpaperBrowser` | the reusable `Gtk.Box` the Settings app embeds on its Wallpaper page |

## Embedding (Settings app)
```python
from carpatic_wallpapers.ui import WallpaperBrowser, install_css
install_css("dark")                     # or "light"; loads design/tokens/out/gtk + the widget CSS
b = WallpaperBrowser(tab="carpatic")    # Gtk.Box, give it about 1000 x 860 px
b.connect("wallpaper-set", lambda b, path: ...)   # after settings.conf + the root window changed
b.connect("accent-picked", lambda b, hex: ...)    # the user pressed "Use as accent"
b.connect("toast", lambda b, text: ...)           # one plain-English line to show (errors, confirmations)
```
Everything slow runs on worker threads, so the widget never blocks the main loop. Without a toast handler nothing is shown for warnings: connect it.

## Interface with the rest of the desktop
- `settings.conf` keys: `WALLPAPER` (path, as before: `carpatic-apply` and the theme picker row keep working) and the new `WALLPAPER_MODE` (`fill|fit|stretch|center|tile`).
- `~/.config/carpatic/wallpapers/state.json`: fill mode, per-theme picture, light/dark pair, per-monitor pictures, rotation, collections. `library.json`: folders and files you added. `wallhaven.key`: optional API key, mode 600.
- Painting uses `xwallpaper` (per-output names) when installed, else `feh`; both through argv lists, never a shell. Changing the picture does not run `carpatic-apply` (no 0.5 s retint); the colours follow only when the user presses "Use as accent" (`carpatic-theme set <theme> --accent #hex`).
- Light/dark pair and per-theme pictures are resolved by `carpatic wallpaper sync` (see `NEEDS.md` for the two lines `carpatic-apply` needs so the right picture is painted first time).

## Library
- **Carpathian**: the 16 design scenes (8 x dark/light, matching mode first) then each theme's pictures (`themes/*/wallpaper*.jpg`, `backgrounds/`). The same picture shipped in two places is listed once.
- **My pictures**: `~/Pictures/Wallpapers` (always, removable) + any folders (`Add folder`, drag a folder in) + single files (`Add pictures`, drag a file in). Recursive to depth 4, at most 6000 files. A folder watcher (inotify) refreshes the grid by itself, debounced 0.6 s. Duplicates (identical sha256, hashed only when two files have the same size) get a "Duplicate" badge; pictures smaller than 90 % of the screen get a "Low resolution" badge and the card says "it will look soft". Facts per file (size, EXIF-corrected dimensions, hash) are cached by mtime+size in `~/.cache/carpatic/wallpapers/index.json`.
- **Drag and drop** onto the widget: files, folders, `file://` URIs, and `wallhaven.cc/w/ID` links (downloaded after the drop). Any other web address is refused with a plain message (nothing is fetched from arbitrary hosts).
- **Formats**: jpg, png, webp, gif, bmp, tiff always (gdk-pixbuf). avif, jxl, heic when a pixbuf loader exists or ImageMagick / `heif-convert` / `djxl` is installed (tried with argv lists); otherwise the tile says "Preview not available" and the card explains. Animated formats are listed (gif) but only the first frame is drawn and set.
- **Thumbnails**: 320 x 200 JPEG q85 in `~/.cache/carpatic/wallpapers/thumbs`, key = path + mtime + size + geometry, made by 2 to 3 worker threads, newest request first, never for off-screen cells. The grid then scales them to the cell size off the main thread and keeps a bitmap per finished cell.
- **Colours**: 12 presets (solid and gradients) and your own two colours; rendered with cairo at your screen's size to `~/.config/carpatic/wallpapers-generated/`.

## Wallhaven (https://wallhaven.cc/help/api)
- **SFW only, by construction**: every request has `purity=100`, there is no setting for anything else, and the parser drops any item whose `purity` is not `sfw`. Default categories: general only (anime, people are checkboxes).
- Sorting: top list (with Day, 3 days, Week, Month, 3 months, 6 months, Year), latest, random (seed kept across pages), relevance, most viewed, most favourited. Size filter defaults to "at least my screen" and shape to "my screen" (nearest Wallhaven ratio); colour chips (the 29 Wallhaven colours); search text with tags (`+forest -city @user id:123`), suggestions from a curated list plus tags of pictures you opened (Wallhaven has no autocomplete endpoint).
- Infinite scroll (next page when the end is within 360 px), skeleton tiles while loading, friendly offline banner with "Try again", last results shown from the cache when offline.
- Detail view: large preview (`th.wallhaven.cc` large thumbnail, still no full-size download), resolution, size, views, favourites, uploader, tags (click to search), original source link, **Set as wallpaper**, **Download**, **Add to my wallpapers** (download + the "Wallhaven picks" collection), **Open on wallhaven.cc**.
- Downloads go to `~/Pictures/Wallpapers/Wallhaven/wallhaven-<id>.<ext>` with `<file>.json` (page, original source, uploader, tags, attribution, licence note). The OS bundles **no** Wallhaven pictures; the tab and the detail page say that pictures belong to their creators.
- Safety: https only to `wallhaven.cc`, `w.wallhaven.cc`, `th.wallhaven.cc` (also across redirects; user-info and other ports refused); 15 s timeouts; JSON max 2 MB, thumbnails 2 MB, full image `min(80 MB, 2 x declared size + 1 MB)`; type sniffed from the first bytes (jpeg/png/webp) before anything is written or decoded; `.part` file removed on any failure; dimension cap 20000 px; no remote string reaches a shell; ids must match `^[a-z0-9]{4,10}$`.
- API key (optional): Filters popover or `carpatic wallpaper wallhaven key set` (reads stdin). Stored in `~/.config/carpatic/wallpapers/wallhaven.key`, mode 600, sent as the `X-API-Key` header only, never in a URL, never in the repo or `settings.conf`. NSFW is not offered anywhere (the key does not change that).
- Politeness: token bucket 40 requests/min (burst 8; the API allows 45), search responses cached 5 min on disk with `ETag`/`Last-Modified` revalidation (Wallhaven currently sends neither, so in practice it is a 5-minute TTL), details cached 1 h, thumbnails come from the CDN and are not API calls. Typical use: one request per tab visit, per filter change, per scrolled page, and one per opened picture.

## CLI
```
carpatic wallpaper list [carpatic|mine|all] [--json]
carpatic wallpaper set <path|id|title> [--fill MODE] [--monitor NAME] [--theme] [--light|--dark]
carpatic wallpaper fill fill|fit|stretch|center|tile
carpatic wallpaper add <file|folder|wallhaven link|wallhaven:ID>    remove <file|folder>
carpatic wallpaper next | random
carpatic wallpaper rotate on [--every MIN] [--collection NAME] [--no-shuffle] [--login] | off | status
carpatic wallpaper collection list|new|add|rm|show
carpatic wallpaper wallhaven search QUERY [--sort S] [--range R] [--page N] [--all-sizes] [--category general|anime|people] [--json]
carpatic wallpaper wallhaven get ID [--set] [--no-download]      wallhaven key set|clear
carpatic wallpaper accent [path] [--apply]     pair light PATH dark PATH | pair off     sync     thumbs [--prune]
```
Rotation: `rotate on` starts a tiny daemon (`rotate daemon`, wakes every 20 s, reads the state each time so `off` is immediate); collections are `carpatic-mode` (Carpathian scenes of the current dark/light mode), `carpatic-dark|light`, `my-pictures`, `all`, or your own. Shuffle keeps one pass through the whole list before repeating. "At login" runs `carpatic wallpaper rotate login` from the session (NEEDS).

## Accent from wallpaper
A 48 px copy is cut into 6 boxes by median cut (clearly separate colour clusters are split at the gap, smooth gradients at the median); the most vivid colour with a visible share is chosen and its lightness moved until it has at least 3:1 contrast on the dark (`#11151c`) or light (`#ffffff`) surface. Grey pictures give no suggestion and the card says so.

## Tests
`wallpapers/tests/run.sh` (also suites `wallpapers-logic` quick, `wallpapers` standard in `tests/run.sh`):
- `test_core.py`: 48 offline checks: limiter, header parsing and EXIF, Wallhaven parse/query/URL safety/cache/ETag/offline/limits/key mode on **recorded API fixtures** (`tests/fixtures/`), library scan/hash/duplicates/index/inotify, thumbnails (crop, cache, bad files, decompression bomb), colour sampling, settings round trip, pair/per-theme/per-monitor, rotation, CLI. `WALLPAPERS_LIVE=1` adds one live Wallhaven search (skipped by default and when offline).
- `test_ui.py`: 8 GTK checks on a private Xvfb (never your display; `uiharness.py` refuses otherwise): selection and fill, keyboard, drag and drop + inotify + duplicates + low-res, Wallhaven skeleton/infinite scroll/detail/download/set (no full-size fetch before the click), offline message, API key file mode, colours, 600-picture scroll timing.
- `shots.py DIR` renders the documentation screenshots from the fixtures.
