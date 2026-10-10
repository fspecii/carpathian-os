#!/usr/bin/env python3
"""Patch an owned extracted installer overlay; never modify the legacy checkout."""
import argparse
from pathlib import Path
import re
import shutil
from greeter import composition

HELPER = '/usr/local/share/carpatic/installer-branding/lib/greeter.py'


def replace_once(text, before, after, label):
    if text.count(before) != 1:
        raise ValueError(f'Expected exactly one {label} hook; inherited installer changed')
    return text.replace(before, after, 1)


def prepare(root, legacy):
    root = root.resolve(strict=True)
    source_dir = legacy.resolve(strict=True) / 'installer/wizard'
    wizard_dir = root / 'usr/local/share/carpathian-installer/wizard'
    wizard = wizard_dir / 'carpatic-wizard'
    dashboard = wizard_dir / 'carpatic-dashboard'
    launcher = root / 'usr/local/sbin/carpatic-live-installer'
    painter = wizard_dir / 'lib/logo.sh'
    # Validate every inherited hook before writing any file.
    patched = {}
    width = "$(awk '{ if (length > max) max = length } END { print max+0 }' \"$LOGO_PATH\")"
    for path in (wizard, dashboard):
        text = (source_dir / path.name).read_text()
        text = replace_once(text, width, f'$(PYTHONUTF8=1 python3 {HELPER} --measure "$LOGO_PATH")', path.name + ' width')
        text = re.sub(r'\bCarpatic\b', 'Carpathian', text)
        text = text.replace('${CYAN}carpatic${RESET}', '${CYAN}Carpathian OS${RESET}')
        if path == wizard:
            text = replace_once(text, '${CARPATIC_GREETER_ANIM:-}',
                                '${CARPATIC_GREETER_ANIM:-/usr/local/bin/carpathian-installer-greeter}',
                                'direct wizard greeter')
        patched[path] = text
    text = launcher.read_text()
    text = replace_once(text, 'WIZ=/usr/share/carpatic/installer/wizard',
                        'WIZ=/usr/local/share/carpathian-installer/wizard', 'private wizard path')
    old = "$(awk '{ if (length > m) m = length } END { print m + 0 }' \"$WIZ/logo.txt\" 2>/dev/null)"
    text = replace_once(text, old, f'$(PYTHONUTF8=1 python3 {HELPER} --measure "$WIZ/logo.txt" 2>/dev/null)', 'launcher width')
    old = 'logo() { clear; sed "s/^/$(pad_cols)/" "$WIZ/logo.txt" 2>/dev/null; echo; }'
    new = f'logo() {{ clear; local pad; pad=$(pad_cols); PYTHONUTF8=1 python3 {HELPER} --print-static --logo "$WIZ/logo.txt" --padding "${{#pad}}"; echo; }}'
    text = replace_once(text, old, new, 'launcher static painter')
    text = replace_once(text, 'export PATH=', 'export CARPATIC_GREETER_ANIM=/usr/local/bin/carpathian-installer-greeter\nexport PATH=', 'launcher environment')
    text = re.sub(r'\bCarpatic\b', 'Carpathian', text)
    patched[launcher] = text
    (source_dir / 'lib/logo.sh').read_text()
    patched[painter] = f'''# UTF-8-safe static identity for installer forms and progress.
print_logo() {{
    PYTHONUTF8=1 python3 {HELPER} --print-static --logo "$LOGO_PATH" --padding "${{1:-0}}"
}}
'''
    lines, _, _ = composition(80, 24)
    patched[wizard_dir / 'logo.txt'] = '\n'.join(text.rstrip() for _, text in lines) + '\n'
    world = root / 'etc/apk/world'
    packages = world.read_text().splitlines()
    if 'python3' not in packages:
        patched[world] = world.read_text().rstrip('\n') + '\npython3\n'
    for relative in ('etc/issue', 'etc/motd', 'usr/local/sbin/carpatic-rootshell',
                     'usr/local/sbin/carpatic-tty1', 'etc/init.d/carpatic-live'):
        path = root / relative
        if path.is_file():
            original = path.read_text()
            changed = re.sub(r'\b(?:Carpatic|Carpatik)\b', 'Carpathian', original)
            if changed != original: patched[path] = changed
    hostname = root / 'etc/hostname'
    if hostname.is_file() and hostname.read_text().strip() == 'carpatic-live':
        patched[hostname] = 'carpathian-live\n'
        hosts = root / 'etc/hosts'
        if hosts.is_file():
            patched[hosts] = re.sub(r'\bcarpatic-live\b', 'carpathian-live', hosts.read_text())
    # A private path prevents APK installation from overwriting staged branding.
    shutil.copytree(source_dir, wizard_dir,
                    ignore=shutil.ignore_patterns('tests', 'fixtures', '__pycache__', '*.pyc', '*.md', '.git', '*.log'))
    shutil.copy2(legacy / 'NOTICE', wizard_dir / 'LEGACY-NOTICE')
    for path, text in patched.items():
        path.write_text(text)
    bin_dir = root / 'usr/local/bin'
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ('carpatic-wizard', 'carpatic-dashboard', 'carpatic-cidata-load'):
        target = bin_dir / name
        if target.exists() or target.is_symlink(): target.unlink()
        target.symlink_to('/usr/local/share/carpathian-installer/wizard/' + name)
    return sorted(str(path.relative_to(root)) for path in patched)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('overlay', type=Path)
    parser.add_argument('legacy', type=Path)
    args = parser.parse_args()
    for path in prepare(args.overlay, args.legacy): print(path)
