#!/bin/sh
# Generates share/man/carpatic.1 from share/commands.tsv. Run: sh geek/tools/gen-man.sh > geek/share/man/carpatic.1
T=$(dirname "$0")/../share/commands.tsv
cat <<'M'
.TH CARPATIC 1 "" "Carpathian OS" "Carpathian OS manual"
.SH NAME
carpatic \- one command for the whole Carpathian desktop
.SH SYNOPSIS
.B carpatic
.RI [ area ]
.RI [ verb ]
.RI [ arguments ...]
.br
.B carpatic help
.RI [ area ]
.SH DESCRIPTION
.B carpatic
is a small router: it maps \fBcarpatic theme set nord\fR to \fBcarpatic-theme set nord\fR and so on.
Every tool it calls also works on its own, so scripts written against the old names keep working.
The list of commands is a plain text table (\fIcommands.tsv\fR); add a line to it to add a command.
.PP
Run \fBcarpatic\fR with no arguments to see every area, or \fBcarpatic help \fIarea\fR for the verbs of one area.
Press Super+Alt+Space for the same things as a menu, and Super+K for the keyboard shortcut cheat sheet.
.SH EXIT STATUS
.TP
.B 0
Done.
.TP
.B 1
The tool ran and failed. Its message says why.
.TP
.B 2
Carpathian did not understand what you typed. It suggests the closest command.
.TP
.B 3
The tool is not available on this computer (not installed, or needs hardware you do not have).
.SH AREAS AND VERBS
M
awk -F'|' '
/^#/ || /^$/ {next}
$1=="@area" { area[++n]=$2; desc[$2]=$3; next }
$1=="@default" {next}
{ rows[$1]=rows[$1] sprintf(".TP\n.B carpatic %s %s\n%s\n", $1, ($2=="*"?"[anything]":$2), $6) }
END { for (i=1;i<=n;i++) { a=area[i]; printf ".SS %s\n%s\n%s", a, desc[a] ".", rows[a] } }' "$T" | sed 's/-/\\-/g; s/^\\-\\-/\\-\\-/'
cat <<'M'
.SH COMPLETIONS
Completions for bash, zsh and fish are installed with the package. They ask \fBcarpatic \-\-complete\fR, so they follow the table above.
.SH FILES
.TP
.I ~/.config/carpatic/
Your settings, hooks, menu additions and web apps.
.TP
.I ~/.config/carpatic/hooks/
Executable scripts run on events: theme\-set, post\-update, screenshot, and more (\fBcarpatic hook list\fR).
.TP
.I ~/.config/carpatic/menu.d/
Your own entries for the menu.
.SH SEE ALSO
Run \fBcarpatic help \fIarea\fR for the verbs of one area, and \fBcarpatic tour \-\-guide\fR for the guide for power users.
.SH CREDITS
The idea of one router, a keyboard menu, hooks and theme sharing comes from Omarchy (MIT). See NOTICE.
M
