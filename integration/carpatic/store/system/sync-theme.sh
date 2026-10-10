#!/bin/sh
# Refresh the GTK theme copies used by the store GUI from the design system output (run on the host, then commit).
set -e
R=$(cd "$(dirname "$0")/../.." && pwd)
cp "$R"/design/tokens/out/gtk/colors-dark.css "$R"/design/tokens/out/gtk/colors-light.css "$R"/design/tokens/out/gtk/carpatic-widgets.css "$R/store/gui/theme/"
# Carpathian style layer (cp_* colours + cp-* classes) used when ~/.config/gtk-3.0/gtk.css has not been rendered yet
for m in dark light; do t=carpatic; [ $m = light ] && t=carpatic-light; "$R/gtktheme/bin/gtk-gen" carpatic 3 "$R/configurator/themes/$t/colors.toml" "$R/store/gui/theme/style-$m.css"; done
