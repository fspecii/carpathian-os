# Sourced by lib/x.sh: make desktop tests independent of the configurator profile in the VM.
# neutral_on  : back up ~/.config/dwm-titus/themes.toml, force default_layout=tile and title bars on (right side)
# neutral_off : restore the original (or remove our override and reload defaults)
UCFG=/home/carpatic-rust-test/.config/dwm-titus
DCFG=/home/carpatic-rust-test/.local/share/dwm-titus/config/themes.toml
NBK=/tmp/carpatic-neutral.$$
neutral_set() { # key value  (replaces "key = ..." anywhere in the user file)
  sed -i "s|^$1 *=.*|$1 = $2|" "$UCFG/themes.toml"
}
neutral_on() {
  mkdir -p "$UCFG"
  if [ -f "$UCFG/themes.toml" ]; then cp "$UCFG/themes.toml" "$NBK"; else cp "$DCFG" "$UCFG/themes.toml"; : > "$NBK.none"; fi
  grep -q '^\[titlebar\]' "$UCFG/themes.toml" || printf '\n[titlebar]\nenabled = 1\n' >> "$UCFG/themes.toml"
  grep -q '^default_layout' "$UCFG/themes.toml" || sed -i 's|^\[appearance\]|[appearance]\ndefault_layout = "tile"|' "$UCFG/themes.toml"
  for kv in 'default_layout="tile"' enabled=1 tiled=1 floating=1 buttons=1 'button_side="right"' 'button_style="windows"' 'buttons_shown="all"' 'button_order=""' 'title_align="auto"' ; do
    k=${kv%%=*}
    grep -q "^$k *=" "$UCFG/themes.toml" || sed -i "s|^\[titlebar\]|[titlebar]\n$k = ${kv#*=}|" "$UCFG/themes.toml"
    neutral_set "$k" "${kv#*=}"
  done
  for kv in 'drag_tiled="float"' corner_radius=0 border_highlight=0 border_width=2 'border_active=""' 'border_inactive=""' inner_gap=8 outer_gap=8 smart_gaps=0; do
    k=${kv%%=*}
    grep -q "^$k *=" "$UCFG/themes.toml" || sed -i "s|^\[appearance\]|[appearance]\n$k = ${kv#*=}|" "$UCFG/themes.toml"
    neutral_set "$k" "${kv#*=}"
  done
  chown -R carpatic-rust-test "$UCFG"; sleep 2.5
}
neutral_off() {
  if [ -f "$NBK.none" ]; then cp "$DCFG" "$UCFG/themes.toml"; sleep 2.5; rm -f "$UCFG/themes.toml" "$NBK.none"
  elif [ -f "$NBK" ]; then cp "$NBK" "$UCFG/themes.toml"; chown carpatic-rust-test "$UCFG/themes.toml"; rm -f "$NBK"; sleep 2.5
  fi
}
