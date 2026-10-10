# Contributing

Use Rust 2021 and the pinned Cargo.lock. Alpine shell scripts use POSIX sh. Keep changes focused, describe user-visible behavior and record actual test results.

Run `tests/run.sh --quick` before submitting a change. Window-manager or session changes also require a native Alpine build and relevant isolated X11 checks. Use private Xvfb displays or disposable Alpine VMs; never launch this window manager on your current desktop.

Include reproduction steps, expected behavior, tested configuration and remaining limitations with bug reports. Rendering reports should distinguish settled pixel correctness from transition coverage and physical presentation timing. Benchmark only while no builds or other test suites are running, and report the actual renderer.

Keep credentials, personal settings, VM disks, generated ISO images and raw runtime logs out of source commits. Preserve third-party notices. Release images belong in tagged release assets.
