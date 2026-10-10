# Adapted Carpatic desktop regressions

These 19 guest cases retain the earlier Carpatic behavior assertions. The
original source is `../carpatic-os/tests/suites/desktop/guest/` relative to the
project root. WM/executable names, fixture home/display and process matching
are adapted; titlebars are located through the Rust WM's `_CARPATIC_CLIENT`
property. Geometry expectations remain unchanged.

Run on an explicit disposable fixture from the project root:

```sh
tests/run.sh --suite desktop --vm debug-01
# A bounded selection for debugging:
CARPATIC_LEGACY_CASES=23-button-styles,26-window-look tests/run.sh --suite desktop --vm debug-01
```

See `tests/README.md` to create the fixture. The adapter uses key-based,
loopback SSH, a dedicated test account and private guest Xvfb :98. It saves
case-level TAP/logs in the run's evidence directory, retains failures without
automatic retries, and cleans up the account's processes and Xvfb. Exit 77 is
reported as SKIP; other nonzero exits fail the suite.

The fixture disables the Rust-specific fullscreen-space policy so the legacy
macOS green-button tests exercise the original maximize/restore behavior.
Native X11 tests independently cover fullscreen spaces. Geometry expectations
are not loosened to accommodate failed tests.

The early adoption run exposed a real focus defect: layout-generated enter
events stole focus from newly mapped clients. That was fixed in the WM before
the subsequent complete run; its passing result must not be described as a
first-pass result of the earlier code.

This subset is not the legacy distribution's complete installer, security,
power or ISO validation. See `docs/LEGACY-TEST-WORKFLOW.md` for the audit.
