#!/bin/sh
# System configuration that goes with installer/packages/daily.txt (idempotent, run as root).
set -u
# time sync (G5): a laptop that has been off for a week must not show the wrong date, TLS needs a correct clock
rc-update add chronyd default >/dev/null 2>&1 || true
rc-service chronyd start >/dev/null 2>&1 || true
# manual page database (mandoc), quietly, so `apropos` and `man -k` work on first use
command -v makewhatis >/dev/null 2>&1 && makewhatis /usr/share/man >/dev/null 2>&1 || true
# pcsc daemon for smartcards / YubiKey (E5)
rc-update add pcscd default >/dev/null 2>&1 || true
rc-service pcscd start >/dev/null 2>&1 || true
# printing (E1): CUPS at boot, human users may add printers, built-in "Save as PDF" printer.
# avahi (mDNS) is NOT started at boot: it would answer on every network. Settings > Printers > "Add a printer" starts it for the session when
# the person asks to search the network (docs/SECURITY.md, residual risk 7).
rc-update del avahi-daemon default >/dev/null 2>&1 || true
rc-service avahi-daemon stop >/dev/null 2>&1 || true
rc-update add cupsd default >/dev/null 2>&1 || true
rc-service cupsd start >/dev/null 2>&1 || true
getent group lpadmin >/dev/null 2>&1 && addgroup root lpadmin >/dev/null 2>&1
getent group lpadmin >/dev/null 2>&1 && awk -F: '$3>=1000 && $3<60000 {print $1}' /etc/passwd | while read -r u; do addgroup "$u" lpadmin >/dev/null 2>&1; done
[ -f /etc/cups/cups-pdf.conf ] && ! grep -q '^Out ' /etc/cups/cups-pdf.conf && echo 'Out ${HOME}/PDF' >> /etc/cups/cups-pdf.conf
[ -f /usr/lib/cups/backend/cups-pdf ] && chmod 700 /usr/lib/cups/backend/cups-pdf
if command -v lpadmin >/dev/null 2>&1 && [ -f /usr/share/ppd/cups-pdf/cups-pdf.ppd ] && ! lpstat -p Save-as-PDF >/dev/null 2>&1; then
  for _ in 1 2 3 4 5; do lpstat -r >/dev/null 2>&1 && break; sleep 1; done
  lpadmin -p Save-as-PDF -D "Save as PDF" -L "The PDF folder in your home folder" -E -v cups-pdf:/ -P /usr/share/ppd/cups-pdf/cups-pdf.ppd >/dev/null 2>&1 || true
fi
# firmware updates (I3): fwupd talks to the Linux Vendor Firmware Service
# fwupd is started by D-Bus on demand (verified): keeping it running at boot would cost about 44 MB of RAM for nothing
rc-update del fwupd default >/dev/null 2>&1 || true
mkdir -p /etc/carpatic; echo "daily-config 1" > /etc/carpatic/daily-installed
exit 0
