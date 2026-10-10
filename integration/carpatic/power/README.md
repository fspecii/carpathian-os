# power/: suspend, hibernate and laptop power for Carpathian OS

One CLI (`carpatic-power`, POSIX sh, idempotent) plus OpenRC/elogind/udev/acpid/TLP config. Research and decisions: [RESEARCH.md](RESEARCH.md).
Integration requests for other agents: [NEEDS.md](NEEDS.md). Human test on a laptop (15 min): [HARDWARE-TEST-PLAN.md](HARDWARE-TEST-PLAN.md).

## Use
    carpatic-power status                 battery, AC, profile, swap, hibernate readiness
    carpatic-power doctor                 plain-words checks; says exactly why hibernate can or cannot work
    doas carpatic-power hibernate-setup   swap file (RAM size) + resume= params for limine/grub/syslinux; then reboot once
    carpatic-power sleep suspend|hibernate|hybrid|suspend-then-hibernate [min]
    carpatic-power profile performance|balanced|saver|auto       (auto: AC -> performance, battery -> balanced, <=20 % -> saver)
    carpatic-power menu                   rofi/dmenu power menu (Lock, Suspend, Hibernate if ready, Log out, Restart, Shutdown)
    carpatic-power brightness up|down|set N, kbd-backlight up|down, battery-limit [N|reset], lock
Config: `/etc/carpatic/power.conf` (thresholds, actions, delays). Install: `sh power/install.sh [--packages] [--hibernate]` (also `--root DIR`).

## What is in here
| Path | Role |
|---|---|
| `bin/carpatic-power` | the CLI, monitor loop (low/critical battery), elogind sleep hook, doctor |
| `etc/openrc/carpatic-power` | OpenRC service: boot-time profile + resume_offset self-heal + battery monitor (supervise-daemon) |
| `etc/udev/99-carpatic-power.rules`, `etc/acpi/carpatic-ac` | AC plug/unplug -> auto profile; backlight permissions for group `video` |
| `etc/tlp.d/10-carpatic.conf`, `etc/conf.d/zram-init` | TLP hardware saving (CPU left to us), zram swap pri 100 |
| generated: `/etc/elogind/{logind,sleep}.conf.d/10-carpatic.conf`, `system-sleep/50-carpatic` | lid/power key policy (laptop vs desktop), sleep modes, hook |
| `qemu-power.sh` | QEMU launcher with ACPI S3+S4 enabled (respects the VM slot rule; port 2253 because 2243 was taken by another project) |
| `tests/` | see below |

## Tests
    sh power/tests/run.sh                  74 VM-free checks (fake /sys,/proc,/boot): profiles, battery rules, boot loader editing, doctor, menu, hooks, install idempotency
    POWER_VM=1 power/tests/run.sh          + real S3/S4 in QEMU (needs a prepared running VM; see header of each script)
Hook for `tests/run.sh`: see NEEDS.md section 3 (suite wiring belongs to the tests agent).

## Verification log (QEMU, Alpine 3.24.2, kernel 6.18.55-lts) - logs in `logs/`, renders in `docs/screenshots/power-*.png`
| Scenario | Result |
|---|---|
| Hibernate+resume ext4 swap partition (q35, ACPI S4) | PASS |
| Hibernate+resume ext4 swap file | PASS |
| Hibernate+resume Btrfs swap file + LUKS2 + Limine, engine-installed disk | PASS (passphrase asked at resume) |
| S3 suspend + wake (ext4 and Btrfs/LUKS disks) | PASS |
| suspend-then-hibernate (own implementation, RTC alarm) | PASS on QEMU `pc`; on `q35` the RTC alarm wakes S3 immediately (QEMU quirk) so untestable there |
| elogind's native suspend-then-hibernate | BROKEN (suspends, never hibernates); disabled |
"PASS" = a worker process with a random token survives power-off: same PID, counter continues, same `boot_id`, RAM-only tmpfs data intact, `hibernation exit` in dmesg.

## NOT verified (needs real hardware, see HARDWARE-TEST-PLAN.md)
Graphics/Wi-Fi/Bluetooth/audio/touchpad/dock resume, real S3 vs s2idle firmware, battery gauge, charge thresholds, CPU profile knobs
(`energy_performance_preference`, `platform_profile`, turbo: only tested against a fake sysfs, VMs have no cpufreq), real slock lock-before-sleep,
low-battery notifications on a real battery, brightness keys. Not integrated yet by others: installer calling `hibernate-setup`, desktop hotkeys/menu (NEEDS.md).
