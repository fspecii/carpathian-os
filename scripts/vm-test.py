#!/usr/bin/env python3
"""Host-only disposable Alpine VM manager. Existing bases are never edited."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
QEMU_NAMES = {'qemu-system-x86_64', 'qemu-system-aarch64'}

def qemu_process(argv):
    return bool(argv) and Path(os.fsdecode(argv[0])).name in QEMU_NAMES

def firmware_path(value):
    if value is None:
        raise RuntimeError('ARM64 requires explicit --qemu, --firmware-code and --firmware-vars paths')
    path = value.resolve(strict=True)
    if not path.is_file() or any(c in str(path) for c in ',\n\r'):
        raise RuntimeError('QEMU/firmware paths must be regular files without comma/newline')
    return path

def arm_command(vm, meta, a, cdrom):
    binary = firmware_path(a.qemu)
    code = firmware_path(a.firmware_code)
    template = firmware_path(a.firmware_vars)
    if not os.access(binary, os.X_OK):
        raise RuntimeError('Explicit QEMU binary is not executable')
    if binary.name != 'qemu-system-aarch64':
        raise RuntimeError('ARM64 binary must be named qemu-system-aarch64 for PID ownership checks')
    if code == template:
        raise RuntimeError('Firmware code and variable template must be distinct')
    if a.graphics != 'software':
        raise RuntimeError('ARM64 fixture currently supports software graphics only')
    variables = vm / 'uefi-vars.fd'
    if variables.is_symlink():
        raise RuntimeError('Refusing symlinked fixture UEFI variable store')
    if variables.exists() and (not variables.is_file() or variables.stat().st_nlink != 1):
        raise RuntimeError('Fixture UEFI variable store must be a regular unshared file')
    if not variables.exists():
        with variables.open('xb') as output, template.open('rb') as source:
            shutil.copyfileobj(source, output)
        variables.chmod(0o600)
    media = []
    if cdrom:
        media = ['-device', 'virtio-scsi-pci,id=scsi', '-drive', f'if=none,id=cd,file={cdrom},format=raw,media=cdrom,readonly=on', '-device', 'scsi-cd,drive=cd,bootindex=1']
    return [str(binary), '-name', f'Carpathian OS test {a.name}',
            '-machine', 'virt,gic-version=3,pflash0=firmware,pflash1=variables',
            '-cpu', 'cortex-a72', '-accel', 'tcg', '-smp', '2', '-m', str(a.ram),
            '-blockdev', f'node-name=firmware,driver=file,filename={code},read-only=true',
            '-blockdev', f'node-name=variables,driver=file,filename={variables}',
            '-device', 'virtio-gpu-pci', '-display', 'gtk,grab-on-hover=on' if a.display == 'gtk' else 'none',
            '-drive', f'if=none,id=disk,file={vm / "overlay.qcow2"},format=qcow2',
            '-device', 'virtio-blk-pci,drive=disk,bootindex=2',
            '-netdev', f'user,id=n0,hostfwd=tcp:127.0.0.1:{meta["port"]}-:22',
            '-device', 'virtio-net-pci,netdev=n0', '-device', 'qemu-xhci',
            '-device', 'usb-tablet', '-device', 'usb-kbd',
            '-serial', f'file:{vm / "run/serial.log"}',
            '-monitor', f'unix:{vm / "run/monitor.sock"},server,nowait',
            '-pidfile', str(vm / 'run/qemu.pid'), '-daemonize'] + media

def call(argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)

def live(vm):
    try:
        pid = int((vm / 'run/qemu.pid').read_text())
        args = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return pid if qemu_process(args) and any(str(vm / 'overlay.qcow2').encode() in a for a in args) else None
    except (OSError, ValueError):
        return None

def monitor(vm, command):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(5)
        sock.connect(str(vm / 'run/monitor.sock'))
        banner = b''
        while not banner.endswith(b'(qemu) '):
            part = sock.recv(4096)
            if not part: raise RuntimeError('QEMU monitor closed before prompt')
            banner += part
        sock.sendall(command.encode() + b'\n')
        reply = b''
        while not reply.endswith(b'(qemu) '):
            part = sock.recv(4096)
            if not part: break
            reply += part
        return reply

def ssh_args(vm, meta, scp=False):
    return ['scp' if scp else 'ssh', '-i', meta['key'], '-o', 'BatchMode=yes',
            '-o', 'IdentitiesOnly=yes', '-o', 'ConnectTimeout=5',
            '-o', 'StrictHostKeyChecking=accept-new', '-o', f'UserKnownHostsFile={vm / "known_hosts"}',
            '-P' if scp else '-p', str(meta['port'])]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True, help='Unique disposable VM name')
    sub = parser.add_subparsers(dest='command', required=True)
    clone = sub.add_parser('clone')
    clone.add_argument('--arch', choices=['x86_64', 'aarch64'], default='x86_64')
    clone.add_argument('--base', required=True, type=Path)
    clone.add_argument('--key', required=True, type=Path, help='Existing guest-authorized key (never copied)')
    clone.add_argument('--port', required=True, type=int)
    start = sub.add_parser('start')
    start.add_argument('--qemu', type=Path, help='Explicit ARM64 QEMU executable')
    start.add_argument('--firmware-code', type=Path, help='Read-only ARM64 UEFI code image')
    start.add_argument('--firmware-vars', type=Path, help='ARM64 UEFI variable template copied into fixture')
    start.add_argument('--graphics', choices=['software', 'virgl'], default='software')
    start.add_argument('--ram', type=int, default=1536)
    start.add_argument('--display', choices=['headless', 'gtk'], default='headless', help='Open a QEMU window only for requested inspection')
    start.add_argument('--cdrom', type=Path, help='Read-only development ISO; boot CD only, never install automatically')
    sub.add_parser('status'); sub.add_parser('stop'); sub.add_parser('destroy')
    wait = sub.add_parser('wait'); wait.add_argument('--timeout', type=int, default=60)
    ssh = sub.add_parser('ssh'); ssh.add_argument('remote_command')
    for action in ('put', 'get'):
        copy = sub.add_parser(action); copy.add_argument('source'); copy.add_argument('destination')
    shot = sub.add_parser('shot'); shot.add_argument('output', type=Path)
    a = parser.parse_args()
    cdrom = None
    cdrom_hash = None
    if a.command == 'start' and a.cdrom is not None:
        cdrom = a.cdrom.resolve(strict=True)
        if not cdrom.is_file() or cdrom.suffix.lower() != '.iso' or any(c in str(cdrom) for c in ',\n\r'):
            parser.error('CDROM must be a regular .iso file without comma/newline in its path')
        digest = hashlib.sha256()
        with cdrom.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        cdrom_hash = digest.hexdigest()
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', a.name): parser.error('Use a lowercase VM name')
    vm = ROOT / 'vm' / ('test-' + a.name)
    if a.command == 'clone':
        base = a.base.resolve(strict=True); key = a.key.resolve(strict=True)
        if not 1024 <= a.port <= 65535: parser.error('Port must be 1024–65535')
        if vm.exists(): parser.error('VM already exists; select a fresh name')
        # Refuse to clone a currently writable source disk.
        for proc in Path('/proc').glob('[0-9]*/cmdline'):
            try:
                argv = proc.read_bytes().split(b'\0')
                if qemu_process(argv) and any(str(base).encode() in x for x in argv):
                    parser.error('Stop the source VM before cloning it')
            except OSError: pass
        vm.mkdir(parents=True); (vm / 'run').mkdir()
        try:
            call(['qemu-img', 'create', '-q', '-f', 'qcow2', '-F', 'qcow2', '-b', str(base), str(vm / 'overlay.qcow2')])
            (vm / 'fixture.json').write_text(json.dumps(dict(base=str(base), key=str(key), port=a.port, arch=a.arch), indent=2)+'\n')
        except Exception:
            shutil.rmtree(vm); raise
        print(f'Created {vm}'); return
    meta = json.loads((vm / 'fixture.json').read_text())
    if a.command == 'start':
        with (ROOT / 'vm/.test-start.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if live(vm): print('Already running'); return
            active = 0
            for p in Path('/proc').glob('[0-9]*/cmdline'):
                try: active += qemu_process(p.read_bytes().split(b'\0'))
                except OSError: pass
            if active >= 4: raise RuntimeError('Four shared VMs are already running')
            available = int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))
            if available < (a.ram + 1024)*1024: raise RuntimeError('Insufficient available host memory; preserve 1 GiB headroom')
            if meta.get('arch', 'x86_64') == 'x86_64' and not os.access('/dev/kvm', os.R_OK | os.W_OK): raise RuntimeError('KVM is required')
            if a.graphics == 'virgl':
                display, device = 'egl-headless,rendernode=/dev/dri/renderD128', 'virtio-vga-gl'
            else: display, device = 'none', 'virtio-vga'
            if a.display == 'gtk':
                display = 'gtk,grab-on-hover=on' + (',gl=on' if a.graphics == 'virgl' else '')
            media = (['-drive', f'file={cdrom},format=raw,media=cdrom,readonly=on', '-boot', 'order=d,strict=on'] if cdrom else [])
            argv = ['qemu-system-x86_64', '-name', f'Carpathian OS test {a.name}',
                  '-machine', 'q35,accel=kvm,vmport=off', '-cpu', 'host', '-smp', '2', '-m', str(a.ram),
                  '-device', device+',edid=on,xres=1360,yres=768', '-display', display,
                  '-drive', f'file={vm / "overlay.qcow2"},format=qcow2,if=virtio',
                  '-netdev', f'user,id=n0,hostfwd=tcp:127.0.0.1:{meta["port"]}-:22', '-device', 'virtio-net-pci,netdev=n0',
                  '-device', 'qemu-xhci', '-device', 'usb-tablet', '-device', 'usb-kbd',
                  '-serial', f'file:{vm / "run/serial.log"}', '-monitor', f'unix:{vm / "run/monitor.sock"},server,nowait',
                  '-pidfile', str(vm / 'run/qemu.pid'), '-daemonize'] + media
            if meta.get('arch', 'x86_64') == 'aarch64':
                argv = arm_command(vm, meta, a, cdrom)
            elif any((a.qemu, a.firmware_code, a.firmware_vars)):
                parser.error('ARM64 firmware arguments require an aarch64 fixture')
            call(argv, env={k:v for k,v in os.environ.items() if k != 'WAYLAND_DISPLAY'})
            if meta.get('arch', 'x86_64') == 'aarch64':
                meta.update(qemu=str(a.qemu.resolve()), firmware_code=str(a.firmware_code.resolve()), firmware_vars_template=str(a.firmware_vars.resolve()), firmware_vars=str(vm / 'uefi-vars.fd'), acceleration='tcg')
            meta.update(graphics=a.graphics, ram_mib=a.ram, cdrom=str(cdrom) if cdrom else None, cdrom_sha256=cdrom_hash, boot_order='d' if cdrom else 'default')
            (vm / 'fixture.json').write_text(json.dumps(meta, indent=2)+'\n')
            print(f'Started {a.name} ({a.graphics}, SSH 127.0.0.1:{meta["port"]})')
    elif a.command == 'status': print('running' if live(vm) else 'stopped')
    elif a.command == 'wait':
        end = time.monotonic()+a.timeout
        while time.monotonic() < end:
            if not live(vm): raise RuntimeError('VM stopped before SSH became ready')
            result = subprocess.run(ssh_args(vm, meta)+['root@127.0.0.1', 'true'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0: print('SSH ready'); return
            time.sleep(1)
        raise RuntimeError('SSH boot timeout; inspect run/serial.log')
    elif a.command == 'ssh':
        call(ssh_args(vm,meta)+['root@127.0.0.1', 'unset WAYLAND_DISPLAY; '+a.remote_command])
    elif a.command in ('put', 'get'):
        src, dst = a.source, a.destination
        if a.command == 'put': dst = 'root@127.0.0.1:'+dst
        else: src = 'root@127.0.0.1:'+src
        call(ssh_args(vm,meta,True)+[src,dst])
    elif a.command == 'shot':
        out=a.output.resolve(); out.parent.mkdir(parents=True,exist_ok=True)
        if any(c.isspace() for c in str(out)): raise RuntimeError('Screenshot path must not contain whitespace')
        reply=monitor(vm,'screendump '+str(out))
        if not out.exists():
            detail = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', reply.decode(errors='replace'))
            raise RuntimeError('Screenshot failed: '+detail.splitlines()[-2][:200])
    elif a.command in ('stop','destroy'):
        if a.command == 'destroy' and (
            meta.get('protected') or (vm / 'USER-PREVIEW-DO-NOT-DESTROY').exists()
        ):
            raise RuntimeError('Refusing to destroy a protected user preview; no VM was stopped')
        pid=live(vm)
        if pid:
            monitor(vm,'system_powerdown')
            end=time.monotonic()+20
            while live(vm) and time.monotonic()<end: time.sleep(.2)
            if live(vm):
                os.kill(pid,signal.SIGTERM)
                end=time.monotonic()+5
                while live(vm) and time.monotonic()<end: time.sleep(.2)
            if live(vm): raise RuntimeError('VM did not stop; refusing disk deletion')
        if a.command == 'destroy': shutil.rmtree(vm); print('Removed disposable VM')
        else: print('Stopped')

if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'vm-test: {error}', file=sys.stderr); sys.exit(1)
