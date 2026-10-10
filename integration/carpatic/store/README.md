# Carpathian App Store

One place for system apps (apk, Alpine repos) and Flatpak apps (Flathub). Newbie-first: a curated catalog, bundles,
a graphical store, and a CLI for scripts.

```
store/
  catalog/*.toml          curated apps per category + bundles.toml (source = apk | flatpak | ai)
  lib/carpatic_store.py   catalog loader + apk/Flatpak backend (stdlib Python 3.11+)
  lib/carpatic_ai.py      AI tool installers, Ollama models, containers, doctor
  lib/carpatic_drivers.py hardware detection (GPU, microcode, Wi-Fi/BT firmware, print, scan, fingerprint)
  ai/                     tools.toml (recipes), models.toml (verified sizes), services/ (OpenRC for Ollama), RESEARCH.md
  gui/                    bundled Carpathian style layer (theme/style-*.css), token copies, app icon
  lib/carpatic_storeui.py the GTK3 GUI (see "GUI" below); RESEARCH.md = reference study
  bin/carpatic-store      CLI
  bin/carpatic-ai         AI CLI: status | install | remove | update | models | gpu | llama | webui | compat | doctor
  bin/carpatic-drivers    detect | install
  bin/carpatic-store-gui  launcher of the GTK3 front end
  carpatic-store.desktop  launcher entry
  system/                 setup-flatpak.sh (provisioning), xdg-runtime.sh, controller udev rules
  tests/                  guest tests, host runner, deploy helper, session-run helper
  NEEDS.md                requests to other agents
```

## Install
As root on a machine with the desktop provisioned: `sh store/system/setup-flatpak.sh` (idempotent). It installs Flatpak, bubblewrap,
xdg-desktop-portal(+gtk), pipewire(+pulse, wireplumber), mesa/vulkan (software + DRI), adds the system-wide Flathub remote, installs the
controller udev rules, the CLI, the GUI, the catalog and the launcher entry.

## CLI
```
carpatic-store list [category] [--installed] [--json]
carpatic-store search <words> [--all]      # --all also searches all of Alpine and Flathub (as a normal user: through the per-user Flathub remote; the first search prints "Updating the app list...")
carpatic-store info <app>
carpatic-store install <app|bundle|apk:pkg|flatpak:app.id>... [--dry-run]
carpatic-store remove <app>...
carpatic-store update [--check]            # apk update+upgrade and flatpak update
carpatic-store bundles
carpatic-store firstrun [--tui|--gui] [--bundles a,b] [--apps x,y] [--print]
carpatic-store doctor
```
`-y/--yes` never asks questions. Failures give one human sentence (no internet, disk full, unknown app with suggestions).
Flatpak apps are installed per user (`flatpak --user`, no root, no polkit prompt); apk apps use root (or `doas` for wheel users).

## Why GTK3 for the GUI
GTK3 and `py3-gobject3` are on Alpine, are already pulled in by Flatpak/portal packages (so no extra weight), render natively under
X11 with real app icons from the icon theme, and a dark CSS skin matches the dwm palette. rofi/yad menus cannot show an
"installing..." state per app, and a TUI is less friendly to newcomers. The GUI has: Home (bundles + newcomer picks), Bundles,
category pages, search, Installed, Updates, per-app spinner + "Installing..." state, remove, open, an administrator password
prompt for apk apps, and a first-run checklist page.

