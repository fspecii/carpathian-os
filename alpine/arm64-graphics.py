#!/usr/bin/env python3
"""Enable visible software scanout for an unaccelerated virtio GPU."""
import argparse
import os
from pathlib import Path
import platform

CONFIG = '''# Software virtio scanout; accelerated and physical GPUs retain defaults.
Section "OutputClass"
    Identifier "Carpathian virtio software scanout"
    MatchDriver "virtio_gpu"
    Driver "modesetting"
    Option "ShadowFB" "true"
EndSection
'''


def configure(sysfs, root):
    software = accelerated = False
    for device in sysfs.glob('virtio*'):
        try:
            if (device / 'device').read_text().strip() != '0x0010':
                continue
            features = (device / 'features').read_text().strip()
            if not features or set(features) - {'0', '1'}:
                continue
            # Linux exposes features in increasing bit order; virtio GPU
            # VIRGL is bit0. See drivers/virtio/virtio.c and virtio_gpu.h.
            if features[0] == '1':
                accelerated = True
            else:
                software = True
        except OSError:
            continue
    target = root / 'etc/X11/xorg.conf.d/21-carpathian-virtio-software.conf'
    if target.is_symlink() or (target.exists() and target.read_text() != CONFIG):
        raise ValueError('Refusing to replace an independently modified Xorg configuration')
    if software and not accelerated:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(CONFIG)
        target.chmod(0o644)
        return True
    if target.exists():
        target.unlink()
    return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sysfs', type=Path, default=Path('/sys/bus/virtio/devices'))
    parser.add_argument('--root', type=Path, default=Path('/'))
    args = parser.parse_args()
    if args.root.resolve() == Path('/') and (
            os.geteuid() != 0 or platform.machine() != 'aarch64'
            or not Path('/etc/alpine-release').is_file()):
        parser.error('System configuration requires root inside Alpine aarch64')
    print('Software virtio scanout enabled' if configure(args.sysfs, args.root)
          else 'Graphics driver defaults retained')
