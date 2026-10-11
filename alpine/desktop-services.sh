#!/bin/sh
# Enable desktop authorization services for the next boot; preserve live sessions.
set -eu
[ "$(id -u)" = 0 ] && [ -f /etc/alpine-release ] || {
    echo 'Run inside Alpine as root.' >&2
    exit 1
}
for service in cgroups dbus elogind polkit; do
    [ -x "/etc/init.d/$service" ] || {
        echo "Required desktop service is missing: $service" >&2
        exit 1
    }
done
[ -x /usr/libexec/elogind/elogind ] || {
    echo 'Required desktop daemon is missing: elogind' >&2
    exit 1
}
rc-update add cgroups boot
for service in dbus elogind polkit; do
    rc-update add "$service" default
done
