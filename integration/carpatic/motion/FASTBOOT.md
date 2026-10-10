# Fast boot: hide the Limine menu when there is only one OS

Omarchy's `omarchy-setup-direct-boot` creates a UEFI boot entry straight to the kernel image (UKI) and refuses on firmware that cannot do it. Carpatic uses Limine, so the
same saving comes from the menu timeout. Limine's `timeout:` key is the whole feature.

## What the engine writes today and what it should write
Today (`installer/engine/carpatic-engine`, `install_splash`): `timeout: $BOOT_TIMEOUT` (3) at the top of `limine.conf`, in all three copies
(`/boot/limine/limine.conf`, `/boot/limine.conf`, `/boot/EFI/BOOT/limine.conf`).

Proposed default, one line in the engine (exact):

    # single OS: nothing to choose, start at once. Another OS present (free_space mode, or windows_entries printed anything): keep the 3 s menu.
    if [ "$MODE" = free_space ] || [ -n "$(windows_entries)" ]; then BOOT_TIMEOUT=3; else BOOT_TIMEOUT=${BOOT_TIMEOUT_SINGLE:-0}; fi

and nothing else changes in the file (`serial: yes`, the theme block and the entries stay). The same switch exists later for users: `carpatic-boot menu hide|show|status`
(root; Settings > Startup and screensaver > "Hide the boot menu"). It edits the three copies, keeps `limine.conf.carpatic-bak`, and **refuses to hide the menu**
when `limine.conf` lists any entry besides `Carpatic OS` and `Carpatic OS (recovery shell)`, when a partition looks like Windows (NTFS/BitLocker/MS reserved), or when
`efibootmgr` lists a Windows Boot Manager. 20 host checks in `motion/tests/test-boot.sh`.

## Measured (UEFI, OVMF + Limine, QEMU/KVM on a busy host; QEMU start until the init prints that the splash is up; `motion/tests/fastboot-lab.py`)
| Limine `timeout:` | Runs (s) | Median |
|---|---|---|
| 3 (today) | 10.54, 11.80, 10.95 | 10.95 s |
| 1 | 9.73, 10.14, 8.67 | 9.73 s |
| 0 | 8.73, 7.41, 8.57 | 8.57 s |
The saving is the timeout itself (about 2.4 of 3 s here; the rest is noise of the busy host). On the full `tests/perf` harness, boot to SSH was 16.9 to 20.8 s with the 3 s menu, so the menu is
roughly 15 percent of a cold boot. See the end of this file for the engine-installed VM run.

## Honest gaps
* **"Hold a key to show the menu" is NOT verified.** QEMU's `sendkey` could not make Limine show the menu at `timeout: 0` (keys sent as a held key and as repeated taps both
  left the machine booting or, with the key `a`, restarting; the experiment is inconclusive, not a proof that it fails). It has to be tried on real hardware with a real keyboard
  before `timeout: 0` becomes the default. Until then the safer default is `timeout: 1` (menu visible for one second, any key stops the countdown, saves about 1.2 s) or
  keeping 3. The recovery shell entry and the restore-point (rollback) menu entries live in this menu: **with the menu hidden they are only reachable if the key hold works**, otherwise
  through the live ISO. Do not flip the default without that test.
* Secure Boot / TPM sealed installs (docs/SECURE-BOOT-TPM.md) are unaffected: the menu is not part of the measured chain, but a hidden menu removes the user's way to pick an older kernel.
* BIOS (legacy) installs: Limine's BIOS path honours the same key; not measured.
