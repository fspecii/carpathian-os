#!/usr/bin/env python3
"""Actual controlling-PTY installer greeting regressions; no desktop input."""
import codecs
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
GREETER = ROOT / 'integration/carpatic/installer-branding/lib/greeter.py'
# Fixed ink from reviewed option19; independent of shipped asset/renderer.
GLYPHS = ((' █████ ', '  ███  ', '██████ ', '██████ ', '  ███  ', '███████', '██   ██', '███████', '  ███  ', '██   ██'), ('██   ██', ' ██ ██ ', '██   ██', '██   ██', ' ██ ██ ', '  ███  ', '██   ██', '  ███  ', ' ██ ██ ', '███  ██'), ('██     ', '██   ██', '██   ██', '██   ██', '██   ██', '  ███  ', '██   ██', '  ███  ', '██   ██', '████ ██'), ('██     ', '██   ██', '██████ ', '██████ ', '██   ██', '  ███  ', '███████', '  ███  ', '██   ██', '██ ████'), ('██     ', '███████', '██ ██  ', '██     ', '███████', '  ███  ', '██   ██', '  ███  ', '███████', '██  ███'), ('██   ██', '██   ██', '██  ██ ', '██     ', '██   ██', '  ███  ', '██   ██', '  ███  ', '██   ██', '██   ██'), (' █████ ', '██   ██', '██   ██', '██     ', '██   ██', '  ███  ', '██   ██', '███████', '██   ██', '██   ██'))

