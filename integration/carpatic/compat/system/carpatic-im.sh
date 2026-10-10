# /etc/profile.d/carpatic-im.sh: environment for the chosen input method (see carpatic-input-method). Read at login.
_f="${XDG_CONFIG_HOME:-$HOME/.config}/carpatic/input-method"
case "$(cat "$_f" 2>/dev/null)" in
  fcitx5) export GTK_IM_MODULE=fcitx QT_IM_MODULE=fcitx XMODIFIERS=@im=fcitx SDL_IM_MODULE=fcitx GLFW_IM_MODULE=ibus;;
  ibus)   export GTK_IM_MODULE=ibus QT_IM_MODULE=ibus XMODIFIERS=@im=ibus;;
esac
unset _f
