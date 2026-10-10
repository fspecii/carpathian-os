# Hardware test plan: suspend, hibernate and battery (15 minutes)

QEMU proves the Linux side (swap, resume parameters, the initramfs, elogind, our scripts). It cannot prove that a real
laptop's graphics chip, Wi-Fi card, touchpad, fingerprint reader or firmware come back. This page is for a human with a
laptop and a Carpathian USB stick or an installed system.

You need: the laptop on AC power, a second device with a stopwatch, and a USB stick or a note app to write results
(copy the table at the bottom).

## 0. Before you start (2 min)

1. Boot Carpathian, log in, open a terminal (Super+Shift+Return).
2. In BIOS/UEFI setup make sure **Secure Boot is OFF** (Carpathian kernels are not signed yet; with Secure Boot the kernel
   goes into lockdown and refuses to hibernate). Setup key is usually F2, F10 or Esc at power-on (HP: Esc then F10).
3. Run `doas carpatic-power doctor`. Read the lines marked `[FAIL]`; each has a "->" fix. The usual fix is:

       doas carpatic-power hibernate-setup
       doas reboot

   then `carpatic-power doctor` again. Goal: "hibernate should work".

## 1. Suspend (S3 / s2idle) (3 min)

Run `cat /sys/power/mem_sleep`. `[deep]` means classic S3 (best battery); `[s2idle]` only means "modern standby"
(drains maybe 1 to 3 % per hour; many 2020+ business laptops).

| # | Do | Pass when |
|---|----|-----------|
| 1.1 | Start a terminal clock: `while :; do date; sleep 1; done`. Run `carpatic-power sleep suspend` | Screen goes dark within 5 s, power LED pulses/changes |
| 1.2 | Wait 30 s, press a key or the power button | Screen back in under 3 s, lock screen asks for a password if lock is enabled |
| 1.3 | After unlock | Clock continues with a jump of about 30 s, terminal intact, keyboard works, touchpad moves the cursor |
| 1.4 | Check Wi-Fi: `ping -c3 1.1.1.1` (give it 10 s) | Reconnects by itself |
| 1.5 | Play a sound (`speaker-test -t sine -l1` or a browser video) | Audio works after resume |
| 1.6 | Close the lid (battery) | Suspends within 2 s, opening the lid wakes it |
| 1.7 | Close the lid with an external monitor plugged in | Does NOT suspend (docked) |
| 1.8 | Brightness keys, keyboard backlight keys | Work before and after suspend |

If the machine **does not wake** (black screen, fan spins): note the model, `uname -r`, `cat /sys/power/mem_sleep`, and
retry with `echo s2idle | doas tee /sys/power/mem_sleep` then suspend again. Report both outcomes.

## 2. Hibernate (4 min)

| # | Do | Pass when |
|---|----|-----------|
| 2.1 | Open 3 terminals and a text editor with unsaved text (a big `cat > /tmp/note` is fine), start `top` in one | |
| 2.2 | `free -h` and note the used memory | |
| 2.3 | `carpatic-power sleep hibernate` | Screen off, disk light busy for a few seconds (about 1 s per GB), then the machine powers OFF completely (no LED) |
| 2.4 | Press the power button | Firmware logo, boot loader, (LUKS passphrase if encrypted), then "Resume from disk" text instead of a normal boot. 10 to 30 s |
| 2.5 | After resume | The 3 terminals, `top` and the unsaved text are exactly as left. `uptime` is not reset |
| 2.6 | Graphics | Desktop redraws correctly, no corruption, external monitor comes back after replug if not by itself |
| 2.7 | Wi-Fi/Bluetooth: `ping -c3 1.1.1.1` | Online within 15 s |
| 2.8 | `dmesg | grep -iE "PM:|hibernat|resume"` | No "Failed to", no "Error -"; "PM: Image restored successfully" is present |
| 2.9 | Do 2.3 to 2.5 a **second** time right away | Works again (some drivers only fail on the 2nd cycle) |

If the image is "not found" and the system boots normally, resume parameters are wrong: run `doas carpatic-power doctor`.
**Never** run `fsck` or mount the disk from another OS between hibernate and resume: Linux will lose the saved session
(and a Windows "fast startup" dual boot makes this risky: disable Fast Startup in Windows if dual-booting).

## 3. Battery and profiles (3 min)

