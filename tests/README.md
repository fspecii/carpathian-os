# Testing

`tests/run.sh --quick` runs host logic, theme and private-Xvfb checks. `--standard --vm NAME` adds native Alpine builds; `--full --vm NAME` adds adapted desktop checks. Use `tests/run.sh --list` for available suites.

Create a unique disposable fixture from a stopped development base with explicit authorized SSH key and loopback port:

```sh
scripts/vm-test.sh --name test-01 clone --base /path/to/stopped-base.qcow2 --key /path/to/authorized-key --port 2271
scripts/vm-test.sh --name test-01 start --graphics software
scripts/vm-test.sh --name test-01 wait
tests/run.sh --standard --vm test-01
scripts/vm-test.sh --name test-01 destroy
```

The base must include the development desktop and build/test dependencies; missing dependencies fail checks. Do not modify shared backing images. GUI tests use private Xvfb or isolated guest Xorg with WAYLAND_DISPLAY unset. Never launch the WM on an existing host desktop.

Results are written under ignored artifacts/test-run-* with suite logs and actual exit status. Real compositor suites test installed guest code, so deploy the intended native binary and helper versions before running them. Renderer identity comes from `glxinfo -B`; a virtual 3D device alone does not prove acceleration.

Performance runs must be exclusive of builds and other suites. Root-pixel checks do not measure physical FPS. Restore preferences and destroy disposable fixtures after testing; retain evidence outside source commits.


The fixture manager refuses new clones or ordinary VM starts below 1 GiB of available host disk space. Starting with `--cdrom` requires at least 6 GiB because installation expands the writable overlay. These are startup checks; monitor free space during longer runs and stop disposable workloads before exhausting storage. Already-running VMs are not stopped by these checks. At most four QEMU VMs may run concurrently.

## Installer identity

The quick suite includes five private controlling-terminal checks for the selected wordmark, mountain alignment, animation/reduced motion, resize and terminal restoration. They require no graphical desktop. Theme checks include canonical/symbolic logo geometry and palette contrast.
