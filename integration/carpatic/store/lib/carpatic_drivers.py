"""Hardware detection and driver/firmware recommendations for Carpathian (Alpine, apk). Stdlib only.

Everything reads /sys and /proc so it works without pciutils. Detection can be pointed at a fake root for tests with
the CARPATIC_SYSROOT environment variable (a directory containing sys/ and proc/).
"""
import glob
import os
import re
import shutil
import subprocess

VENDORS = {"0x1002": "AMD", "0x8086": "Intel", "0x10de": "NVIDIA", "0x1af4": "Virtio (virtual GPU)",
           "0x15ad": "VMware (virtual GPU)", "0x1234": "QEMU/Bochs (virtual GPU)", "0x1b36": "QEMU (virtual GPU)"}
# PCI vendor ids of common Wi-Fi/Bluetooth chips -> linux-firmware subset (Alpine package suffixes)
WIFI_FW = {"0x8086": ["linux-firmware-intel"], "0x10ec": ["linux-firmware-realtek", "linux-firmware-rtlwifi", "linux-firmware-rtl_bt"],
           "0x14c3": ["linux-firmware-mediatek"], "0x168c": ["linux-firmware-ath10k", "linux-firmware-ath11k", "linux-firmware-ath12k"],
           "0x17cb": ["linux-firmware-ath11k", "linux-firmware-ath12k", "linux-firmware-qca"], "0x14e4": ["linux-firmware-brcm"],
           "0x1814": ["linux-firmware-mediatek"]}


def root(p):
    base = os.environ.get("CARPATIC_SYSROOT", "")
    return os.path.join(base, p.lstrip("/")) if base else p


def read(path, default=""):
    try:
        with open(root(path)) as f:
            return f.read().strip()
    except OSError:
        return default


def apk_installed(pkg):
    if os.environ.get("CARPATIC_SYSROOT"):
        return pkg in read("/installed-apks").split()
    return subprocess.run(["apk", "info", "-e", pkg], capture_output=True).returncode == 0


def pci_devices():
    out = []
    for d in sorted(glob.glob(root("/sys/bus/pci/devices/*"))):
        def r(n):
            try:
                return open(os.path.join(d, n)).read().strip()
            except OSError:
                return ""
        drv = os.path.basename(os.path.realpath(os.path.join(d, "driver"))) if os.path.exists(os.path.join(d, "driver")) else ""
        out.append({"slot": os.path.basename(d), "vendor": r("vendor"), "device": r("device"), "class": r("class"), "driver": drv})
    return out


def gpus():
    res = []
    for d in pci_devices():
        if d["class"].startswith(("0x0300", "0x0302", "0x0380")):
            d = dict(d)
            d["vendor_name"] = VENDORS.get(d["vendor"], d["vendor"])
            res.append(d)
    return res


def cpu_vendor():
    m = re.search(r"vendor_id\s*:\s*(\S+)", read("/proc/cpuinfo"))
    v = m.group(1) if m else ""
    return {"GenuineIntel": "Intel", "AuthenticAMD": "AMD"}.get(v, v or "unknown")


def cpu_model():
    m = re.search(r"model name\s*:\s*(.+)", read("/proc/cpuinfo"))
    return m.group(1).strip() if m else "unknown"


def is_virtual():
    return "hypervisor" in read("/proc/cpuinfo").split("flags")[-1] if "flags" in read("/proc/cpuinfo") else False


