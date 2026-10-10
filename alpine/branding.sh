#!/bin/sh
# Install the shared desktop identity and original website mountain mark.
set -eu
cd "$(dirname "$0")/.."
icons=integration/carpatic/panel/assets/branding
mkdir -p /usr/share/carpatic/brand /usr/share/icons/hicolor/scalable/apps
install -m644 "$icons/carpathian-os.svg" /usr/share/carpatic/brand/carpatic-icon-light.svg
sed 's/fill="currentColor"/fill="#f5f7f2"/' "$icons/carpathian-os-symbolic.svg" > /usr/share/carpatic/brand/carpatic-icon-dark.svg
chmod 644 /usr/share/carpatic/brand/carpatic-icon-dark.svg
for name in carpathian-os carpatic; do
    install -m644 "$icons/carpathian-os.svg" "/usr/share/icons/hicolor/scalable/apps/$name.svg"
done
sh integration/carpatic/compat/system/brand-os
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || :

if [ -r /etc/hostname ] && [ "$(cat /etc/hostname)" = carpatic ]; then
    printf 'carpathian\n' > /etc/hostname
    hostname carpathian
fi