## Findings: Flatpak on Alpine (musl), verified in the VM (Alpine 3.24.2, QEMU virtio-vga, no real GPU, no sound card)
| Area | Result |
|---|---|
| Install | `apk add flatpak` works; Flathub remote added; user installs need no polkit. `XDG_DATA_DIRS` is set by `/etc/profile.d/flatpak.sh` (package) so launchers that read it see Flatpak apps. |
| glibc vs musl | The host stays musl. Flatpak apps ship their own glibc runtime (`ldd` inside the sandbox: glibc 2.44), so glibc-only apps run. VERIFIED: Calculator, Spotify (login screen), Steam (updated itself, sign-in screen), Discord (login screen). |
| Big install | Steam end to end: about 4 GB on disk (Platform 720 MB, GNOME runtimes, GL + GL32, Compat.i386, codecs). Discord and Spotify installed too (screenshots). Lutris installed through the GUI (1 GB). |
| Sandbox | bubblewrap works unprivileged (user namespaces enabled in the Alpine kernel). Portal daemons (document, desktop, gtk) start on demand with a dbus session. Harmless message while installing "extra-data" apps (Spotify, Discord): `lseek error in child setup`. |
| GPU / OpenGL / Vulkan | In this VM there is no GPU passthrough; apps fall back to software (llvmpipe/lavapipe, mesa `radv` init errors in logs are expected). Electron apps (Discord) crash with "GPU process isn't usable" and needed `--disable-gpu` here; this is a VM limitation, real GPUs unverified. Flatpak brings its own Mesa (`org.freedesktop.Platform.GL.default`), so host Mesa matters only for the DRI driver / kernel side. On real AMD/Intel hardware install `mesa-dri-gallium mesa-vulkan-*` (done by setup). NVIDIA proprietary on musl: not possible; nouveau/NVK only (Flatpak GL extension `nvidia-*` needs the matching glibc host driver version, untested). |
| 32-bit | Not needed on the host. Steam pulls `org.freedesktop.Platform.Compat.i386` and `GL32` runtimes via Flatpak (verified installed). |
| Audio | `pipewire`, `wireplumber`, `pipewire-pulse` start fine in the session and the pulse socket answers (`pactl info`: protocol 35). Real playback NOT verified (VM has no sound device). Nothing starts them automatically yet: see NEEDS.md. |
| Portals | `xdg-desktop-portal` + `-gtk` needed (file chooser, open-URI). "Open With" shows "No Apps available" when no default browser is configured. |

## What Steam needs on Alpine (summary)
1. `flatpak` + Flathub, `bubblewrap`, `xdg-desktop-portal(-gtk)` (setup script).
2. Mesa DRI (`mesa-dri-gallium`, and `mesa-vulkan-*` for your GPU: `-intel`, `-ati`, `-swrast` for software), `vulkan-loader`.
3. 32-bit runtime: automatic, inside Flatpak (Compat.i386, GL32). No multilib on Alpine required.
4. Controllers: `steam-devices` (apk) and our `/etc/udev/rules.d/60-carpatic-controllers.rules`; user in `input` group (desktop install does this); `uinput` access for Steam Input (`modprobe uinput`).
5. Audio: pipewire-pulse running. 6. At least about 10 GB free. 7. Proton/Wine: ProtonPlus or ProtonUp-Qt (Flatpak) install Proton-GE.
8. Game anti-cheat (EAC/BattlEye) on Proton is independent of the distro; musl is not involved inside the sandbox.

## Tests
`store/tests/run-host.sh [STORE_FULL=1] [STORE_RUN=1]` (see NEEDS.md for hooking into `tests/run.sh`). Result when last run:
See the Tests section below.
Screenshots: `docs/screenshots/store-*.png`.


## AI-ready (see `ai/RESEARCH.md` for all verified facts and the architecture decision)
One command or one click installs the AI tools; the user never picks a technique. Three hidden tiers: **native** (apk, static musl
binary or upstream installer) for Claude Code, Codex, OpenCode, Goose, Gemini CLI, Aider, Ollama, llama.cpp; a **rootless podman
container** for Open WebUI; a **glibc compatibility container** (distrobox, Ubuntu 24.04) for glibc-only software, CUDA and ROCm. When the system-wide `carpatic-compat` manager (compat/) is installed, `carpatic-ai compat` and the store recipe delegate to it (same box name and image); otherwise the store creates the box itself.

