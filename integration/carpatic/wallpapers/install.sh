#!/bin/sh
# Install the wallpaper library, the carpatic-wallpaper CLI and the carpatic-wallpapers window. Idempotent. Needs: python3, py3-gobject3, gtk+3.0,
# gdk-pixbuf (all already in the image for the configurator), py3-cairo. Optional: feh or xwallpaper (painting the root window), librsvg/webp-pixbuf-loader/
# libheif/libavif/libjxl pixbuf loaders (more picture formats).
set -e
here=$(cd "$(dirname "$0")" && pwd)
dest=${DEST:-/usr/local/share/carpatic/wallpapers}
bin=${BINDIR:-/usr/local/bin}
mkdir -p "$dest" "$bin" "${APPDIR:-/usr/local/share/applications}"
rm -rf "$dest/lib"; cp -R "$here/lib" "$dest/lib"; find "$dest/lib" -name __pycache__ -prune -exec rm -rf {} +
# the design tokens (generated CSS) the widget is styled with: copied from the checkout so there is one source of truth
mkdir -p "$dest/gtk"
for f in colors-dark.css colors-light.css carpatic-widgets.css; do
  for d in "$here/../design/tokens/out/gtk" "${TOKENS_DIR:-/nonexistent}"; do [ -f "$d/$f" ] && { cp "$d/$f" "$dest/gtk/$f"; break; }; done
done
for t in carpatic-wallpaper carpatic-wallpapers; do install -m 755 "$here/bin/$t" "$bin/$t"; done
install -m 644 "$here/share/applications/carpatic-wallpapers.desktop" "${APPDIR:-/usr/local/share/applications}/"
echo "wallpapers installed: $bin/carpatic-wallpaper, $bin/carpatic-wallpapers"
