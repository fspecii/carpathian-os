#!/usr/bin/env python3
"""Stage the ARM64 live overlay and existing desktop without host credentials."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parent.parent


def archive(source, output):
    with tarfile.open(output, 'w:gz', format=tarfile.PAX_FORMAT) as target:
        for path in sorted(source.rglob('*')):
            relative = path.relative_to(source)
            if any(part in ('__pycache__', '.git', 'target') for part in relative.parts):
                continue
            required_document = relative == Path('integration/carpatic/stylepacks/RESEARCH.md')
            if path.suffix in ('.pyc', '.log') or (path.suffix == '.md' and not required_document):
                continue
            if path.is_file() and not path.is_symlink():
                with path.open('rb') as file:
                    if file.read(4) == b'\x7fELF' and relative.parts[0] != 'prebuilt':
                        continue
            info = target.gettarinfo(str(path), str(relative))
            info.uid = info.gid = 0
            info.uname = info.gname = 'root'
            if info.isfile():
                with path.open('rb') as file:
                    target.addfile(info, file)
            else:
                target.addfile(info)


def package_metadata(path):
    # Signed APKv2 contains concatenated gzip/tar members. Ignore the tar
    # terminators between signature, metadata and payload members.
    with gzip.open(path, 'rb') as stream:
        with tarfile.open(fileobj=stream, mode='r|', ignore_zeros=True) as package:
            for entry in package:
                if entry.name == '.PKGINFO':
                    info = package.extractfile(entry).read().decode()
                    break
            else:
                raise ValueError(f'Missing APK metadata: {path.name}')
    values = dict(line.split(' = ', 1) for line in info.splitlines() if ' = ' in line)
    return values


def prepare(run, native, repos, world, kernel='lts'):
    listed = {line.split(maxsplit=1)[1].lstrip('*').removeprefix('./')
              for line in (repos / 'SHA256SUMS').read_text().splitlines() if line.strip()}
    available = set()
    for name in ('main', 'community'):
        repo = repos / name
        if not (repo / 'aarch64/APKINDEX.tar.gz').is_file():
            raise ValueError(f'Missing signed {name} aarch64 index')
        index = repo / 'aarch64/APKINDEX.tar.gz'
        if index.is_symlink() or str(index.relative_to(repos)) not in listed:
            raise ValueError(f'Unverified or symlink repository index: {index}')
        for package in (repo / 'aarch64').glob('*.apk'):
            if str(package.relative_to(repos)) not in listed or package.is_symlink():
                raise ValueError(f'Unverified or symlink APK: {package}')
            metadata = package_metadata(package)
            if metadata['arch'] not in ('aarch64', 'noarch'):
                raise ValueError(f'Wrong architecture or symlink APK: {package}')
            available.add(metadata['pkgname'])
        if not (repo / '.boot_repository').is_file():
            raise ValueError(f'Missing live boot repository marker: {repo}')
    packages = sorted(set(world.read_text().split()) | {'alpine-base', 'openssl'})
    if any(not name.isascii() or not name.replace('-', '').replace('+', '').replace('.', '').replace('_', '').isalnum()
           for name in packages):
        raise ValueError('Runtime world must contain only explicit package names')
    if set(packages) - available:
        raise ValueError('Missing explicit live packages: ' + ', '.join(sorted(set(packages) - available)))
    payload = run / 'payload'
    payload.mkdir()
    for directory in ('alpine', 'config', 'integration'):
        shutil.copytree(ROOT / directory, payload / directory,
                        symlinks=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git', '*.log', '*.md'))
    research = Path('integration/carpatic/stylepacks/RESEARCH.md')
    shutil.copy2(ROOT / research, payload / research)
    (payload / 'scripts').mkdir()
    shutil.copy2(ROOT / 'scripts/carpatic-rust-session', payload / 'scripts')
    shutil.copytree(native, payload / 'prebuilt')
    for name in ('LICENSE', 'NOTICE'):
        shutil.copy2(ROOT / name, payload / name)
    archive(payload, run / 'carpathian-arm64-payload.tar.gz')
    overlay = run / 'overlay'
    (overlay / 'etc/apk').mkdir(parents=True)
    (overlay / 'etc/apk/world').write_text('\n'.join(packages) + '\n')
    (overlay / 'etc/hostname').write_text('carpathian-live\n')
    (overlay / 'etc/network').mkdir()
    (overlay / 'etc/network/interfaces').write_text('auto lo\niface lo inet loopback\n')
    (overlay / 'etc/local.d').mkdir()
    shutil.copy2(ROOT / 'alpine/arm64-live.start', overlay / 'etc/local.d/carpathian.start')
    (overlay / 'etc/local.d/carpathian.start').chmod(0o755)
    for level, services in {
        'sysinit': ('devfs', 'dmesg', 'udev', 'udev-trigger', 'udev-settle', 'hwdrivers', 'modloop'),
        'boot': ('modules', 'sysctl', 'hostname', 'bootmisc', 'syslog', 'networking'),
        'default': ('dbus', 'elogind', 'wpa_supplicant', 'networkmanager', 'local'),
        'shutdown': ('mount-ro', 'killprocs', 'savecache'),
    }.items():
        directory = overlay / 'etc/runlevels' / level
        directory.mkdir(parents=True)
        for service in services:
            (directory / service).symlink_to('/etc/init.d/' + service)
    archive(overlay, run / 'carpathian-live.apkovl.tar.gz')
    (run / 'grub.cfg').write_text(f'''set timeout=3
menuentry "Carpathian OS ARM64 development live desktop" {{
linux /boot/vmlinuz-{kernel} modules=loop,squashfs,sd-mod,usb-storage quiet console=tty0 console=ttyAMA0
initrd /boot/initramfs-{kernel}
}}
''')
    manifest = {str(path.relative_to(payload)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in payload.rglob('*') if path.is_file() and not path.is_symlink()}
    (run / 'payload-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'native', 'repos', 'world'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--kernel', choices=('lts', 'virt'), default='lts')
    args = parser.parse_args()
    prepare(args.run, args.native, args.repos, args.world, args.kernel)
