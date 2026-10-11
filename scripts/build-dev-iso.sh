#!/bin/sh
# Development remaster only; reads the original ISO and writes a new image.
set -eu
cd "$(dirname "$0")/.."
project=$PWD
legacy=$(realpath "${CARPATIC_LEGACY_DIR:-$project/../carpatic-os}")
[ -d "$legacy/installer/engine" ] && [ -f "$legacy/NOTICE" ] || {
    echo 'Select the legacy installer source with CARPATIC_LEGACY_DIR.' >&2; exit 1;
}
base=${CARPATIC_BASE_ISO:-$legacy/iso/out/carpatic-latest.iso}
prebuilt=${CARPATIC_PREBUILT_DIR:-$project/artifacts/installer-prebuilt}
apks=${CARPATIC_APK_DIR:-$project/artifacts/installer-apks}
update_latest=${CARPATIC_UPDATE_LATEST:-0}
case "$update_latest" in 0|1) ;; *) echo 'CARPATIC_UPDATE_LATEST must be 0 or 1.' >&2; exit 1;; esac
mkdir -p iso/out artifacts
run=$(mktemp -d "$project/artifacts/test-run-iso-build-XXXXXXXX")
stamp=$(date +%Y%m%d-%H%M%S)
out=${CARPATIC_ISO_OUTPUT:-$project/iso/out/carpathian-os-dev-$stamp-${run##*/}-x86_64.iso}
case "$out" in /*.iso) ;; *) echo 'CARPATIC_ISO_OUTPUT must be an absolute .iso path.' >&2; exit 1;; esac
partial="$out.part"
for path in "$out" "$partial" "$out.sha256"; do
    if [ -e "$path" ] || [ -L "$path" ]; then echo "Refusing existing output: $path" >&2; exit 1; fi
done
[ -d "$(dirname "$out")" ] || { echo 'Output parent directory must exist.' >&2; exit 1; }
[ -f "$base" ] && [ -f "$prebuilt/SHA256SUMS" ] && [ -f "$apks/SHA256SUMS" ] || { echo 'Missing base ISO or verified prebuilt/APK input manifests.' >&2; exit 1; }
( cd "$prebuilt"; sha256sum -c SHA256SUMS ) >"$run/prebuilt-check.log" 2>&1
python3 alpine/verify-prebuilt.py "$prebuilt" --arch x86_64 >>"$run/prebuilt-check.log"
( cd "$apks"; sha256sum -c SHA256SUMS ) >"$run/apk-check.log" 2>&1
python3 - "$apks" <<'PY_APKS'
import pathlib, sys
root = pathlib.Path(sys.argv[1])
listed = {line.split(maxsplit=1)[1].lstrip('*').removeprefix('./')
          for line in (root / 'SHA256SUMS').read_text().splitlines() if line.strip()}
for path in root.glob('*.apk'):
    if path.is_symlink() or path.name not in listed:
        raise SystemExit('Unverified or symlink APK input: ' + path.name)
PY_APKS
for required in xterm btrfs-progs flock xfdesktop xdg-user-dirs thunar gvfs gvfs-fuse udisks2 udiskie elogind polkit-elogind polkit-gnome elogind-openrc dbus-openrc polkit-openrc; do
    present=0
    for file in "$apks/$required"-[0-9]*.apk; do [ ! -f "$file" ] || present=1; done
    [ "$present" = 1 ] || { echo "Missing required offline package: $required" >&2; exit 1; }
done
sha256sum "$base" >"$run/base-input.sha256"
if [ -n "${CARPATIC_BASE_SHA256:-}" ]; then
    actual=$(sha256sum "$base" | cut -d ' ' -f1)
    [ "$actual" = "$CARPATIC_BASE_SHA256" ] || { echo 'Base ISO hash mismatch.' >&2; exit 1; }
fi
cp "$prebuilt/SHA256SUMS" "$run/prebuilt-input.sha256"
cp "$apks/SHA256SUMS" "$run/apk-input.sha256"
sha256sum "$0" >"$run/build-script.sha256"
stage="$run/stage"
mkdir "$stage"
cleanup() {
    python3 - "$stage" <<'PY_CLEAN'
import pathlib, shutil, sys
path = pathlib.Path(sys.argv[1])
if path.name != 'stage' or not path.parent.name.startswith('test-run-iso-build-'):
    raise SystemExit('Refusing cleanup outside owned ISO stage')
shutil.rmtree(path)
PY_CLEAN
}
trap cleanup EXIT
trap 'exit 130' INT TERM
xorriso -osirrox on -indev "$base" -extract /carpatic-live.apkovl.tar.gz "$stage/base-overlay.tar.gz" >"$stage/extract.log" 2>&1
mkdir -p "$stage/overlay" "$stage/payload"
tar -xzf "$stage/base-overlay.tar.gz" -C "$stage/overlay"
# The greeter uses the Python already carried by the motion package. Make it
# an explicit live dependency and verify the original medium carries its APK.
xorriso -indev "$base" -find /apks -name 'python3-*.apk' -exec echo -- >"$run/live-python-packages.txt" 2>"$run/live-python-inventory.log"
grep -q '/python3-[0-9]' "$run/live-python-packages.txt" || { echo 'Base medium lacks the live greeter Python dependency.' >&2; exit 1; }
python3 integration/carpatic/installer-branding/lib/prepare_overlay.py "$stage/overlay" "$legacy" >"$run/installer-branding-files.txt"
sh integration/carpatic/installer-branding/install.sh --root "$stage/overlay"
cp -R alpine config integration "$stage/payload/"
mkdir -p "$stage/payload/scripts" "$stage/payload/prebuilt"
cp scripts/carpatic-rust-session "$stage/payload/scripts/"
for name in carpatic-wm carpatic-intro-play carpatic-clipwatch carpatic-supertap libcarpatic-livecss.so SHA256SUMS; do
    [ -f "$prebuilt/$name" ] && [ ! -L "$prebuilt/$name" ] || { echo "Missing regular prebuilt input: $name" >&2; exit 1; }
    cp "$prebuilt/$name" "$stage/payload/prebuilt/"
done
cp -R "$apks" "$stage/payload/packages"
cp NOTICE LICENSE "$stage/payload/"
tar --exclude='__pycache__' --exclude='*.pyc' -czf "$stage/carpatic-rust-payload.tar.gz" -C "$stage/payload" .
python3 - "$legacy" "$stage/overlay" <<'PY'
import pathlib, shutil, sys
legacy, overlay = map(pathlib.Path, sys.argv[1:])
engine = overlay / 'usr/local/share/carpatic-rust-installer/engine'
shutil.copytree(legacy / 'installer/engine', engine,
               ignore=shutil.ignore_patterns('dev', 'tests', 'fixtures', 'test*', '__pycache__'))
shutil.copy2(legacy / 'NOTICE', engine / 'LEGACY-NOTICE')
path = engine / 'carpatic-engine'
source = path.read_text()
phase = '''ph_rust() {
  [ "$INST_DESKTOP" = yes ] || { log "Rust desktop skipped (desktop disabled)"; return 0; }
  _payload=""
  for _file in /media/*/carpatic-rust-payload.tar.gz; do
    [ -f "$_file" ] && { _payload=$_file; break; }
  done
  [ -n "$_payload" ] || die "Rust desktop payload is missing from the installer medium"
  mkdir -p "$TARGET/usr/share/carpatic-rust"
  tar -xzf "$_payload" -C "$TARGET/usr/share/carpatic-rust" || die "cannot extract Rust desktop payload"
  in_target /usr/bin/env "CARPATIC_USER=$USERNAME" /bin/sh /usr/share/carpatic-rust/alpine/install-prebuilt.sh >>"$LOG" 2>&1 \\
    || die "Rust desktop installation failed: $(tail -n 3 "$LOG" | tr '\\n' ' ' | cut -c1-300)"
  log "Rust window manager and desktop session installed"
}

'''
needle = 'PHASE_LIST="$PHASE_LIST mkfs bootstrap configure bootloader setup power user snapshot validate cleanup"'
assert source.count(needle) == 1
source = source.replace(needle, phase + needle.replace('user snapshot', 'user rust snapshot'))
needle = '    user) echo "Finalizing user" ;;'
assert source.count(needle) == 1
source = source.replace(needle, needle + '\n    rust) echo "Installing Rust desktop" ;;')
path.write_text(source)
path.chmod(0o755)
bin_dir = overlay / 'usr/local/bin'
bin_dir.mkdir(parents=True, exist_ok=True)
for name in ('carpatic-engine', 'carpatic-install-engine'):
    target = bin_dir / name
    if target.exists() or target.is_symlink(): target.unlink()
    target.symlink_to('/usr/local/share/carpatic-rust-installer/engine/carpatic-engine')
# Explicit selection also protects against a wizard's inherited PATH.
launcher = overlay / 'usr/local/sbin/carpatic-live-installer'
text = launcher.read_text()
text = text.replace('export PATH=',
    'export CARPATIC_ENGINE=/usr/local/bin/carpatic-install-engine\nexport PATH=', 1)
launcher.write_text(text)
PY
sh -n "$stage/overlay/usr/local/share/carpatic-rust-installer/engine/carpatic-engine"
tar --owner=0 --group=0 -czf "$stage/carpatic-live.apkovl.tar.gz" -C "$stage/overlay" .
# Capture every packaged source and input byte; excludes build-only caches.
python3 - "$stage/payload" "$run" <<'PY_MANIFEST'
import hashlib, json, pathlib, sys
payload, run = map(pathlib.Path, sys.argv[1:])
manifest = {str(p.relative_to(payload)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in payload.rglob('*') if p.is_file() and not p.is_symlink()
            and '__pycache__' not in p.parts and p.suffix != '.pyc'}
(run / 'payload-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
PY_MANIFEST
sha256sum "$stage/carpatic-rust-payload.tar.gz" "$stage/carpatic-live.apkovl.tar.gz" >"$run/embedded-inputs.sha256"
# Reserve the partial path exclusively; never remaster an existing image.
(set -C; : >"$partial")
xorriso -indev "$base" -outdev "$partial" -boot_image any replay \
    -map "$stage/carpatic-live.apkovl.tar.gz" /carpatic-live.apkovl.tar.gz \
    -map "$stage/carpatic-rust-payload.tar.gz" /carpatic-rust-payload.tar.gz \
    -commit -end >"$run/iso-remaster.log" 2>&1
# Hard-link publication fails atomically if the final image already exists.
ln "$partial" "$out"
python3 - "$partial" <<'PY_PART'
import pathlib, sys
pathlib.Path(sys.argv[1]).unlink()
PY_PART
(set -C; cd "$(dirname "$out")"; sha256sum "$(basename "$out")" >"$out.sha256")
cp "$out.sha256" "$run/output.sha256"
if [ "$update_latest" = 1 ]; then
    ln -sfn "$out" iso/out/carpatic-rust-latest.iso
fi
printf 'Development installer remaster: %s\nEvidence: %s\n' "$out" "$run"
