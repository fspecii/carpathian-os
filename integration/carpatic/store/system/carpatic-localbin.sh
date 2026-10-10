# Carpatic: per-user tools (Claude Code, Codex, OpenCode, Aider...) live in ~/.local/bin.
# Sourced from /etc/profile, which the X session (xinitrc) also sources.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) [ -n "$HOME" ] && export PATH="$HOME/.local/bin:$PATH" ;; esac
