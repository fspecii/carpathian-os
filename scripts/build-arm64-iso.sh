#!/bin/sh
# ARM64 live development image; reuses verified upstream ARM UEFI boot media.
set -eu
cd "$(dirname "$0")/.."
project=$PWD
: "${CARPATIC_ARM_BASE_ISO:?Select the official Alpine aarch64 ISO}"
: "${CARPATIC_ARM_BASE_SHA256:?Provide its official SHA256}"
: "${CARPATIC_ARM_PREBUILT_DIR:?Select verified aarch64 native payloads}"
: "${CARPATIC_ARM_APK_DIR:?Select signed main/community offline repositories}"
: "${CARPATIC_ARM_WORLD:?Select the runtime world file}"
kernel=${CARPATIC_ARM_KERNEL:-lts}
case "$kernel" in lts|virt) ;; *) echo 'Kernel must be lts or virt.' >&2; exit 1;; esac
mkdir -p artifacts iso/out
run=$(mktemp -d "$project/artifacts/test-run-arm64-iso-XXXXXXXX")
out=${CARPATIC_ARM_ISO_OUTPUT:-$project/iso/out/carpathian-os-arm64-live-$(date +%Y%m%d-%H%M%S)-${run##*/}.iso}
case "$out" in /*.iso) ;; *) echo 'Output must be an absolute .iso path.' >&2; exit 1;; esac
for path in "$out" "$out.part" "$out.sha256"; do
    [ ! -e "$path" ] && [ ! -L "$path" ] || { echo "Refusing existing output: $path" >&2; exit 1; }
done
actual=$(sha256sum "$CARPATIC_ARM_BASE_ISO" | cut -d ' ' -f1)
[ "$actual" = "$CARPATIC_ARM_BASE_SHA256" ] || { echo 'ARM base checksum mismatch.' >&2; exit 1; }
(cd "$CARPATIC_ARM_PREBUILT_DIR"; sha256sum -c SHA256SUMS) >"$run/native-check.log"
python3 alpine/verify-prebuilt.py "$CARPATIC_ARM_PREBUILT_DIR" --arch aarch64 >>"$run/native-check.log"
(cd "$CARPATIC_ARM_APK_DIR"; sha256sum -c SHA256SUMS) >"$run/apk-check.log"
xorriso -indev "$CARPATIC_ARM_BASE_ISO" -ls "/boot/vmlinuz-$kernel" -ls "/boot/initramfs-$kernel" >"$run/kernel-inventory.log" 2>&1
grep -q "vmlinuz-$kernel" "$run/kernel-inventory.log" && grep -q "initramfs-$kernel" "$run/kernel-inventory.log" || { echo 'Base lacks the selected ARM kernel.' >&2; exit 1; }
python3 scripts/prepare-arm64-live.py "$run" "$CARPATIC_ARM_PREBUILT_DIR" "$CARPATIC_ARM_APK_DIR" "$CARPATIC_ARM_WORLD" --kernel "$kernel"
sha256sum "$CARPATIC_ARM_BASE_ISO" >"$run/base-input.sha256"
(set -C; : >"$out.part")
xorriso -indev "$CARPATIC_ARM_BASE_ISO" -outdev "$out.part" -boot_image any replay \
    -volid CARPATHIAN_ARM64_DEV \
    -map "$run/carpathian-live.apkovl.tar.gz" /carpathian-live.apkovl.tar.gz \
    -map "$run/carpathian-arm64-payload.tar.gz" /carpathian-arm64-payload.tar.gz \
    -map "$CARPATIC_ARM_APK_DIR/main" /apks/carpathian-main \
    -map "$CARPATIC_ARM_APK_DIR/community" /apks/carpathian-community \
    -map "$run/grub.cfg" /boot/grub/grub.cfg \
    -commit -end >"$run/remaster.log" 2>&1
ln "$out.part" "$out"
rm "$out.part"
(cd "$(dirname "$out")"; set -C; sha256sum "$(basename "$out")" >"$(basename "$out").sha256")
cp "$out.sha256" "$run/output.sha256"
printf 'Experimental ARM64 live image: %s\nEvidence: %s\n' "$out" "$run"
