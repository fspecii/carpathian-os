# Carpathian OS

An Alpine Linux desktop with an original Rust X11 window manager, tiling and floating layouts, workspaces, desktop settings, themes and integrated applications.

Carpathian OS is in early development. Experimental images are for evaluation in a disposable VM; animation continuity, hardware compatibility and recovery qualification remain underway. Rust alone does not establish a performance advantage.

## Build

Requirements: Rust, Cargo, an X11 development environment and the dependencies listed by the Alpine installation scripts.

```sh
. scripts/rust-env.sh
cargo build --release --locked
```

For an isolated Alpine machine or VM, install with `CARPATIC_USER=youruser sh alpine/install.sh` as root, then select the desktop session at login. Existing `carpatic-*` command and package names remain compatibility interfaces.

ARM64 UEFI development live media and native payload builds are documented in [ARM64 development](docs/ARM64.md). ARM images are experimental; disk installation and physical hardware support remain unqualified.

## Test

```sh
tests/run.sh --quick
```

GUI checks run on private Xvfb displays. Never start the window manager inside an existing desktop session. Native Alpine and compositor tests use disposable VM fixtures; see [Testing](tests/README.md).

## Project

[Architecture](docs/ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md) · [Website](https://carpathianos.com) · [Releases](https://github.com/fspecii/carpathian-os/releases)

Original project code is MIT licensed. Adapted components and third-party assets retain their own licenses and attribution; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