| # | Do | Pass when |
|---|----|-----------|
| 3.1 | `carpatic-power status` on AC | "AC connected", profile "auto (currently performance)" |
| 3.2 | Unplug the charger | Within 5 s `carpatic-power profile` reports balanced; status says "on battery" |
| 3.3 | Replug | Back to performance |
| 3.4 | `carpatic-power profile saver`, run `cat /sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference` | `power` |
| 3.5 | Watch power draw: `doas powertop` (Overview tab), or status "remaining ... at N W" | Idle desktop on battery: roughly 4 to 8 W on a modern 14" business laptop with screen at 50 %; note your number |
| 3.6 | `carpatic-power battery-limit 80` | Either "charge stops at 80 %" or the explanation that this firmware only offers it in the BIOS |
| 3.7 | Low battery (optional, 20 min): drain to 15 % unplugged | Notification "Battery low", saver profile |
| 3.8 | Low battery critical (optional): continue to 5 % | Notification, then the machine hibernates (or suspends if hibernate is not ready) |

## 4. HP EliteBook and other business laptops

These are the machines the project is developed on, and they have specific traits.

- **Firmware:** HP BIOS has "Secure Boot Configuration" (turn off Secure Boot, keep UEFI mode, set "Legacy Support" OFF).
  Also check *Advanced > Power Management Options*: "S5 Maximum Power Savings" must not block wake-on-power-button.
- **Sleep type:** Intel 11th gen and newer EliteBooks often expose only `s2idle` ("Modern Standby"); S3 may be hidden
  unless the BIOS has "Sleep State: Linux/S3" (not all do). s2idle works but wakes more often; the 60 minute
  `carpatic-power sleep suspend-then-hibernate` mode is the right everyday choice here (suspend, and after one hour
  hibernate to stop the drain).
- **Wi-Fi (Intel AX2xx):** resumes fine with `iwlwifi`. Realtek USB dongles and some Mediatek cards need the driver unloaded
  before sleep; set `SLEEP_UNLOAD_MODULES="name"` in /etc/carpatic/power.conf if 1.4 fails (find the name with `lspci -k`).
- **Fingerprint reader (Synaptics/Validity):** unsupported by `fprintd` on musl in Carpathian today; the sleep cycle
  must not hang because of it. Check that 1.2 returns within 3 s.
- **Touchpad (Synaptics/ELAN I2C-HID):** after resume taps/clicks must work. A pad that stays dead needs
  `i2c_hid` reload; note it. (Known on this project: phantom taps, see the touchpad notes.)
- **Dock (HP USB-C / Thunderbolt):** suspend with the dock connected; after resume external monitors and the USB keyboard
  must return. Hibernate with a Thunderbolt dock plugged in is the single most common failure: test both docked and undocked.
- **Battery:** HP provides **Battery Care / Adaptive Battery Optimizer** only in the BIOS (no `charge_control_end_threshold`
  in Linux on most models), so `carpatic-power battery-limit` will explain that and you set it in the BIOS.
- **Discrete GPU (EliteBook 8xx G9/G10 with NVIDIA/AMD):** proprietary NVIDIA does not run on musl, use the open drivers
  (`nouveau`, `amdgpu`) and record whether the dGPU wakes after hibernate (`lspci -k` shows the driver in use).
- **Lid + dock + external monitor:** closing the lid with an external display must keep the session (rule 1.7).

## 5. What only real hardware can show (we could not verify these in QEMU)

Graphics resume (Intel/AMD/NVIDIA), Wi-Fi and Bluetooth resume, audio resume, touchpad/keyboard I2C resume, USB/Thunderbolt
devices, fingerprint reader, camera, lid sensor, battery gauge accuracy, real power draw numbers, firmware S3 vs s2idle, charge
thresholds, thermal behaviour after resume, the "disk light" hibernate time on a slow SSD, whether firmware keeps the RTC alarm
for `suspend-then-hibernate`, and display brightness restoration.

## Result sheet (copy, fill, send back)

    Laptop model / BIOS version:
    Kernel (uname -r):                       mem_sleep:
    Disk (NVMe/SATA), encrypted? (y/n), RAM:
    doctor result:
    1.1-1.8 suspend:      PASS / FAIL (which)
    2.3-2.9 hibernate:    PASS / FAIL (which)  time to power off: ___ s  time to resume: ___ s
    3.x battery/profile:  PASS / FAIL (which)  idle watts on battery: ___
    Notes (dmesg lines for any failure):