def vulkan_devices():
    """Names of Vulkan devices (needs vulkan-tools). [] if not installed or none."""
    if not shutil.which("vulkaninfo"):
        return None
    try:
        t = subprocess.run(["vulkaninfo", "--summary"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return re.findall(r"deviceName\s*=\s*(.+)", t)


def wifi_bt_devices():
    """PCI/USB network and bluetooth devices -> list of (kind, vendor id, firmware packages)."""
    res = []
    for d in pci_devices():
        if d["class"].startswith("0x0280"):
            res.append(("Wi-Fi (PCI)", d["vendor"], WIFI_FW.get(d["vendor"], ["linux-firmware-other"])))
    for dev in glob.glob(root("/sys/bus/usb/devices/*")):
        cls = read(os.path.join(dev, "bDeviceClass"))
        vid = read(os.path.join(dev, "idVendor"))
        if cls == "e0":  # wireless controller (bluetooth)
            res.append(("Bluetooth (USB)", "0x" + vid, ["bluez", "bluez-openrc"] + (["linux-firmware-rtl_bt"] if vid == "0bda" else ["linux-firmware-intel"] if vid == "8087" else ["linux-firmware-qca"] if vid == "0cf3" else [])))
    return res


def has_path(glob_pat):
    return bool(glob.glob(root(glob_pat)))


def detect():
    """Return a list of findings. Each: dict(id, title, status, detail, packages, services, honest)."""
    f = []
    g = gpus()
    kinds = {d["vendor"] for d in g}
    pk_common = ["mesa-dri-gallium", "mesa-va-gallium", "mesa-egl", "mesa-gl", "vulkan-loader", "vulkan-tools"]
    if not g:
        f.append(dict(id="gpu", title="Graphics", status="none", detail="No GPU found on the PCI bus.", packages=[], honest=""))
    for d in g:
        vname = VENDORS.get(d["vendor"], d["vendor"])
        if d["vendor"] == "0x1002":
            pk = pk_common + ["mesa-vulkan-ati", "linux-firmware-amdgpu", "xf86-video-amdgpu"]
            honest = "AMD works best on Alpine: open kernel driver amdgpu + Mesa (OpenGL, Vulkan RADV, video decode). AI: llama.cpp uses Vulkan. ROCm/HIP is not packaged for Alpine."
        elif d["vendor"] == "0x8086":
            pk = pk_common + ["mesa-vulkan-intel", "linux-firmware-i915", "intel-media-driver"]
            honest = "Intel works well: kernel i915/xe + Mesa (OpenGL, Vulkan ANV, VA-API). AI: llama.cpp via Vulkan."
        elif d["vendor"] == "0x10de":
            pk = pk_common + ["mesa-vulkan-nouveau", "linux-firmware-nvidia", "xf86-video-nouveau"]
            honest = ("NVIDIA on Alpine uses the open 'nouveau' kernel driver with Mesa (OpenGL) and NVK (Vulkan, newer cards). "
                      "The proprietary NVIDIA driver and CUDA are glibc-only and do not run on Alpine/musl. What works: desktop, games through Vulkan/NVK "
                      "(slower than the proprietary driver), llama.cpp via Vulkan. For CUDA use the Carpathian compatibility container "
                      "(glibc Ubuntu, 'carpatic-ai compat'); that path is designed but untested on real NVIDIA hardware.")
        else:
            pk = ["mesa-dri-gallium", "mesa-egl", "mesa-gl", "mesa-vulkan-swrast", "vulkan-loader"]
            honest = "Virtual or unknown GPU: software rendering (llvmpipe) is used. Fine for the desktop, slow for games and AI."
        f.append(dict(id="gpu-" + d["slot"], title=f"GPU: {vname} ({d['device']})", status="driver=" + (d["driver"] or "none"),
                      detail=f"kernel driver in use: {d['driver'] or 'none'}", packages=pk, honest=honest))
    cv = cpu_vendor()
    uc = {"Intel": "intel-ucode", "AMD": "amd-ucode"}.get(cv)
    f.append(dict(id="microcode", title=f"CPU microcode ({cv}: {cpu_model()})", status="installed" if uc and apk_installed(uc) else "missing" if uc else "n/a",
                  detail="Microcode fixes CPU bugs and security issues; loaded at boot.", packages=[uc] if uc else [], honest="Takes effect after a reboot."))
    wb = wifi_bt_devices()
    if wb:
        pk = sorted({p for _, _, ps in wb for p in ps})
        miss = [p for p in pk if not apk_installed(p)]
        f.append(dict(id="wifi-bt", title="Wi-Fi / Bluetooth firmware", status="ok" if not miss else "missing: " + " ".join(miss),
                      detail="; ".join(k for k, _, _ in wb), packages=pk, honest="Only the firmware subsets for the chips found are installed (full linux-firmware is large)."))
    else:
        f.append(dict(id="wifi-bt", title="Wi-Fi / Bluetooth firmware", status="n/a", detail="No Wi-Fi or Bluetooth chip detected.", packages=[], honest=""))
    f.append(dict(id="printing", title="Printing", status="installed" if apk_installed("cups") else "not installed",
                  detail="CUPS print system with common driver sets.", packages=["cups", "cups-openrc", "cups-filters", "gutenprint", "hplip", "avahi"],
                  services=["cups", "avahi-daemon"], honest="Most modern printers work driverless over the network (IPP Everywhere)."))
    f.append(dict(id="scanning", title="Scanning", status="installed" if apk_installed("sane") else "not installed",
                  detail="SANE scanner backends and Simple Scan.", packages=["sane", "sane-backends", "sane-airscan", "simple-scan"], honest=""))
    fp = has_path("/sys/bus/usb/devices/*/product") and any("finger" in read(p).lower() for p in glob.glob(root("/sys/bus/usb/devices/*/product")))
    f.append(dict(id="fingerprint", title="Fingerprint reader", status=("detected" if fp else "not detected"),
                  detail="fprintd + libfprint (login integration needs PAM setup).", packages=["fprintd", "libfprint"],
                  honest="Support depends on the reader model (libfprint list). Enrolling a finger: 'fprintd-enroll'."))
    return f


def install_packages(pkgs, on_line=None, password=None):
    import carpatic_store as cs
    code = cs.run(cs.priv_prefix() + ["apk", "add"] + list(pkgs), on_line, password=password)
    if code != 0:
        raise cs.StoreError("Installing driver packages failed (offline, or a package name is missing in this Alpine release).")
    for p, svc in (("cups", "cupsd"), ("bluez", "bluetooth")):
        if p in pkgs:
            cs.run(cs.priv_prefix() + ["rc-update", "add", svc, "default"], None, password=password)
            cs.run(cs.priv_prefix() + ["rc-service", svc, "start"], None, password=password)
