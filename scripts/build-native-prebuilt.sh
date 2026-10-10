#!/bin/sh
# Build the five native desktop files on the target Alpine architecture.
set -eu
cd "$(dirname "$0")/.."
[ -f /etc/alpine-release ] || { echo 'Build inside Alpine Linux.' >&2; exit 1; }
arch=$(uname -m)
case "$arch" in x86_64|aarch64) ;; *) echo "Unsupported architecture: $arch" >&2; exit 1;; esac
: "${CARPATIC_NATIVE_OUTPUT:?Select a new absolute output directory}"
case "$CARPATIC_NATIVE_OUTPUT" in /*) ;; *) echo 'Output must be absolute.' >&2; exit 1;; esac
[ ! -e "$CARPATIC_NATIVE_OUTPUT" ] && [ ! -L "$CARPATIC_NATIVE_OUTPUT" ] || { echo 'Output already exists.' >&2; exit 1; }
mkdir -p artifacts
run=$(mktemp -d "$PWD/artifacts/test-run-native-prebuilt-XXXXXXXX")
export CARGO_TARGET_DIR="$run/target"
export CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS:-2}
cargo build --release --locked >"$run/rust-build.log" 2>&1
cc -O2 -Wall -Wextra -DHAVE_X11 -o "$run/carpatic-intro-play" \
    integration/carpatic/motion/src/intro_main.c integration/carpatic/motion/src/intro_scene.c -lX11 -lXext -lm
cc -O2 -o "$run/carpatic-clipwatch" integration/carpatic/geek/src/clipwatch.c -lX11 -lXfixes
cc -O2 -o "$run/carpatic-supertap" integration/carpatic/configurator/share/supertap.c -lX11 -lXi
cc -O2 -fPIC -shared -o "$run/libcarpatic-livecss.so" integration/carpatic/configurator/share/carpatic-livecss.c $(pkg-config --cflags --libs gtk+-3.0 gmodule-2.0)
cp "$CARGO_TARGET_DIR/release/carpatic-wm" "$run/carpatic-wm"
python3 alpine/verify-prebuilt.py "$run" --arch "$arch" >"$run/verification.log"
mkdir "$CARPATIC_NATIVE_OUTPUT"
for file in carpatic-wm carpatic-intro-play carpatic-clipwatch carpatic-supertap libcarpatic-livecss.so; do
    install -m755 "$run/$file" "$CARPATIC_NATIVE_OUTPUT/$file"
done
(cd "$CARPATIC_NATIVE_OUTPUT"; sha256sum carpatic-wm carpatic-intro-play carpatic-clipwatch carpatic-supertap libcarpatic-livecss.so >SHA256SUMS)
printf 'Native %s payload: %s\nEvidence: %s\n' "$arch" "$CARPATIC_NATIVE_OUTPUT" "$run"
