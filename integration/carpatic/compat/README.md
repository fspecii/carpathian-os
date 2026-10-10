# carpatic-compat: run programs built for other Linux systems

Carpatic OS is built on Alpine Linux, which uses the *musl* C library. Most software on the internet (Google Chrome, Zoom, vendor
tools, AppImages, many developer SDKs) is built for *glibc* and will not start here ("required file not found").
`carpatic-compat` fixes that without you having to know anything about containers.

It keeps one small Ubuntu 24.04 "box" (a rootless Podman container managed by distrobox). The box shares your home folder, screen,
sound and clipboard. Apps you install in it show up in your launcher and command-line tools land on your PATH.

## Everyday use

| You want to | Type |
|---|---|
| Install a downloaded package (Chrome, Zoom, Teams, a vendor tool) | `carpatic-compat install ~/Downloads/google-chrome-stable_current_amd64.deb` (a web link works too) |
| Add an AppImage to your launcher | `carpatic-compat install ~/Downloads/Thing.AppImage` (or double-click it in the file manager and choose "Add to Carpatic") |
| Install something from Ubuntu's archive | `carpatic-compat install xournalpp` |
| Run one program that refuses to start | `carpatic-compat run ./vendor-tool --help` |
| Make a command-line tool work everywhere | `carpatic-compat wrap ~/tools/vendor-cli vendor`, then just type `vendor` |
| See what you added | `carpatic-compat list` |
| Remove something | `carpatic-compat remove xournalpp` |
| Update everything in the box | `carpatic-compat update` |
| Open a terminal inside the box | `carpatic-compat shell` |
| Start over (your files are not touched) | `carpatic-compat reset` |

The first time you use it, it asks for your password once to install Podman and friends, then downloads about 100 MB. After that
everything is offline-friendly: nothing needs the network except installing and updating.

## What works (verified in a VM, see docs/DAILY-DRIVER.md)
- A real Google Chrome `.deb`, a real Qt AppImage that fails natively, `x11-apps`, and a wrapped vendor script.
- Windows get Carpatic title bars and taskbar entries; sound reaches the host's PipeWire; `/dev/dri` is available inside the box.

## What does not
See [LIMITATIONS.md](LIMITATIONS.md): no NVIDIA proprietary/CUDA on the host, kernel-level anticheat, anything needing systemd inside the box,
and a few things nobody has tested on real hardware yet.

## How it fits together
- `bin/carpatic-compat`: the whole tool, POSIX sh.
- `system/compat-boot`, `system/carpatic-compat.initd`: boot-time preparation (tun, fuse, shared mount) for rootless containers.
- `install.sh`: puts it all in place; `--daily` also installs the daily-driver package set (`installer/packages/daily.txt`).
- Same container name (`carpatic-compat`) and image (Ubuntu 24.04) as the store's `carpatic-ai compat`, so there is only one box.
- Tests: `tests/suites/daily/` (`COMPAT_FULL=1` runs the AppImage test, which downloads 62 MB).

Settings through environment variables: `CARPATIC_COMPAT_IMAGE` (e.g. a Debian or Fedora image) and `CARPATIC_COMPAT_NAME`.

## Everyday tools that come with it
| Tool | What it does |
|---|---|
| `carpatic-system` | One window for Updates and restore points, Accessibility, Touchpad and Screen scale |
| `carpatic-update` | `check`, `list`, `apply`, `status`: safe updates, and "restart to finish updating" notices |
| `carpatic-rollback` | `snapshot`, `list`, `restore`, `delete`, `prune`: restore points on Btrfs installs |
| `carpatic-a11y` | Large text, high contrast, screen reader, on-screen keyboard, sticky/slow/bounce/mouse keys |
| `carpatic-touchpad` | Tap to click, tap and drag, natural scrolling, typing guard, scroll method, speed (safe defaults) |
| `carpatic-gestures` | Three- and four-finger swipes: workspaces and the app switcher |