```
carpatic-ai status                      what is installed, GPU, Ollama service
carpatic-ai install claude-code codex   one or many (idempotent, progress, key guidance printed at the end)
carpatic-ai update [tool]               checks the upstream release, reinstalls only when newer
carpatic-ai remove <tool>
carpatic-ai models list|pull|run|rm     curated Ollama models with verified sizes, RAM and disk warnings
carpatic-ai llama serve model.gguf      llama.cpp server (Vulkan GPU when present)
carpatic-ai webui start|stop|status     Open WebUI container
carpatic-ai compat enter|run ...        glibc box
carpatic-ai doctor [--deep]             PATH, GPU, Vulkan, every tool runs, services, podman; --deep generates text
carpatic-drivers detect|install         GPU / microcode / Wi-Fi+BT firmware / printing / scanning / fingerprint
```
Bundles in the store: **AI Developer** (Claude Code, Codex, OpenCode, Ollama, llama.cpp + a 940 MB coding model), **Local AI**
(Ollama, llama.cpp, Open WebUI + llama3.2:1b, 1.3 GB, size warning shown first), **AI Coding Harnesses** (six terminal agents).
API keys are never stored: each tool's post-install note says to sign in or export the key in your own shell.
User tools install to `~/.local` (no root); `/etc/profile.d/carpatic-localbin.sh` puts `~/.local/bin` on PATH for shells and the X session.

### Honest limits
* NVIDIA proprietary driver and CUDA: impossible on musl; Vulkan through nouveau/NVK works in principle; the container CUDA path is designed, NOT tested (no NVIDIA hardware).
* AMD ROCm: not packaged for Alpine; only Vulkan (RADV) is native. Intel/AMD/NVK Vulkan paths are NOT tested on real GPUs (VM has llvmpipe only).
* Ollama from apk is the CPU build; GPU inference goes through llama.cpp Vulkan.
* LM Studio is offered as a Flatpak (starts; models and GPU use not tested). vLLM is not offered; it could only live in the compat container.
* System (apk) steps need root or doas: the GUI asks for the password (kept in memory, used via a pty, never written to disk).
* Claude Code is proprietary; Open WebUI has a branding clause licence; see the table in RESEARCH.md.

### Catalog source types
`apk` (Alpine package), `flatpak` (Flathub, per-user), `ai` (Carpathian recipe in `ai/tools.toml`), `compat` (glibc-only software through
`carpatic-compat`: `pkg` is an apt name, a URL to a .deb/AppImage or a local file; `remove_as` the apt name for removal; the launcher entry
is created by carpatic-compat). Direct refs work on the CLI: `carpatic-store install apk:htop flatpak:org.gnome.Calculator compat:x11-apps`.
Example: Google Chrome (`id = "chrome"`) installs its own .deb in the Ubuntu box and gets a normal launcher entry (verified).
`carpatic-ai compat` is a thin wrapper over `carpatic-compat` (the store no longer creates containers itself; boxes made earlier carry over).

## GUI (redesigned: OS style layer, no webkit)
`lib/carpatic_storeui.py` (launched by `bin/carpatic-store-gui`). The look comes from the OS: the user's `~/.config/gtk-3.0/gtk.css` (rendered by
`carpatic-apply`) defines the `@cp_*` colours and the shared `cp-card`, `cp-primary`, `cp-sidebar(-row)`, `cp-section`, `cp-search`, `cp-badge` classes for the six
styles (macos, windows, ubuntu, zen, kylin, carpatic) in light and dark; the store adds only `st-*` layout classes on top, so a style or accent change restyles it
live. When that file is not rendered yet (first boot, tests) the bundled `gui/theme/style-{dark,light}.css` (Carpathian style, from `gtktheme/bin/gtk-gen`, refresh with
`store/system/sync-theme.sh`) is used. Research and measurements: `RESEARCH.md`.

