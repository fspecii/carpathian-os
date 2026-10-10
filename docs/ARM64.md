# ARM64 development images

The ARM target is little-endian AArch64 Linux/musl with UEFI. The experimental
image boots the existing Rust desktop from a RAM-backed live system. It does
not yet install to disk. Raspberry Pi boot firmware, Apple Silicon boot support,
Secure Boot signing and physical hardware qualification are separate work.

`scripts/build-native-prebuilt.sh` builds all five native desktop components on
an Alpine x86_64 or aarch64 system. Build dependencies are `cargo rust build-base
pkgconf python3 libx11-dev libxext-dev libxfixes-dev libxi-dev gtk+3.0-dev`.
Set `CARPATIC_NATIVE_OUTPUT` to a new absolute directory. The pinned Cargo.lock
is required. The packaging verifier rejects foreign ELF architectures and
incompatible executable loaders before installation.

`scripts/build-arm64-iso.sh` remasters a verified official Alpine ARM64 ISO.
It preserves the original ARM UEFI boot image and never overwrites an existing
ISO. Inputs are:

- `CARPATIC_ARM_BASE_ISO`: official Alpine aarch64 standard ISO.
- `CARPATIC_ARM_BASE_SHA256`: published checksum, verified against downloaded bytes.
- `CARPATIC_ARM_PREBUILT_DIR`: five ARM native files and their `SHA256SUMS`.
- `CARPATIC_ARM_APK_DIR`: offline repositories with `main/aarch64` and
  `community/aarch64`, original signed indices, matching signed APK closure,
  empty `.boot_repository` markers in both repository directories, and a root
  `SHA256SUMS` covering every index and APK.
- `CARPATIC_ARM_WORLD`: explicit runtime package names whose complete dependency
  closure is present offline. Verify indices and every APK with native `apk verify`
  and the official release aarch64 keys before packaging; never use
  `--allow-untrusted`.
- `CARPATIC_ARM_ISO_OUTPUT`: new absolute ISO path (optional).

The default kernel is `lts`; `CARPATIC_ARM_KERNEL=virt` selects the smaller
upstream virt medium for VM-specific development. The public live image enables
no SSH daemon and contains no SSH authorization keys. Its local live account is
`carpathian`; changes are lost on reboot.

For isolated boot tests, clone a fresh blank QCOW2 using `scripts/vm-test.sh
--name NAME clone --arch aarch64 --base DISK --key KEY --port PORT`. ARM start
requires explicit `--qemu`, `--firmware-code` and `--firmware-vars` paths. Firmware
code is read-only; writable variables belong to the fixture. Use loopback-only
ports and destroy the fixture after testing. On an x86 host this uses QEMU TCG;
emulated timings do not measure native ARM performance.

An ARM build and an EFI boot do not establish a working desktop. Record the
running kernel architecture, installed file hashes, Xorg renderer and session
processes, then exercise Settings, calendar, file desktop and native helpers.
Disk installation and physical machine support must remain explicitly
unqualified until tested.