class Terminal:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.row = self.col = 0
        self.cells = {}; self.frames = []; self.text = ''; self.pending = ''
    def feed(self, text):
        self.text += text; self.pending += text
        while self.pending:
            if self.pending.startswith('\x1b'):
                m = re.match(r'\x1b\[([?0-9;]*)([A-Za-z])', self.pending)
                if not m:
                    if len(self.pending) < 24: break
                    raise AssertionError('Unsupported escape sequence')
                args, op = m.groups(); self.pending = self.pending[m.end():]
                if op == 'H':
                    a = [int(x or 1) for x in args.split(';')] if args else [1, 1]
                    self.row, self.col = a[0]-1, (a[1] if len(a)>1 else 1)-1
                    assert 0 <= self.row < self.height and 0 <= self.col < self.width
                elif op == 'J' and args == '2': self.cells = {}
                elif op == 'm':
                    # Complete paint boundaries remain observable without calling renderer functions.
                    self.frames.append(dict(self.cells))
                continue
            ch, self.pending = self.pending[0], self.pending[1:]
            if ch == '\r': self.col = 0; continue
            if ch == '\n': self.row += 1; continue
            assert ch.isprintable(), repr(ch)
            assert 0 <= self.row < self.height and 0 <= self.col < self.width, (self.row,self.col,self.width,self.height)
            self.cells[self.row,self.col] = ch; self.col += 1
    def word(self):
        rows = [''.join(self.cells.get((r,c),' ') for c in range(self.width)) for r in range(self.height)]
        wide = self.width >= 92 and self.height >= 29
        width, stride = (88, 9) if wide else (79, 8)
        left = max(0, (self.width-width)//2)
        return [tuple(r[left+i*stride:left+i*stride+7] for i in range(10)) for r in rows if '█' in r]

class Session:
    def __init__(self, width=80, height=24, reduced=False, renderer=GREETER):
        self.master, self.slave = pty.openpty()
        self.resize(width,height)
        self.saved = termios.tcgetattr(self.slave)
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self.term = Terminal(width,height)
        self.scratch = tempfile.TemporaryDirectory(prefix='carpatic-greeter-test-')
        pid = os.fork()
        if pid == 0:
            os.setsid(); fcntl.ioctl(self.slave, termios.TIOCSCTTY, 0)
            for fd in (0,1,2): os.dup2(self.slave,fd)
            os.close(self.master)
            env = dict(os.environ, TERM='xterm', CARPATIC_CONFIG=self.scratch.name,
                       CARPATIC_NO_ANIM='1' if reduced else '0')
            os.execve(sys.executable,[sys.executable,str(renderer)],env)
        self.pid = pid; self.done = False
    def resize(self,w,h):
        fcntl.ioctl(self.slave,termios.TIOCSWINSZ,struct.pack('HHHH',h,w,0,0))
        if hasattr(self,'term'): self.term.width,self.term.height=w,h
    def read(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if select.select([self.master],[],[],min(.05,max(0,end-time.monotonic())))[0]:
                data=os.read(self.master,65536)
                if data: self.term.feed(self.decoder.decode(data))
    def finish(self, sig=None):
        if sig: os.kill(self.pid,sig)
        else: os.write(self.master,b'\r')
        self.read(.3)
        end=time.monotonic()+3
        while time.monotonic()<end:
            pid,status=os.waitpid(self.pid,os.WNOHANG)
            if pid:
                self.done=True
                assert termios.tcgetattr(self.slave)==self.saved, 'Terminal settings not restored'
                assert '\x1b[?25h' in self.term.text, 'Cursor not restored'
                return os.waitstatus_to_exitcode(status)
            time.sleep(.02)
        raise AssertionError('Greeter failed to exit')
    def close(self):
        if not self.done:
            os.kill(self.pid,signal.SIGKILL); os.waitpid(self.pid,0)
        os.close(self.master); os.close(self.slave); self.scratch.cleanup()

class GreetingTests(unittest.TestCase):
    def test_selected_glyphs_and_bounds(self):
        for size in ((80,24),(100,30)):
            s=Session(*size)
            try:
                s.read(.3); self.assertEqual(s.term.word(),list(GLYPHS))
                self.assertEqual(s.finish(),0)
            finally: s.close()
    def test_rise_loop_and_stable_wordmark(self):
        s=Session(100,30)
        try:
            s.read(.15); early=dict(s.term.cells); self.assertEqual(s.term.word(),list(GLYPHS))
            s.read(2); risen=dict(s.term.cells); self.assertNotEqual(early,risen)
            self.assertEqual(s.term.word(),list(GLYPHS))
            start=len(s.term.text); s.read(.4); first=s.term.text[start:]
            start=len(s.term.text); s.read(.4); second=s.term.text[start:]
            # Compare color assignments for the same mountain row, not byte counts.
            def bands(output):
                return {line
                        for line in re.findall(r'\x1b\[4;7H(.*?)(?=\x1b\[[0-9]+;[0-9]+H)', output, re.S)}
            self.assertTrue(bands(first)); self.assertTrue(bands(second))
            self.assertNotEqual(bands(first),bands(second))
            self.assertEqual(s.term.word(),list(GLYPHS))
            self.assertEqual(s.finish(signal.SIGTERM),130)
        finally:s.close()
    def test_reduced_static_and_resize(self):
        s=Session(100,30,True)
        try:
            s.read(.3); self.assertEqual(s.term.word(),list(GLYPHS))
            n=len(s.term.text); s.read(.35); self.assertEqual(len(s.term.text),n)
            s.resize(80,24); s.read(.4); self.assertEqual(s.term.word(),list(GLYPHS))
            n=len(s.term.text); s.read(.3); self.assertEqual(len(s.term.text),n)
            self.assertEqual(s.finish(),0)
        finally:s.close()
    def check_mountain_anchors(self, renderer=GREETER, sizes=((100,30),(80,24))):
        # Original art coordinate anchors: lower-left baseline establishes one
        # rigid block origin. Peak slopes must descend one column per row.
        for width,height in sizes:
            s=Session(width,height,True,renderer)
            try:
                s.read(.3)
                rows=[''.join(s.term.cells.get((r,c),' ') for c in range(width))
                      for r in range(height)]
                baseline=next(r for r,line in enumerate(rows) if '______' in line)
                origin=rows[baseline].index('_')
                if width==100:
                    top=baseline-8
                    for dy,x in ((0,32),(1,31),(2,30),(3,29)):
                        self.assertEqual(rows[top+dy][origin+x], '/',
                                         f'{width}: mountain slope drift at row{dy}')
                    self.assertEqual(rows[top][origin+33], chr(92))
                else:
                    top=baseline-4
                    self.assertEqual(rows[top][origin+30:origin+33], '(@)')
                    self.assertEqual(rows[top+1][origin+22:origin+24], '/'+chr(92))
                    self.assertEqual(rows[top+2][origin+21], '/')
                    self.assertEqual(rows[top+2][origin+13], '/')
                self.assertEqual(s.finish(),0)
            finally:s.close()

    def test_mountain_rigid_block_anchors(self):
        self.check_mountain_anchors()

    def test_non_tty_returns_without_output(self):
        result=subprocess.run([sys.executable,str(GREETER)],capture_output=True,timeout=3)
        self.assertEqual((result.returncode,result.stdout,result.stderr),(0,b'',b''))

class OverlayHostname(unittest.TestCase):
    def test_staged_default_and_custom_hostname_preserve_legacy(self):
        import importlib.util
        branding = GREETER.parent
        sys.path.insert(0, str(branding))
        try:
            spec = importlib.util.spec_from_file_location('hostname_overlay_subject', branding / 'prepare_overlay.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory); legacy = base / 'legacy'; overlay = base / 'overlay'
                wizard = legacy / 'installer/wizard'; (wizard / 'lib').mkdir(parents=True)
                width = "$(awk '{ if (length > max) max = length } END { print max+0 }' \"$LOGO_PATH\")"
                (wizard / 'carpatic-wizard').write_text(width + '\n${CARPATIC_GREETER_ANIM:-}\n')
                (wizard / 'carpatic-dashboard').write_text(width + '\n')
                (wizard / 'lib/logo.sh').write_text('print_logo() { :; }\n')
                form = "CARPATIC_HOSTNAME_DEFAULT='carpatic'\nchoose_hostname() { hostname=${1:-$CARPATIC_HOSTNAME_DEFAULT}; }\n"
                (wizard / 'lib/form.sh').write_text(form)
                (legacy / 'NOTICE').write_text('Fixture license notice\n')
                launcher = overlay / 'usr/local/sbin/carpatic-live-installer'; launcher.parent.mkdir(parents=True)
                launcher.write_text('WIZ=/usr/share/carpatic/installer/wizard\n'
                    + "$(awk '{ if (length > m) m = length } END { print m + 0 }' \"$WIZ/logo.txt\" 2>/dev/null)\n"
                    + 'logo() { clear; sed "s/^/$(pad_cols)/" "$WIZ/logo.txt" 2>/dev/null; echo; }\nexport PATH=/bin\n')
                world = overlay / 'etc/apk/world'; world.parent.mkdir(parents=True); world.write_text('alpine-base\n')
                changed = module.prepare(overlay, legacy)
                staged = overlay / 'usr/local/share/carpathian-installer/wizard/lib/form.sh'
                self.assertIn(str(staged.relative_to(overlay)), changed)
                self.assertEqual((wizard / 'lib/form.sh').read_text(), form)
                def run(extra, env=None):
                    return subprocess.check_output(['bash', '-c', '. "$1"; ' + extra, 'test', str(staged)],
                        text=True, env={'PATH': '/usr/bin:/bin', **(env or {})}).strip()
                self.assertEqual(run('choose_hostname; printf "%s" "$hostname"'), 'carpathian')
                self.assertEqual(run('choose_hostname review-machine; printf "%s" "$hostname"'), 'review-machine')
                self.assertEqual(run('choose_hostname; printf "%s" "$hostname"',
                                     {'CARPATIC_HOSTNAME_DEFAULT': 'custom-default'}), 'custom-default')
        finally:
            sys.path.remove(str(branding))


class EnginePhaseBranding(unittest.TestCase):
    def setUp(self):
        import importlib.util
        branding = GREETER.parent
        sys.path.insert(0, str(branding))
        self.addCleanup(sys.path.remove, str(branding))
        spec = importlib.util.spec_from_file_location('engine_branding_subject', branding / 'prepare_overlay.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.path = Path(self.scratch.name) / 'carpatic-engine'

    def test_phase_display_changes_with_shell_ids_commands_intact(self):
        for spelling in ('Carpatic', 'Carpatik'):
            source = ('#!/bin/sh\nname_of() {\n  case $1 in\n'
                      f'    setup) echo "Running {spelling} setup" ;;\n'
                      '    user) echo "Finalizing user" ;;\n  esac\n}\n'
                      'PHASE_LIST="setup user"\n'
                      'CARPATIC_SRC=/usr/share/carpatic\n'
                      'carpatic-install -y\n')
            self.path.write_text(source)
            self.path.chmod(0o755)
            self.module.brand_engine(self.path)
            expected = source.replace(f'Running {spelling} setup', 'Running Carpathian setup')
            self.assertEqual(self.path.read_text(), expected)
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o755)
            self.module.brand_engine(self.path)
            self.assertEqual(self.path.read_text(), expected)
            subprocess.run(['sh', '-n', str(self.path)], check=True)
            # Execute only fixture dispatch, avoiding fixture install command.
            dispatch = expected.split('PHASE_LIST=')[0] + 'name_of setup\n'
            result = subprocess.check_output(['sh'], input=dispatch, text=True)
            self.assertEqual(result.strip(), 'Running Carpathian setup')

    def test_missing_duplicate_unknown_context_rejected_without_write(self):
        for source in ('setup) echo "Running unknown setup" ;;\n',
                       '    setup) echo "Running Carpatic setup" ;;\n' * 2,
                       '#    setup) echo "Running Carpatic setup" ;;\n'):
            self.path.write_text(source)
            with self.assertRaises(ValueError):
                self.module.brand_engine(self.path)
            self.assertEqual(self.path.read_text(), source)

    def test_symlink_rejected(self):
        target = self.path.with_name('original-engine')
        source = '    setup) echo "Running Carpatic setup" ;;\n'
        target.write_text(source)
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.module.brand_engine(self.path)
        self.assertEqual(target.read_text(), source)


if __name__=='__main__': unittest.main()