Pages: **Discover** (hero carousel with arrows/dots, "AI tools, one click" strip, categories, games, drivers shortcut, bundles, good first picks), **AI & Agents**
(coding agents, run models locally, chat apps, advanced, curated Ollama models with sizes), **Bundles**, one page per category, **Installed** (grouped by source, Open/Remove),
**Updates** (count badge in the sidebar, list, Update everything), **Drivers & Hardware**, search (catalog first, then an explicit "Search all of Alpine and Flathub"),
and per-app **detail pages**: icon, name, source/state pills, Get/Open/Remove, a facts strip (source, download size, where it installs, licence), screenshots from Flathub,
About, the curated note, and for AI tools a "Getting started" card (install, command to type with a Copy button, sign-in note). Installs show in place: "Installing 62 %" and a
bar in the button's slot (Flatpak percentages, apk `(n/m)` steps, model pulls); no spinner dialogs. Errors are an inline banner (plain sentence, Try again, collapsed details),
successes an inline "is ready" banner with the next step. The administrator password dialog is styled and used once per session, never saved.
Keyboard: Ctrl+F focuses search, Esc leaves a detail page, arrows/Enter work in the sidebar.

Icons: real theme icons and Flathub icons when they exist; otherwise a designed, original family (no brand logos). AI tools get a gradient squircle with a white glyph and a small
monogram, one hue per kind (coding agents: terminal glyph in the accent hue; local models: flask in blue; chat apps: magenta; compat box: orange), with a small lightness shift per tool; other apps get a letter squircle.
Tooltips are drawn square with no shadow: GTK's rounded, shadowed tooltip is ghosted (double-drawn) on a window manager without a compositor.

### Test-session note (screen lock)
Long idle gaps in the test VM start `i3lock` through `xautolock` (10 min). The lock grabs keyboard and pointer, so the app looks frozen and xdotool clicks go nowhere; killing `i3lock` makes the window answer at once
(checked: no grab is held by the store). `test-gui-e2e.py` now keeps the screen awake.

### Host renders (no VM)
`store/tests/render-store.sh OUT.png [--page P | --detail ID | --search Q] [--mode dark|light] [--style CSS] [--demo] [--firstrun]` renders any page on a private Xvfb with a
throwaway HOME (never the real desktop). `--demo` fakes installed/downloading/updates so every state shows. Needs `adw-gtk3` and Papirus under `STORE_XDG` (a data dir with
`themes/` and `icons/`) for exact icons; without it a fallback theme is used. `store/tests/sheet.py` builds the side-by-side sheets (`docs/screenshots/ref-store-*.png`).

## Tests
* `tests/run.sh --suite store-logic` (host, 35 s): drivers logic + `store/tests/test_gui_host.sh`, 25 renders (every page, dark and light, errors, first run, bundled style) on Xvfb that fail on any GTK warning/CSS error or tiny image, plus the tagline rule.
* `tests/run.sh --suite store-gui` (VM, about 30-120 s, needs network): `store/tests/test-gui-e2e.py` drives the real window with xdotool pointer clicks: AI page, Get on Ollama, the administrator password dialog (typed), live progress, installed tile + "is ready" banner, search, detail page, Get on a small apk app; removes both afterwards through the store's own remove.
* `store/tests/run-host.sh [STORE_FULL=1] [STORE_RUN=1] [STORE_AI=1]` (see NEEDS.md). Last full run in the VM with `STORE_RUN=1 STORE_AI=1`:
**63 passed, 0 failed** (plus the host-side token contrast test, 22 checks) (catalog, CLI, apk and Flatpak round trips, Goose install/update/remove, drivers on fake AMD/Intel/NVIDIA/virtio sysfs,
Ollama OpenRC service + real model generation, llama-server, Open WebUI container health, glibc compat container, every GUI page starting).
Screenshots: `docs/screenshots/store-*.png`.
