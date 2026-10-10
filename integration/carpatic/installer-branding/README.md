# Installer identity

The installer combines the original mountain/ridge composition with the selected
Heavy Grotesk Carpathian wordmark. The mountain rows rise once and a quiet light
band travels across them; the wordmark remains steady. Login, Plymouth and
screensaver animation assets remain separate.

The 88-column wordmark is used at 100×30 and larger. An 80×24 composition retains
all ten original seven-column glyphs with one-column letter spacing (79 columns).
Forms and installation progress use this compact identity without animation.

`install.sh --root DIR` installs the isolated greeter and UTF-8 assets.
`lib/prepare_overlay.py OVERLAY LEGACY` prepares an owned extracted live overlay:
it copies the existing installer into a private path, patches its three text-width
and painting hooks, and declares Python as an explicit live dependency. The ISO
builder verifies that the base medium carries the Python APK. The legacy checkout
and existing images are never changed.

The renderer uses Python's standard library, cached assets and one terminal write
per frame at 20 Hz. Enter exits; interrupt/termination restores terminal settings
and the cursor. Reduced-motion and non-TTY modes are supported. No disk or account
operations are performed by the renderer.

Preview frames: `python3 lib/greeter.py --dump NEW_DIR --size 100x30`.
Private controlling-terminal regressions: `python3 tests/installer-branding.py`
from the project root. Actual boot-media qualification is distinct from these
renderer tests.
