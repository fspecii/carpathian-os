# Known limitations (plain words)

Carpatic OS runs on musl, not glibc. We solve most of the pain with `carpatic-compat`, Flatpak and a curated store. These are the
things we cannot (yet) make work, and what to do instead.

| Limit | Why | What to do |
|---|---|---|
| NVIDIA proprietary driver, CUDA and NVENC on the host | NVIDIA ships only glibc userspace libraries; an Xorg built on musl cannot load them | Use the open `nouveau` driver (Vulkan via NVK). For CUDA work use a machine with glibc, or try the compatibility box; CUDA in the box is untested |
| HDR video / HDR monitors | Not supported by X11 | SDR only |
| VirtualBox | No musl build and no Alpine package | QEMU/KVM with virt-manager |
| Games with kernel-level anticheat | Refuse containers and Wine | Not supported |
| `gcompat` | Only covers the loader and a few symbols; most real programs fail with it | Use the compatibility box |
| Software that needs systemd (some vendor installers) | Carpatic uses OpenRC | Run it in the box (it has no systemd either: ask the vendor for a plain `.deb`/AppImage) |
| Hardware-dependent features (Wi-Fi, Bluetooth, GPU video decode, fingerprint, battery life) | Verified only in QEMU so far | Hardware test log: docs/DAILY-DRIVER.md section 6 |
| `.local` (mDNS) name resolution in programs | musl has no NSS modules | Use `avahi-resolve`, or the IP address; the file manager's network view uses avahi directly |
