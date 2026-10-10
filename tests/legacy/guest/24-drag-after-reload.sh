#!/bin/sh
# Regression: Super+drag (move and resize) must keep working on windows that existed BEFORE a config reload
# (the configurator's first apply rewrites the TOML files; the button grabs used to be lost until SIGUSR1).
. /tmp/carpatic-rust-legacy/lib/x.sh
a=$(spawn_st); xdotool key super+shift+space; sleep 1
# trigger the inotify reload the way carpatic-apply does: rewrite the user's hotkeys/themes files
H=/home/carpatic-rust-test/.config/dwm-titus
mkdir -p $H; [ -f $H/hotkeys.toml ] || cp /home/carpatic-rust-test/.local/share/dwm-titus/config/hotkeys.toml $H/hotkeys.toml
echo "# reload $$" >> $H/hotkeys.toml; neutral_set enabled 1; chown -R carpatic-rust-test $H; sleep 3
echo "# touch" >> $H/themes.toml; sleep 2
x0=$(gv $a X); y0=$(gv $a Y); w0=$(gv $a WIDTH); h0=$(gv $a HEIGHT)
drag 1 400 300 40 30
x1=$(gv $a X); y1=$(gv $a Y)
[ $((x1-x0)) -ge 40 ] && [ $((y1-y0)) -ge 30 ] || fail "Super+drag move dead after config reload ($x0,$y0 -> $x1,$y1)"
drag 3 $((x1+w0-30)) $((y1+h0-30)) -40 -30
w1=$(gv $a WIDTH); h1=$(gv $a HEIGHT)
[ "$w1" -lt "$w0" ] && [ "$h1" -lt "$h0" ] || fail "Super+right-drag resize dead after config reload (${w0}x$h0 -> ${w1}x$h1)"
sed -i '/^# reload /d;/^# touch$/d' $H/hotkeys.toml $H/themes.toml
