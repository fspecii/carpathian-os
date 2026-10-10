#!/usr/bin/env python3
"""Exercise the login wrapper with stubs; never launch a host WM."""
import os
from pathlib import Path
import subprocess
import signal
import sys
import json
import shlex
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SessionLogging(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='carpatic-session-check-')
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.runtime = self.base / 'runtime with spaces'
        self.runtime.mkdir(mode=0o755)
        self.mark = self.base / 'wm-called'
        self.stub('xsetroot', 'exit 0')
        self.stub('carpatic-wm', 'touch "$WM_MARK"; exit 0')
        self.stub('carpatic-session', 'echo private-profile-marker')
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin)+':/usr/bin:/bin',
                        DISPLAY=':997', DBUS_SESSION_BUS_ADDRESS='stub-only',
                        XDG_RUNTIME_DIR=str(self.runtime), WM_MARK=str(self.mark),
                        XDG_CURRENT_DESKTOP='CarpaticRust')
        self.env.pop('WAYLAND_DISPLAY', None)
        # Test the real wrapper body while redirecting its only managed hook
        # lookup into this fixture. Never execute an installed desktop hook.
        source = (ROOT/'scripts/carpatic-rust-session').read_text()
        managed = 'autostart=/usr/local/share/carpatic-rust/autostart.sh'
        self.assertEqual(source.count(managed), 1)
        self.managed_hook = self.base/'managed-autostart.sh'
        self.wrapper = self.base/'session.sh'
        self.wrapper.write_text(source.replace(managed, 'autostart="'+str(self.managed_hook)+'"'))
        self.old_global = Path('/tmp/carpatic-autostart.log')
        self.before = self.fingerprint(self.old_global)
    def tearDown(self):
        self.assertEqual(self.before, self.fingerprint(self.old_global))
        self.tmp.cleanup()
    @staticmethod
    def fingerprint(path):
        if not path.exists(): return None
        st = path.stat()
        return (st.st_ino, st.st_size, st.st_mtime_ns)
    def stub(self, name, body):
        p = self.bin / name
        p.write_text('#!/bin/sh\n'+body+'\n')
        p.chmod(0o700)
    def run_session(self, **env):
        return subprocess.run(['/bin/sh', str(self.wrapper)],
                              env=dict(self.env, **env), capture_output=True, text=True, timeout=8)
    def await_marker(self, path, marker):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if path.exists() and marker in path.read_text():
                return
            time.sleep(0.01)
        self.fail('Expected owned helper marker did not appear: '+str(path))
    def test_private_unique_logs(self):
        for _ in range(2):
            result = self.run_session()
            self.assertEqual(result.returncode, 0, result.stderr)
        logs = list(self.runtime.glob('carpatic-session-*'))
        self.assertEqual(len(logs), 2)
        self.assertEqual(self.runtime.stat().st_mode & 0o777, 0o700)
        for log in logs:
            self.assertEqual(log.stat().st_mode & 0o777, 0o700)
            outputs = list(log.glob('*.log'))
            self.assertEqual(len(outputs), 1)
            self.assertEqual(outputs[0].stat().st_mode & 0o777, 0o600)
            self.await_marker(outputs[0], 'private-profile-marker')
        self.assertTrue(self.mark.exists())
    def test_autostart_log_private(self):
        hook = self.home/'.local/share/dwm-titus/scripts/autostart.sh'
        hook.parent.mkdir(parents=True)
        hook.write_text('#!/bin/sh\necho autostart-private-marker\n')
        hook.chmod(0o700)
        result = self.run_session()
        self.assertEqual(result.returncode, 0, result.stderr)
        logs = list(self.runtime.glob('carpatic-session-*/autostart.log'))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)
        self.await_marker(logs[0], 'autostart-private-marker')
    def test_managed_hook_priority_is_isolated(self):
        self.managed_hook.write_text('#!/bin/sh\necho managed-private-marker\n')
        self.managed_hook.chmod(0o700)
        result = self.run_session()
        self.assertEqual(result.returncode, 0, result.stderr)
        logs = list(self.runtime.glob('carpatic-session-*/autostart.log'))
        self.assertEqual(len(logs), 1)
        self.await_marker(logs[0], 'managed-private-marker')
        self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)
    def test_detached_helpers_receive_term_and_unrelated_survives(self):
        self.supervision_case(stubborn=False)
    def test_stubborn_detached_helper_is_killed(self):
        self.supervision_case(stubborn=True)
    def supervision_case(self, stubborn):
        ready=self.base/'daemon-ready.json'
        terminated=self.base/'daemon-term'
        helper=self.base/'daemon.py'
        helper.write_text("""import json,os,signal,sys,time
from pathlib import Path
ready=Path(sys.argv[1]); stopped=Path(sys.argv[2]); stubborn=sys.argv[3]=='yes'
def term(*_):
    stopped.write_text('TERM received')
    if not stubborn: raise SystemExit(0)
signal.signal(signal.SIGTERM,term)
ready.write_text(json.dumps({'pid':os.getpid(),'sid':os.getsid(0)}))
while True: time.sleep(.05)
""")
        unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],
                                   env=dict(self.env),start_new_session=True)
        daemon_pid=None
        try:
            # Owned hook launches a helper in a distinct session, then exits.
            launcher=self.base/'launch.py'
            launcher.write_text('import subprocess,sys\nsubprocess.Popen('+repr([sys.executable,str(helper),str(ready),str(terminated),'yes' if stubborn else 'no'])+',start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n')
            self.managed_hook.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(launcher))+'\n')
            self.managed_hook.chmod(0o700)
            waiter=self.base/'wm-stub.py'
            waiter.write_text('import time\nfrom pathlib import Path\np=Path('+repr(str(ready))+')\ndeadline=time.monotonic()+2\nwhile not p.exists() and time.monotonic()<deadline: time.sleep(.01)\nraise SystemExit(0 if p.exists() else 1)\n')
            self.stub('carpatic-wm','exec '+shlex.quote(sys.executable)+' '+shlex.quote(str(waiter)))
            started=time.monotonic()
            result=self.run_session()
            elapsed=time.monotonic()-started
            self.assertEqual(result.returncode,0,result.stderr)
            record=json.loads(ready.read_text()); daemon_pid=record['pid']
            self.assertEqual(record['sid'],daemon_pid,'Helper must really detach')
            self.assertTrue(terminated.exists(),'Helper should receive graceful TERM first')
            self.assertFalse(self.live(daemon_pid),'Owned daemon survives WM exit')
            self.assertIsNone(unrelated.poll(),'Unrelated same-uid/display helper was signaled')
            self.assertLess(elapsed,6)
            if stubborn: self.assertGreaterEqual(elapsed,2)
        finally:
            unrelated.terminate(); unrelated.wait(timeout=3)
            if daemon_pid and self.live(daemon_pid): os.kill(daemon_pid,signal.SIGKILL)
    @staticmethod
    def live(pid):
        try:
            raw=Path('/proc/'+str(pid)+'/stat').read_text()
            return raw[raw.rindex(')')+2:].split()[0]!='Z'
        except FileNotFoundError: return False
    def test_symlink_rejected(self):
        link = self.base/'runtime-link'; link.symlink_to(self.runtime)
        result = self.run_session(XDG_RUNTIME_DIR=str(link))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.mark.exists())
        self.assertEqual(self.runtime.stat().st_mode & 0o777, 0o755)
    def test_other_uid_rejected(self):
        foreign = Path('/tmp')
        if os.getuid() == 0:
            foreign = self.base/'foreign-runtime'
            foreign.mkdir()
            os.chown(foreign, 65534, 65534)
        elif os.getuid() == foreign.stat().st_uid:
            self.skipTest('No accessible foreign-owned directory fixture')
        result = self.run_session(XDG_RUNTIME_DIR=str(foreign))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.mark.exists())
    def test_relative_rejected(self):
        result = self.run_session(XDG_RUNTIME_DIR='relative-runtime')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.mark.exists())
    def test_missing_rejected(self):
        result = self.run_session(XDG_RUNTIME_DIR=str(self.base/'missing'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.mark.exists())

if __name__ == '__main__': unittest.main(verbosity=2)
